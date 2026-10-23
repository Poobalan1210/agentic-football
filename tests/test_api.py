import json
import time

import pytest
from fastapi.testclient import TestClient

from matchsense.server import app

KEY = "dcd_test_SECRET_never_exposed"


@pytest.fixture
def c():
    return TestClient(app)


def test_health_never_exposes_key(c):
    r = c.get("/api/health")
    assert r.status_code == 200
    assert KEY not in r.text and r.json()["mode"] == "mock"
    assert r.json()["config"]["decider_api_key_set"] is True


def test_lab_runs_both_flows_on_same_state(c):
    r = c.post("/api/lab/run", json={"scenario_id": "regain_space", "flows": ["A", "B1"]})
    assert r.status_code == 200
    body = r.json()
    assert set(body["results"]) == {"A", "B1"} and body["state_text"]
    assert body["results"]["A"]["mode"] == "mock" and body["reference"]["policy"] == "COUNTERATTACK"


def test_lab_with_edited_state(c, state_dict):
    state_dict["score_us"] = 3
    r = c.post("/api/lab/run", json={"state": state_dict, "flows": ["B2"]})
    assert r.status_code == 200 and "winning 3-1" in r.json()["state_text"]


def test_errors_are_clear_json(c, state_dict):
    r = c.post("/api/lab/run", json={"flows": ["A"]})
    assert r.status_code == 400 and "error" in r.json()
    bad = dict(state_dict, stamina=7)
    r = c.post("/api/lab/run", json={"state": bad})
    assert r.status_code == 422 and r.json()["error"] == "invalid request"
    r = c.get("/api/replay/nope")
    assert r.status_code == 404 and "error" in r.json()
    r = c.post("/api/replay/run", json={"match_id": "missing"})
    assert r.status_code == 404


def _parse_sse(text):
    events = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
        if not lines:
            continue
        ev = dict(ln.split(": ", 1) for ln in lines)
        events.append((ev["event"], json.loads(ev["data"])))
    return events


def test_replay_streams_one_event_per_tick_and_matches_stored_run(c):
    r = c.post("/api/replay/run", json={"match_id": "m1_late_comeback", "baseline": "B1", "paced": False, "max_ticks": 8})
    run_id = r.json()["run_id"]
    with c.stream("GET", f"/api/replay/{run_id}/stream") as s:
        text = "".join(s.iter_text())
    evs = _parse_sse(text)
    ticks = [d for t, d in evs if t == "tick"]
    assert len(ticks) == 8 and evs[-1][0] == "end"
    for _ in range(50):
        got = c.get(f"/api/replay/{run_id}")
        if got.status_code == 200:
            break
        time.sleep(0.05)
    stored = got.json()
    assert stored["mode"] == "mock" and len(stored["ticks"]) == 8
    assert [t["lanes"] for t in stored["ticks"]] == [t["lanes"] for t in ticks]
    assert any(x["run_id"] == run_id for x in c.get("/api/replays").json()["items"])


def test_benchmark_and_exports(c):
    r = c.post("/api/benchmark/run", json={"suites": ["variants"], "max_items": 5})
    job = r.json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/benchmark/{job}").json()
        if j.get("result"):
            break
        time.sleep(0.05)
    s = j["result"]["summary"]
    assert s["mode"] == "mock" and set(s["flows"]) == {"A", "A2", "B1", "B2"}
    assert c.get(f"/api/export/{job}.csv").text.startswith("trial,")
    assert len(c.get(f"/api/export/{job}.json").json()["rows"]) == 20


def test_frontend_served(c):
    page = c.get("/").text
    assert "Which tactic should" in page and "Detailed replay" in page
    assert c.get("/static/watch.js").status_code == 200
    assert c.get("/static/app.js").status_code == 200


def test_prompts_endpoint_rebuilds_exact_inputs(c):
    text = "We have the ball. Objective: score now."
    r = c.post("/api/prompts", json={"state_text": text, "policy": "COUNTERATTACK"})
    assert r.status_code == 200
    b = r.json()
    assert b["decider"]["body"]["state"] == text
    assert b["decider"]["body"]["questions"]["policy"]["type"] == "choice"
    assert text in b["nova_pro_choose_and_plan"]["user"] and "COUNTERATTACK" in b["nova_pro_plan"]["user"]
    assert KEY not in r.text
    assert c.post("/api/prompts", json={"state_text": ""}).status_code == 422
