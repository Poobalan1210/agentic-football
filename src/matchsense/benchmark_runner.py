"""Runs every selected flow on the same items and stores one row per (trial, item, flow).

Suites:
  variants  - labelled scenarios (base + variants), each item an independent decision (lanes reset)
  matches   - scripted matches, played tick by tick (lanes keep their active policy)

Each item is sent to all flows concurrently with identical state text. The hosted Decider queues
concurrent requests, so items themselves run one after another.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import settings
from .metrics import row_from_tick, summarize
from .replay import run_match
from .scenarios import reference_labels, scenarios, state_of
from .state_text import state_to_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_benchmark(rt, *, suites: list[str], flows: list[str], trials: int = 1, threshold: float | None = None,
                  match_ids: list[str] | None = None, max_items: int | None = None, job=None,
                  save_replays: bool = True, fallback_mode: str | None = None) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor

    from .scenarios import matches

    s = settings()
    thr = threshold if threshold is not None else s.confidence_threshold
    labels = reference_labels()
    items = [it for it in scenarios() if labels.get(it["id"])] if "variants" in suites else []
    if max_items:
        items = items[:max_items]
    mids = (match_ids or [m["id"] for m in matches()]) if "matches" in suites else []
    total = trials * (len(items) + sum(len(m["ticks"]) for m in matches() if m["id"] in mids))
    if job:
        job.total = total
    rows: list[dict] = []
    done = 0

    def tick_progress(_ev=None):
        nonlocal done
        done += 1
        if job:
            job.done_count, job.progress = done, done / max(total, 1)
            job.emit({"type": "progress", "done": done, "total": total})

    stopped = lambda: bool(job and job.stop_flag.is_set())  # noqa: E731
    for trial in range(1, trials + 1):
        if items:
            with ThreadPoolExecutor(max_workers=len(flows)) as pool:
                for it in items:
                    if stopped():
                        break
                    text = state_to_text(state_of(it))
                    lanes = {f: rt.lane(f, thr, fallback_mode) if f in ("A", "A2") else rt.lane(f) for f in flows}
                    futs = {f: pool.submit(lanes[f].step, 0, text) for f in flows}
                    for f, fut in futs.items():
                        r = fut.result().model_dump(mode="json")
                        rows.append(row_from_tick(r, trial=trial, suite="variants", item_id=it["id"], match_id=None,
                                                  tick=None, reference=labels[it["id"]]["policy"]))
                    tick_progress()
        for mid in mids:
            if stopped():
                break
            run = run_match(mid, flows, rt, run_id=f"bench_{mid}_{trial}", threshold=thr, on_event=tick_progress,
                            should_stop=stopped, fallback_mode=fallback_mode)
            if save_replays:
                from . import persistence

                run["baseline"] = "B2" if "B2" in flows else ("B1" if "B1" in flows else None)
                run["agent"] = "A" if "A" in flows else ("A2" if "A2" in flows else None)
                run["run_id"] = f"{job.id if job else 'cli'}_{mid}_{trial}"
                run["note"] = "recorded during a benchmark (unpaced: moments run back to back)"
                persistence.save(rt.mode, "replays", run["run_id"], run)
            for ev in run["ticks"]:
                for f, r in ev["lanes"].items():
                    rows.append(row_from_tick(r, trial=trial, suite="matches", item_id=f"{mid}#{ev['tick']}",
                                              match_id=mid, tick=ev["tick"], reference=ev["reference_policy"]))
    return {"mode": rt.mode, "finished_at": _now(),
            "config": {**s.public(), "confidence_threshold": thr, "fallback_mode": fallback_mode or s.fallback_mode, "suites": suites, "flows": flows, "trials": trials,
                       "match_ids": mids, "n_variant_items": len(items)},
            "rows": rows, "summary": summarize(rows, s.decision_deadline_s) if rows else None}
