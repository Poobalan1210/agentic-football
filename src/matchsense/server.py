"""FastAPI app: API routes, SSE replay stream, and the single-page frontend from web/.

Run: uvicorn matchsense.server:app --reload   ->  http://localhost:8000
No authentication: intended for local use only (it spends your Bedrock and Decider quota).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import persistence
from .benchmark_runner import run_benchmark
from .config import WEB_DIR, settings
from .jobs import JOBS, Job
from .metrics import to_csv
from .policy_decision import POLICY_OPTIONS, QUESTION
from .replay import run_match
from .runtime import runtime
from .scenarios import match, matches, reference_labels, scenario, scenarios
from .schemas import MatchState
from .state_text import state_to_text

app = FastAPI(title="MatchSense", version="0.1.0")


@app.exception_handler(HTTPException)
async def _http_err(_: Request, e: HTTPException) -> JSONResponse:
    return JSONResponse({"error": e.detail, "status": e.status_code}, status_code=e.status_code)


@app.exception_handler(RequestValidationError)
async def _val_err(_: Request, e: RequestValidationError) -> JSONResponse:
    return JSONResponse({"error": "invalid request", "details": json.loads(json.dumps(e.errors(), default=str))},
                        status_code=422)


@app.exception_handler(Exception)
async def _any_err(_: Request, e: Exception) -> JSONResponse:
    return JSONResponse({"error": f"{type(e).__name__}: {e}", "status": 500}, status_code=500)


# ---- health -------------------------------------------------------------------------------------

_health_cache: dict[str, Any] = {}
_health_lock = threading.Lock()


def _bedrock_status(rt) -> dict:
    """One tiny Nova Micro call, cached for 10 minutes (it costs money)."""
    if rt.mode == "mock":
        return {"ok": True, "mock": True}
    with _health_lock:
        c = _health_cache.get("bedrock")
        if c and time.time() - c[0] < 600:
            return c[1]
    res = rt.tactics.client.ping()
    res["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _health_lock:
        _health_cache["bedrock"] = (time.time(), res)
    return res


@app.get("/api/health")
def health(bedrock: bool = True) -> dict:
    rt = runtime()
    try:
        dec = rt.decider.health()
    except Exception as e:  # noqa: BLE001
        dec = {"ok": False, "error": f"{getattr(e, 'kind', type(e).__name__)}: {e}"}
    return {"mode": rt.mode, "config": settings().public(), "decider": dec,
            "bedrock": _bedrock_status(rt) if bedrock else {"skipped": True}}


# ---- data ---------------------------------------------------------------------------------------

@app.get("/api/scenarios")
def list_scenarios() -> dict:
    labels = reference_labels()
    return {"question": QUESTION, "options": POLICY_OPTIONS,
            "items": [{"id": s["id"], "title": s["title"], "kind": s["kind"], "base_id": s["base_id"],
                       "state": s["state"], "reference": labels.get(s["id"])} for s in scenarios()]}


@app.get("/api/matches")
def list_matches() -> dict:
    return {"items": [{"id": m["id"], "title": m["title"], "ticks": len(m["ticks"]), "final_score": m["final_score"],
                       "tick_s": m["tick_s"]} for m in matches()]}


@app.get("/api/matches/{match_id}")
def get_match(match_id: str) -> dict:
    try:
        return match(match_id)
    except KeyError:
        raise HTTPException(404, f"unknown match {match_id}") from None


class StateTextReq(BaseModel):
    state: MatchState


@app.post("/api/state_text")
def state_text(req: StateTextReq) -> dict:
    return {"state_text": state_to_text(req.state)}


class PromptsReq(BaseModel):
    state_text: str = Field(min_length=1, max_length=20000)
    policy: Literal["HIGH_PRESS", "COUNTERATTACK", "KEEP_POSSESSION", "PROTECT_LEAD", "LOW_BLOCK"] | None = None


@app.post("/api/prompts")
def prompts(req: PromptsReq) -> dict:
    """The exact inputs the code builds for this state text (no model is called)."""
    from .policy_decision import FAST_SYSTEM, fast_prompt
    from .tactical_planner import PLANNER_SYSTEM, choose_and_plan_prompt, plan_prompt

    s = settings()
    out = {
        "decider": {"endpoint": f"POST {'/v1/systemone' if s.decider_mode == 'local' else '/v1/decide'}",
                    "body": {"state": req.state_text,
                             "questions": {"policy": {"type": "choice", "instructions": QUESTION, "criteria": POLICY_OPTIONS}}}},
        "nova_pro_choose_and_plan": {"model": s.nova_planner_model_id, "system": PLANNER_SYSTEM,
                                     "user": choose_and_plan_prompt(req.state_text), "output_schema": "PolicyAndPlan"},
        "nova_pro_choose": {"model": s.nova_planner_model_id, "system": FAST_SYSTEM, "user": fast_prompt(req.state_text),
                            "output_schema": "PolicyChoice"},
        "nova_micro_choose": {"model": s.nova_fast_model_id, "system": FAST_SYSTEM, "user": fast_prompt(req.state_text),
                              "output_schema": "PolicyChoice"},
    }
    if req.policy:
        out["nova_pro_plan"] = {"model": s.nova_planner_model_id, "system": PLANNER_SYSTEM,
                                "user": plan_prompt(req.state_text, req.policy), "output_schema": "TacticalPlan"}
    return out


# ---- lab ----------------------------------------------------------------------------------------

class LabReq(BaseModel):
    scenario_id: str | None = None
    state: MatchState | None = None
    flows: list[Literal["A", "A2", "B1", "B2"]] = Field(default_factory=lambda: ["A", "B2"], min_length=1)
    threshold: float | None = Field(default=None, ge=0, le=1)
    fallback_mode: Literal["nova_micro", "nova_pro", "hold", "none"] | None = None


@app.post("/api/lab/run")
def lab_run(req: LabReq) -> dict:
    if req.state is None and req.scenario_id is None:
        raise HTTPException(400, "give scenario_id or state")
    if req.state is not None:
        state = req.state
    else:
        try:
            state = MatchState.model_validate(scenario(req.scenario_id)["state"])
        except KeyError:
            raise HTTPException(404, f"unknown scenario {req.scenario_id}") from None
    text = state_to_text(state)
    rt = runtime()
    from concurrent.futures import ThreadPoolExecutor

    flows = list(dict.fromkeys(req.flows))
    with ThreadPoolExecutor(max_workers=len(flows)) as pool:
        futs = {f: pool.submit((rt.lane(f, req.threshold, req.fallback_mode) if f in ("A", "A2") else rt.lane(f)).step, 0, text) for f in flows}
        results = {f: fut.result().model_dump(mode="json") for f, fut in futs.items()}
    ref = reference_labels().get(req.scenario_id) if req.scenario_id and req.state is None else None
    return {"mode": rt.mode, "state_text": text, "question": QUESTION, "options": POLICY_OPTIONS,
            "reference": ref, "results": results}


# ---- replay -------------------------------------------------------------------------------------

class ReplayReq(BaseModel):
    match_id: str
    agent: Literal["A", "A2"] = "A"
    baseline: Literal["B1", "B2"] = "B2"
    paced: bool = True
    threshold: float | None = Field(default=None, ge=0, le=1)
    fallback_mode: Literal["nova_micro", "nova_pro", "hold", "none"] | None = None
    max_ticks: int | None = Field(default=None, ge=1, le=200)


@app.post("/api/replay/run")
def replay_run(req: ReplayReq) -> dict:
    try:
        match(req.match_id)
    except KeyError:
        raise HTTPException(404, f"unknown match {req.match_id}") from None
    rt = runtime()

    def work(job: Job) -> dict:
        def on_event(ev: dict) -> None:
            job.done_count += 1
            job.progress = job.done_count / max(job.total, 1)
            job.emit(ev)

        run = run_match(req.match_id, [req.agent, req.baseline], rt, run_id=job.id, pace=req.paced, threshold=req.threshold,
                        on_event=on_event, max_ticks=req.max_ticks, should_stop=job.stop_flag.is_set,
                        fallback_mode=req.fallback_mode)
        run["baseline"], run["agent"] = req.baseline, req.agent
        persistence.save(rt.mode, "replays", job.id, run)
        return {"run_id": job.id}

    job = JOBS.start("replay", work)
    job.total = req.max_ticks or len(match(req.match_id)["ticks"])
    job.emit({"type": "start", "run_id": job.id, "match_id": req.match_id, "baseline": req.baseline, "mode": rt.mode,
              "total": job.total})
    return {"run_id": job.id, "mode": rt.mode}


def _sse(job: Job):
    i = 0
    while True:
        with job._cv:
            while i >= len(job.events):
                job._cv.wait(timeout=15)
                if i >= len(job.events):
                    break
            batch = job.events[i:]
        if not batch:
            yield ": keep-alive\n\n"
            continue
        for ev in batch:
            i += 1
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
            if ev["type"] == "end":
                return


@app.get("/api/replay/{run_id}/stream")
def replay_stream(run_id: str) -> StreamingResponse:
    job = JOBS.get(run_id)
    if job is None or job.kind != "replay":
        raise HTTPException(404, "no live run with that id (stored runs: GET /api/replay/{run_id})")
    return StreamingResponse(_sse(job), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/replay/{run_id}/stop")
def replay_stop(run_id: str) -> dict:
    job = JOBS.get(run_id)
    if job is None:
        raise HTTPException(404, "no live run with that id")
    job.stop_flag.set()
    return job.summary()


@app.get("/api/replay/{run_id}")
def replay_get(run_id: str) -> dict:
    got = persistence.load("replays", run_id)
    if got is None:
        job = JOBS.get(run_id)
        if job is not None:
            raise HTTPException(409, f"run is still {job.status}; it is stored when it finishes")
        raise HTTPException(404, "no stored run with that id")
    mode, run = got
    run["stored_mode"] = mode
    return run


@app.get("/api/replays")
def replays() -> dict:
    return {"items": persistence.list_items("replays", ("run_id", "match_id", "match_title", "baseline", "flows", "started_at",
                                                         "finished_at", "status", "mode"))}


# ---- benchmark ----------------------------------------------------------------------------------

class BenchReq(BaseModel):
    suites: list[Literal["variants", "matches"]] = Field(default_factory=lambda: ["variants"], min_length=1)
    flows: list[Literal["A", "A2", "B1", "B2"]] = Field(default_factory=lambda: ["A", "A2", "B1", "B2"], min_length=1)
    trials: int = Field(default=1, ge=1, le=5)
    threshold: float | None = Field(default=None, ge=0, le=1)
    match_ids: list[str] | None = None
    max_items: int | None = Field(default=None, ge=1, le=500)
    fallback_mode: Literal["nova_micro", "nova_pro", "hold", "none"] | None = None


@app.post("/api/benchmark/run")
def bench_run(req: BenchReq) -> dict:
    rt = runtime()

    def work(job: Job) -> dict:
        res = run_benchmark(rt, suites=req.suites, flows=list(dict.fromkeys(req.flows)), trials=req.trials,
                            threshold=req.threshold, match_ids=req.match_ids, max_items=req.max_items, job=job,
                            fallback_mode=req.fallback_mode)
        res["job_id"] = job.id
        res["started_at"] = res["finished_at"]
        persistence.save(rt.mode, "benchmarks", job.id, res)
        return {"job_id": job.id}

    job = JOBS.start("bench", work)
    return {"job_id": job.id, "mode": rt.mode}


@app.get("/api/benchmark/{job_id}")
def bench_get(job_id: str, rows: bool = False) -> dict:
    job = JOBS.get(job_id)
    got = persistence.load("benchmarks", job_id)
    if got is None:
        if job is None:
            raise HTTPException(404, "no benchmark with that id")
        return {**job.summary(), "result": None}
    mode, res = got
    out = {**(job.summary() if job else {"job_id": job_id, "status": "done", "progress": 1.0}), "stored_mode": mode,
           "result": {k: v for k, v in res.items() if rows or k != "rows"}}
    return out


@app.get("/api/benchmarks")
def benchmarks() -> dict:
    return {"items": persistence.list_items("benchmarks", ("job_id", "finished_at", "mode", "config"))}


@app.get("/api/export/{job_id}.csv")
def export_csv(job_id: str) -> PlainTextResponse:
    got = persistence.load("benchmarks", job_id)
    if got is None:
        raise HTTPException(404, "no stored benchmark with that id")
    return PlainTextResponse(to_csv(got[1]["rows"]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{job_id}.csv"'})


@app.get("/api/export/{job_id}.json")
def export_json(job_id: str) -> JSONResponse:
    got = persistence.load("benchmarks", job_id)
    if got is None:
        raise HTTPException(404, "no stored benchmark with that id")
    return JSONResponse(got[1], headers={"Content-Disposition": f'attachment; filename="{job_id}.json"'})


# ---- frontend -----------------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
