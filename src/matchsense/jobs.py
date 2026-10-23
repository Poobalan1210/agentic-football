"""Background jobs (replay runs, benchmarks) on threads, with an append-only event list for SSE."""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from typing import Any


class Job:
    def __init__(self, kind: str):
        self.id = f"{kind}_{uuid.uuid4().hex[:12]}"
        self.kind = kind
        self.status = "queued"   # queued | running | done | error | stopped
        self.progress = 0.0
        self.total = 0
        self.done_count = 0
        self.events: list[dict] = []
        self.result: Any = None
        self.error: str | None = None
        self.stop_flag = threading.Event()
        self._cv = threading.Condition()

    def emit(self, ev: dict) -> None:
        with self._cv:
            self.events.append(ev)
            self._cv.notify_all()

    def summary(self) -> dict:
        return {"job_id": self.id, "kind": self.kind, "status": self.status, "progress": round(self.progress, 3),
                "done": self.done_count, "total": self.total, "error": self.error}


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, fn: Callable[[Job], Any]) -> Job:
        job = Job(kind)
        with self._lock:
            self.jobs[job.id] = job

        def run() -> None:
            job.status = "running"
            try:
                job.result = fn(job)
                job.status = "stopped" if job.stop_flag.is_set() else "done"
                job.progress = 1.0 if job.status == "done" else job.progress
            except Exception as e:  # noqa: BLE001 - surfaced to the UI
                job.error = f"{type(e).__name__}: {e}"
                job.status = "error"
                traceback.print_exc()
            job.emit({"type": "end", "status": job.status, "error": job.error})

        threading.Thread(target=run, name=job.id, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)


JOBS = JobManager()
