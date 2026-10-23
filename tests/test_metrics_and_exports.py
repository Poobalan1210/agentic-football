import csv
import io

import pytest

from matchsense.metrics import agreement, percentile, summarize, threshold_sweep, to_csv


def row(flow, item, ref, eff, *, raw=None, conf=None, llm=None, lat=100.0, mode="real", suite="variants",
        err=None, fallback=False):
    return {"trial": 1, "suite": suite, "item_id": item, "match_id": None, "tick": None, "flow": flow,
            "reference_policy": ref, "raw_decider_policy": raw, "decider_confidence": conf, "llm_policy": llm,
            "effective_policy": eff, "fallback": fallback, "fallback_reason": "low_confidence" if fallback else None,
            "decided_by": "decider", "decision_latency_ms": lat, "decider_latency_ms": lat if flow == "A" else None,
            "decider_server_latency_ms": None, "tick_latency_ms": lat, "deadline_missed": lat > 1000,
            "bedrock_calls": 0 if flow == "A" else 1, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001,
            "plan_called": False, "plan_valid": None, "error": err, "mode": mode}


ROWS = [
    row("A", "i1", "HIGH_PRESS", "HIGH_PRESS", raw="HIGH_PRESS", conf=0.9, lat=200),
    row("A", "i2", "LOW_BLOCK", "LOW_BLOCK", raw="COUNTERATTACK", conf=0.3, llm="LOW_BLOCK", fallback=True, lat=1500),
    row("A", "i3", None, "KEEP_POSSESSION", raw="KEEP_POSSESSION", conf=0.8),   # unlabelled
    row("A", "i4", "PROTECT_LEAD", None, err="decider_timeout"),                 # incomplete
    row("B1", "i1", "HIGH_PRESS", "LOW_BLOCK"),
    row("B1", "i2", "LOW_BLOCK", "LOW_BLOCK"),
    row("B1", "i3", None, "KEEP_POSSESSION"),
    row("B1", "i4", "PROTECT_LEAD", "PROTECT_LEAD"),
]


def test_accuracy_raw_vs_effective_and_incomplete():
    s = summarize(ROWS)
    a = s["flows"]["A"]
    assert a["accuracy"] == {"value": round(2 / 3, 4), "n": 3}        # incomplete counts as wrong
    assert a["raw_decider_accuracy"] == {"value": round(1 / 3, 4), "n": 3}
    assert a["incomplete"] == 1 and a["errors"] == 1
    assert a["fallback_rate"]["value"] == 0.25
    assert s["flows"]["B1"]["accuracy"]["value"] == round(2 / 3, 4)
    assert a["deadline_miss_rate"] == {"value": 0.25, "n": 4}
    assert a["small_n_warning"]


def test_agreement():
    ag = agreement(ROWS)["A-B1"]
    assert ag == {"value": round(2 / 3, 4), "n": 3}  # i4 has no A answer


def test_percentiles():
    xs = list(range(1, 101))
    assert percentile(xs, 50) == 50 and percentile(xs, 95) == 95 and percentile([], 50) is None


def test_threshold_sweep_uses_recorded_answers():
    sw = {t["threshold"]: t for t in threshold_sweep(ROWS)}
    assert sw[0.0]["accuracy"] == 0.5         # raw decider on i1 (right) and i2 (wrong)
    assert sw[0.9]["accuracy"] == 1.0         # i1 (conf .9) keeps the decider; i2 uses its recorded Nova fallback
    assert all(t["simulated"] for t in sw.values())


def test_mock_and_real_never_mixed():
    with pytest.raises(ValueError):
        summarize([ROWS[0], {**ROWS[1], "mode": "mock"}])


def test_csv_export_roundtrip():
    out = list(csv.DictReader(io.StringIO(to_csv(ROWS))))
    assert len(out) == len(ROWS) and out[0]["flow"] == "A" and out[1]["fallback_reason"] == "low_confidence"


def test_json_export_and_persistence_separate_modes():
    from matchsense import persistence

    persistence.save("real", "benchmarks", "b_real", {"rows": ROWS})
    persistence.save("mock", "benchmarks", "b_mock", {"rows": []})
    assert persistence.load("benchmarks", "b_real")[0] == "real"
    assert persistence.load("benchmarks", "b_mock")[0] == "mock"
    assert persistence.load("benchmarks", "../etc") is None
