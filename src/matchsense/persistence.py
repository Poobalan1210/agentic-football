"""Stored runs and benchmarks as JSON files. Real and mock results live in separate folders."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import settings

SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


def _dir(mode: str, kind: str) -> Path:
    if mode not in ("real", "mock"):
        raise ValueError("mode must be real or mock")
    p = settings().results_dir / mode / kind
    p.mkdir(parents=True, exist_ok=True)
    return p


def save(mode: str, kind: str, obj_id: str, data: Any) -> Path:
    if not SAFE_ID.match(obj_id):
        raise ValueError("bad id")
    p = _dir(mode, kind) / f"{obj_id}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=str))
    tmp.replace(p)
    return p


def load(kind: str, obj_id: str) -> tuple[str, Any] | None:
    """Look in real first, then mock. Returns (mode, data) or None."""
    if not SAFE_ID.match(obj_id):
        return None
    for mode in ("real", "mock"):
        p = _dir(mode, kind) / f"{obj_id}.json"
        if p.exists():
            return mode, json.loads(p.read_text())
    return None


def list_items(kind: str, fields: tuple[str, ...]) -> list[dict]:
    out = []
    for mode in ("real", "mock"):
        for p in _dir(mode, kind).glob("*.json"):
            try:
                d = json.loads(p.read_text())
            except ValueError:
                continue
            out.append({"mode": mode, **{f: d.get(f) for f in fields}})
    return sorted(out, key=lambda r: r.get("started_at") or "", reverse=True)
