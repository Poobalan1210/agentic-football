"""Stored runs and benchmarks as JSON files. Real and mock results live in separate folders.

Real runs committed to the repo under docs/results/ (benchmarks there, replays in docs/results/replays/)
are also read, read-only, so a fresh clone can play back the published real runs without any keys.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import ROOT, settings

PUBLISHED_DIR = ROOT / "docs" / "results"   # committed real runs (read-only)

SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


def _dir(mode: str, kind: str) -> Path:
    if mode not in ("real", "mock"):
        raise ValueError("mode must be real or mock")
    p = settings().results_dir / mode / kind
    p.mkdir(parents=True, exist_ok=True)
    return p


def _published(kind: str) -> Path:
    return PUBLISHED_DIR / "replays" if kind == "replays" else PUBLISHED_DIR


def _read_published(p: Path) -> Any | None:
    """Only committed files that say they are real runs count."""
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("mode") == "real" else None


def save(mode: str, kind: str, obj_id: str, data: Any) -> Path:
    if not SAFE_ID.match(obj_id):
        raise ValueError("bad id")
    p = _dir(mode, kind) / f"{obj_id}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=str))
    tmp.replace(p)
    return p


def load(kind: str, obj_id: str) -> tuple[str, Any] | None:
    """Look in real first, then the committed real runs, then mock. Returns (mode, data) or None."""
    if not SAFE_ID.match(obj_id):
        return None
    p = _dir("real", kind) / f"{obj_id}.json"
    if p.exists():
        return "real", json.loads(p.read_text())
    p = _published(kind) / f"{obj_id}.json"
    if p.exists() and (d := _read_published(p)) is not None:
        return "real", d
    p = _dir("mock", kind) / f"{obj_id}.json"
    if p.exists():
        return "mock", json.loads(p.read_text())
    return None


def list_items(kind: str, fields: tuple[str, ...]) -> list[dict]:
    out = []
    seen: set[str] = set()
    for mode in ("real", "mock"):
        for p in _dir(mode, kind).glob("*.json"):
            try:
                d = json.loads(p.read_text())
            except ValueError:
                continue
            seen.add(p.stem)
            out.append({"mode": mode, **{f: d.get(f) for f in fields},
                        "_t": d.get("started_at") or d.get("finished_at") or ""})
    for p in sorted(_published(kind).glob("*.json")):
        if p.stem in seen or (d := _read_published(p)) is None:
            continue
        out.append({"mode": "real", **{f: d.get(f) for f in fields},
                    "_t": d.get("started_at") or d.get("finished_at") or ""})
    out.sort(key=lambda r: r["_t"], reverse=True)   # newest first
    for r in out:
        r.pop("_t")
    return out
