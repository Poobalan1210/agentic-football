"""Metrics computed only from stored trial rows. Mock and real rows are never mixed."""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from typing import Any

FLOWS = ["A", "A2", "B1", "B2"]
OURS = ("A", "A2")
SMALL_N = 30

ROW_FIELDS = ["trial", "suite", "item_id", "match_id", "tick", "flow", "reference_policy", "raw_decider_policy",
              "decider_confidence", "llm_policy", "effective_policy", "fallback", "fallback_reason", "decided_by",
              "decision_latency_ms", "decider_latency_ms", "decider_server_latency_ms", "tick_latency_ms",
              "deadline_missed", "bedrock_calls", "input_tokens", "output_tokens", "cost_usd", "plan_called",
              "plan_valid", "error", "mode"]


def row_from_tick(r: dict, *, trial: int, suite: str, item_id: str, match_id: str | None, tick: int | None,
                  reference: str | None) -> dict:
    d = r["decision"]
    err = d.get("decider_error") if d.get("effective_policy") is None else None
    err = err or (d.get("llm_error") if d.get("effective_policy") is None else None) or r.get("plan_error")
    return {
        "trial": trial, "suite": suite, "item_id": item_id, "match_id": match_id, "tick": tick, "flow": r["flow"],
        "reference_policy": reference, "raw_decider_policy": d.get("raw_decider_policy"),
        "decider_confidence": d.get("decider_confidence"), "llm_policy": d.get("llm_policy"),
        "effective_policy": d.get("effective_policy"), "fallback": d.get("fallback"),
        "fallback_reason": d.get("fallback_reason"), "decided_by": d.get("decided_by"),
        "decision_latency_ms": d.get("decision_latency_ms"), "decider_latency_ms": d.get("decider_latency_ms"),
        "decider_server_latency_ms": d.get("decider_server_latency_ms"), "tick_latency_ms": r.get("tick_latency_ms"),
        "deadline_missed": r.get("deadline_missed"), "bedrock_calls": r.get("bedrock_calls"),
        "input_tokens": r.get("input_tokens"), "output_tokens": r.get("output_tokens"), "cost_usd": r.get("cost_usd"),
        "plan_called": r.get("plan_called"), "plan_valid": r.get("plan_valid"), "error": err, "mode": r.get("mode"),
    }


def percentile(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100)."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, math.ceil(q / 100 * len(xs)) - 1))
    return round(xs[k], 1)


def _rate(num: int, den: int) -> dict:
    return {"value": round(num / den, 4) if den else None, "n": den}


def summarize(rows: list[dict], deadline_s: float = 1.0) -> dict[str, Any]:
    modes = {r["mode"] for r in rows}
    if len(modes) > 1:
        raise ValueError("mock and real rows must not be mixed")
    out: dict[str, Any] = {"mode": next(iter(modes), None), "n_rows": len(rows), "flows": {}, "small_n_threshold": SMALL_N}
    by_flow: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_flow[r["flow"]].append(r)
    for f in FLOWS:
        rs = by_flow.get(f, [])
        if not rs:
            continue
        labelled = [r for r in rs if r["reference_policy"]]
        answered = [r for r in labelled if r["effective_policy"]]
        m: dict[str, Any] = {
            "n": len(rs),
            "accuracy": _rate(sum(r["effective_policy"] == r["reference_policy"] for r in answered), len(labelled)),
            "decision_latency_p50_ms": percentile([r["decision_latency_ms"] for r in rs], 50),
            "decision_latency_p95_ms": percentile([r["decision_latency_ms"] for r in rs], 95),
            "tick_latency_p50_ms": percentile([r["tick_latency_ms"] for r in rs], 50),
            "tick_latency_p95_ms": percentile([r["tick_latency_ms"] for r in rs], 95),
            "deadline_miss_rate": _rate(sum(bool(r["deadline_missed"]) for r in rs), len(rs)),
            "errors": sum(1 for r in rs if r["error"]),
            "incomplete": sum(1 for r in rs if not r["effective_policy"]),
            "bedrock_calls": sum(r["bedrock_calls"] or 0 for r in rs),
            "input_tokens": sum(r["input_tokens"] or 0 for r in rs),
            "output_tokens": sum(r["output_tokens"] or 0 for r in rs),
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in rs), 6),
        }
        m["bedrock_cost_per_1000_decisions_usd"] = round(m["cost_usd"] / len(rs) * 1000, 4)
        plans = [r for r in rs if r["plan_called"]]
        m["plan_calls"] = len(plans)
        m["plan_schema_valid_rate"] = _rate(sum(bool(r["plan_valid"]) for r in plans), len(plans))
        if f in OURS:
            dec = [r for r in labelled if r["raw_decider_policy"]]
            m["raw_decider_accuracy"] = _rate(sum(r["raw_decider_policy"] == r["reference_policy"] for r in dec), len(labelled))
            m["fallback_rate"] = _rate(sum(bool(r["fallback"]) for r in rs), len(rs))
            reasons: dict[str, int] = defaultdict(int)
            for r in rs:
                if r["fallback_reason"]:
                    reasons[r["fallback_reason"]] += 1
            m["fallback_reasons"] = dict(reasons)
            m["decider_latency_p50_ms"] = percentile([r["decider_latency_ms"] for r in rs], 50)
            m["decider_latency_p95_ms"] = percentile([r["decider_latency_ms"] for r in rs], 95)
            m["decider_server_latency_p50_ms"] = percentile([r["decider_server_latency_ms"] for r in rs], 50)
            m["decider_only_deadline_miss_rate"] = _rate(
                sum(1 for r in rs if r["decider_latency_ms"] is not None and r["decider_latency_ms"] > deadline_s * 1000),
                sum(1 for r in rs if r["decider_latency_ms"] is not None))
        # per scripted match
        per_match: dict[tuple, list[dict]] = defaultdict(list)
        for r in rs:
            if r["suite"] == "matches":
                per_match[(r["trial"], r["match_id"])].append(r)
        if per_match:
            k = len(per_match)
            m["per_match"] = {
                "n_matches": k,
                "bedrock_calls": round(sum(sum(x["bedrock_calls"] or 0 for x in v) for v in per_match.values()) / k, 2),
                "tokens": round(sum(sum((x["input_tokens"] or 0) + (x["output_tokens"] or 0) for x in v) for v in per_match.values()) / k, 1),
                "cost_usd": round(sum(sum(x["cost_usd"] or 0 for x in v) for v in per_match.values()) / k, 6),
                "plan_calls": round(sum(sum(bool(x["plan_called"]) for x in v) for v in per_match.values()) / k, 2),
            }
        m["small_n_warning"] = len(labelled) < SMALL_N
        out["flows"][f] = m
    out["agreement"] = agreement(rows)
    out["confidence_buckets"] = confidence_buckets(rows)
    out["threshold_sweep"] = threshold_sweep(rows)
    return out


def _key(r: dict) -> tuple:
    return (r["trial"], r["suite"], r["item_id"], r["tick"])


def agreement(rows: list[dict]) -> dict:
    idx: dict[tuple, dict[str, str]] = defaultdict(dict)
    for r in rows:
        if r["effective_policy"]:
            idx[_key(r)][r["flow"]] = r["effective_policy"]
    out = {}
    for a, b in (("A", "A2"), ("A", "B1"), ("A", "B2"), ("A2", "B2"), ("B1", "B2")):
        pairs = [(v[a], v[b]) for v in idx.values() if a in v and b in v]
        out[f"{a}-{b}"] = _rate(sum(x == y for x, y in pairs), len(pairs))
    return out


def confidence_buckets(rows: list[dict]) -> list[dict]:
    """Raw Decider accuracy by its own confidence (labelled rows of flow A, else A2)."""
    src = "A" if any(r["flow"] == "A" for r in rows) else "A2"
    rs = [r for r in rows if r["flow"] == src and r["reference_policy"] and r["raw_decider_policy"]
          and r["decider_confidence"] is not None]
    edges = [0.0, 0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 1.01]
    out = []
    for lo, hi in zip(edges, edges[1:]):
        b = [r for r in rs if lo <= r["decider_confidence"] < hi]
        out.append({"range": f"{lo:.1f}-{min(hi, 1):.1f}", **_rate(sum(r["raw_decider_policy"] == r["reference_policy"] for r in b), len(b))})
    return out


def threshold_sweep(rows: list[dict]) -> list[dict]:
    """SIMULATED from recorded outputs: "Decider + Nova Pro when unsure" accuracy if the threshold were t.
    Below t the answer is flow A2's recorded Nova fallback on the same item if there is one, else flow
    B2's recorded Nova Pro answer (same model). No new model calls."""
    a2 = {_key(r): r["llm_policy"] for r in rows if r["flow"] == "A2" and r["llm_policy"]}
    b2 = {_key(r): r["effective_policy"] for r in rows if r["flow"] == "B2"}
    src = "A" if any(r["flow"] == "A" for r in rows) else "A2"
    rs = [r for r in rows if r["flow"] == src and r["reference_policy"] and r["raw_decider_policy"]
          and r["decider_confidence"] is not None]
    out = []
    for t in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        correct = n = used = 0
        for r in rs:
            if r["decider_confidence"] >= t:
                ans = r["raw_decider_policy"]
                used += 1
            else:
                ans = a2.get(_key(r)) or (r["llm_policy"] if r["flow"] == "A2" else None) or b2.get(_key(r))
            if ans is None:
                continue
            n += 1
            correct += ans == r["reference_policy"]
        out.append({"threshold": t, "accuracy": round(correct / n, 4) if n else None, "n": n,
                    "decider_share": round(used / len(rs), 4) if rs else None, "simulated": True})
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ROW_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
