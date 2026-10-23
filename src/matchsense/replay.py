"""Plays a scripted match through the Hybrid lane and one or more baseline lanes, tick by tick.

All lanes receive the identical state text each tick and run concurrently, so each lane's latency
is its own. With `pace=True` a tick lasts at least TICK_SECONDS (the simulated match clock); a lane
slower than that simply makes the tick longer, and that is recorded, never hidden.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .scenarios import match as load_match
from .schemas import MatchState
from .state_text import state_to_text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_counters() -> dict[str, float]:
    return {"bedrock_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "deadline_misses": 0,
            "policy_switches": 0, "plan_calls": 0, "fallbacks": 0, "decider_calls": 0, "errors": 0, "ticks": 0}


def add_counters(c: dict, r: dict) -> None:
    c["ticks"] += 1
    c["bedrock_calls"] += r["bedrock_calls"]
    c["input_tokens"] += r["input_tokens"]
    c["output_tokens"] += r["output_tokens"]
    c["cost_usd"] = round(c["cost_usd"] + r["cost_usd"], 8)
    c["deadline_misses"] += int(r["deadline_missed"])
    c["policy_switches"] += int(r["policy_changed"] and r["active_policy_before"] is not None)
    c["plan_calls"] += int(r["plan_called"])
    c["fallbacks"] += int(r["decision"]["fallback"])
    c["decider_calls"] += int(r["decision"]["raw_decider_policy"] is not None or r["decision"]["decider_error"] is not None)
    c["errors"] += int(r["decision"]["effective_policy"] is None or bool(r["plan_error"]))


def run_match(match_id: str, flows: list[str], rt, *, run_id: str, pace: bool = False,
              threshold: float | None = None, on_event: Callable[[dict], None] | None = None,
              max_ticks: int | None = None, should_stop: Callable[[], bool] | None = None,
              fallback_mode: str | None = None) -> dict[str, Any]:
    s = settings()
    m = load_match(match_id)
    lanes = {f: rt.lane(f, threshold, fallback_mode) if f in ("A", "A2") else rt.lane(f) for f in flows}
    counters = {f: _empty_counters() for f in flows}
    run: dict[str, Any] = {
        "run_id": run_id, "match_id": match_id, "match_title": m["title"], "flows": flows, "mode": rt.mode,
        "started_at": now_iso(), "finished_at": None, "status": "running",
        "config": {**s.public(), "confidence_threshold": threshold if threshold is not None else s.confidence_threshold,
                   "fallback_mode": fallback_mode or s.fallback_mode,
                   "paced": pace},
        "ticks": [], "totals": counters,
    }
    ticks = m["ticks"][:max_ticks] if max_ticks else m["ticks"]
    with ThreadPoolExecutor(max_workers=len(flows)) as pool:
        for t in ticks:
            if should_stop and should_stop():
                run["status"] = "stopped"
                break
            t0 = time.perf_counter()
            state = MatchState.model_validate(t["state"])
            text = state_to_text(state)
            futs = {f: pool.submit(lanes[f].step, t["tick"], text) for f in flows}
            results = {f: fut.result().model_dump(mode="json") for f, fut in futs.items()}
            for f, r in results.items():
                add_counters(counters[f], r)
            wall = (time.perf_counter() - t0) * 1000
            ev = {"type": "tick", "tick": t["tick"], "phase": t["phase"], "event": t["event"], "state": t["state"],
                  "state_text": text, "reference_policy": t["reference_policy"], "reference_reason": t["reference_reason"],
                  "lanes": results, "tick_wall_ms": round(wall, 1),
                  "totals": {f: dict(c) for f, c in counters.items()}}
            run["ticks"].append(ev)
            if on_event:
                on_event(ev)
            if pace:
                left = s.tick_seconds - (time.perf_counter() - t0)
                if left > 0:
                    time.sleep(left)
    if run["status"] == "running":
        run["status"] = "done"
    run["finished_at"] = now_iso()
    return run
