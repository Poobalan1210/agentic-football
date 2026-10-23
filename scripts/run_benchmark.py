"""Run the benchmark from the command line and store it like the UI does.

    python scripts/run_benchmark.py --suites variants matches --trials 1
Results: results/<mode>/benchmarks/<id>.json (+ .csv beside it); match runs also stored as replays.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matchsense import persistence  # noqa: E402
from matchsense.benchmark_runner import run_benchmark  # noqa: E402
from matchsense.metrics import to_csv  # noqa: E402
from matchsense.runtime import runtime  # noqa: E402


class CLIJob:
    def __init__(self, job_id):
        import threading

        self.id, self.total, self.done_count, self.progress = job_id, 0, 0, 0.0
        self.stop_flag = threading.Event()
        self.t0 = time.time()

    def emit(self, ev):
        if ev.get("type") == "progress" and (ev["done"] % 10 == 0 or ev["done"] == ev["total"]):
            print(f"  {ev['done']}/{ev['total']}  ({time.time() - self.t0:.0f}s)", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", nargs="+", default=["variants", "matches"], choices=["variants", "matches"])
    ap.add_argument("--flows", nargs="+", default=["A", "A2", "B1", "B2"], choices=["A", "A2", "B1", "B2"])
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--max-items", type=int, default=None)
    ap.add_argument("--fallback", choices=["nova_micro", "nova_pro", "hold", "none"], default=None)
    ap.add_argument("--matches", nargs="*", default=None)
    a = ap.parse_args()
    rt = runtime()
    job = CLIJob(f"bench_cli_{time.strftime('%Y%m%d_%H%M%S')}")
    print(f"mode={rt.mode} decider={rt.decider!r} fallback={a.fallback} threshold={a.threshold} suites={a.suites} flows={a.flows} trials={a.trials} id={job.id}", flush=True)
    res = run_benchmark(rt, suites=a.suites, flows=a.flows, trials=a.trials, threshold=a.threshold,
                        match_ids=a.matches, max_items=a.max_items, job=job, fallback_mode=a.fallback)
    res["job_id"] = job.id
    res["started_at"] = res["finished_at"]
    p = persistence.save(rt.mode, "benchmarks", job.id, res)
    p.with_suffix(".csv").write_text(to_csv(res["rows"]))
    print("saved", p)
    print(json.dumps(res["summary"], indent=1))
