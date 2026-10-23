"""Scenarios, variants, scripted matches and the reference-label rule.

Reference labels are evaluation references, not objective truth. They come from the explicit rule
in `reference_policy` below (written for this project, readable and arguable), and situations the
rule cannot call cleanly are left unlabelled and excluded from accuracy.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .config import DATA_DIR
from .schemas import MatchState
from .state_text import derived

LATE_S = 30


def reference_policy(state: MatchState) -> tuple[str | None, str]:
    d = derived(state)
    lead = state.score_us - state.score_them
    late = state.time_remaining_s <= LATE_S
    bx = d["ball"][0]
    tired = state.stamina < 0.4
    if state.possession == "loose":
        return None, "ambiguous: loose ball"
    if lead > 0 and late:
        if state.possession == "us":
            return "PROTECT_LEAD", "winning with the ball in the last 30 s: keep it safe and run the clock"
        if bx > 20:
            return None, "ambiguous: winning late, opponent has the ball far from our goal (PROTECT_LEAD or LOW_BLOCK)"
        return "LOW_BLOCK", "winning late and the opponent is attacking our half: defend deep"
    if state.possession == "them":
        if d["us_goal_side"] <= 1 and bx <= 30:
            return "LOW_BLOCK", "opponent counterattacking with at most one of our outfield players goal-side"
        if bx >= 23:
            if tired:
                return "LOW_BLOCK", "opponent has the ball in their half but we are too tired to press"
            if lead > 0:
                return None, "ambiguous: winning, opponent in their half (press or sit)"
            return "HIGH_PRESS", "opponent has the ball in their half and we need it back"
        return "LOW_BLOCK", "opponent has the ball in our half: protect the centre and our goal"
    # we have the ball
    if d["them_goal_side"] <= 1 and bx < 32 and not tired:
        return "COUNTERATTACK", "we have the ball with at most one opponent goal-side: attack the space now"
    if lead < 0 and state.time_remaining_s <= 15:
        return None, "ambiguous: losing in the last 15 s, no open space (no all-out-attack option)"
    return "KEEP_POSSESSION", "we have the ball, no quick opening: keep it and build"


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text())


@lru_cache(maxsize=1)
def scenarios() -> list[dict]:
    """Base scenarios and variants: [{id, title, kind: base|variant, base_id, state}]."""
    return _load("scenarios.json")


@lru_cache(maxsize=1)
def reference_labels() -> dict[str, dict]:
    return _load("reference_labels.json")


def scenario(item_id: str) -> dict:
    for s in scenarios():
        if s["id"] == item_id:
            return s
    raise KeyError(item_id)


@lru_cache(maxsize=1)
def matches() -> list[dict]:
    out = []
    for p in sorted((DATA_DIR / "matches").glob("*.json")):
        out.append(json.loads(p.read_text()))
    return out


def match(match_id: str) -> dict:
    for m in matches():
        if m["id"] == match_id:
            return m
    raise KeyError(match_id)


def state_of(item: dict) -> MatchState:
    return MatchState.model_validate(item["state"])
