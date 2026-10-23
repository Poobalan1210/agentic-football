"""Builds data/scenarios.json, data/reference_labels.json and data/matches/*.json.

Positions come from hand-written phase templates in the frame where we attack right (towards x=40),
interpolated over the phase and mirrored when we attack left. Run: `python scripts/build_data.py`.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .scenarios import reference_policy
from .schemas import PITCH_LENGTH, PITCH_WIDTH, MatchState

IDS = ["gk", "def", "ml", "mr", "fwd"]
ROLES = {"gk": "GK", "def": "DEF", "ml": "MID", "mr": "MID", "fwd": "FWD"}

# template: possession, objective, flags, (us start, us end), (them start, them end), (ball start, ball end)
TEMPLATES: dict[str, dict] = {
    "build_own_half": dict(
        possession="us", objective="build_attack",
        us=([(2, 10), (8, 10), (14, 15), (14, 5), (22, 10)], [(3, 10), (12, 10), (20, 16), (19, 4), (28, 11)]),
        them=([(38, 10), (30, 10), (24, 13), (24, 7), (18, 10)], [(38, 10), (32, 10), (27, 13), (27, 7), (22, 9)]),
        ball=((8.5, 10), (20, 15.5))),
    "attack": dict(
        possession="us", objective="build_attack",
        us=([(4, 10), (16, 10), (24, 15), (24, 5), (30, 10)], [(5, 10), (20, 10), (30, 15), (29, 4), (34, 9)]),
        them=([(38, 10), (33, 10), (30, 13), (29, 7), (22, 10)], [(38.5, 10), (35.5, 9), (33, 13), (32, 6), (26, 11)]),
        ball=((24, 14.5), (29, 4.5))),
    "counter_us": dict(
        possession="us", objective="exploit_space",
        us=([(3, 10), (13, 10), (15, 15), (12, 4), (22, 8)], [(5, 10), (18, 10), (30, 15), (26, 4), (34, 8)]),
        them=([(36, 10), (24, 11), (12, 14), (13, 6), (10, 10)], [(37, 10), (31, 10), (22, 14), (23, 6), (18, 10)]),
        ball=((14, 10), (31, 14.5))),
    "press_them": dict(
        possession="them", objective="win_ball_back",
        us=([(4, 10), (16, 10), (24, 14), (24, 6), (29, 10)], [(6, 10), (18, 10), (25, 13), (23, 7), (29, 12)]),
        them=([(38, 10), (32, 10), (28, 15), (28, 5), (20, 10)], [(38, 10), (30, 10), (27, 14), (26, 5), (19, 9)]),
        ball=((31.5, 10), (27, 14))),
    "they_attack": dict(
        possession="them", objective="win_ball_back",
        us=([(2, 10), (9, 10), (15, 13), (13, 7), (24, 10)], [(1.5, 10), (6, 9), (9, 13), (8, 6), (18, 10)]),
        them=([(37, 10), (26, 10), (20, 14), (18, 6), (12, 10)], [(36, 10), (22, 10), (14, 14), (12, 6), (8, 9)]),
        ball=((20, 13.5), (11, 8))),
    "counter_them": dict(
        possession="them", objective="stop_counter",
        us=([(3, 10), (20, 10), (30, 15), (29, 5), (33, 10)], [(2, 10), (7, 11), (20, 15), (18, 5), (26, 10)]),
        them=([(38, 10), (28, 10), (26, 14), (24, 6), (18, 10)], [(37, 10), (24, 10), (14, 14), (13, 6), (8, 10)]),
        ball=((27.5, 10), (9, 10))),
    "protect": dict(
        possession="us", objective="build_attack",
        us=([(3, 10), (12, 10), (18, 15), (18, 5), (25, 10)], [(3, 10), (13, 9), (21, 16), (19, 4), (26, 12)]),
        them=([(37, 10), (28, 10), (20, 13), (21, 7), (15, 10)], [(37, 10), (29, 10), (22, 13), (22, 7), (17, 10)]),
        ball=((12.5, 10), (20.5, 15.5))),
    "low_block_them": dict(
        possession="us", objective="break_low_block", flags={"opponent_low_block": True},
        us=([(5, 10), (18, 10), (25, 16), (25, 4), (30, 10)], [(5, 10), (19, 10), (27, 15), (26, 5), (31, 9)]),
        them=([(39, 10), (35, 10), (32, 13), (32, 7), (29, 10)], [(39, 10), (35, 10), (33, 12), (32, 6), (30, 9)]),
        ball=((24.5, 15.5), (25.5, 5.5))),
    "pressed": dict(
        possession="us", objective="survive_pressure", flags={"opponent_pressing": True},
        us=([(2, 10), (6, 10), (11, 16), (11, 4), (19, 10)], [(2, 10), (8, 9), (14, 16), (13, 4), (21, 11)]),
        them=([(37, 10), (24, 10), (10, 13), (9, 7), (7, 10)], [(37, 10), (25, 10), (12, 14), (11, 6), (9, 9)]),
        ball=((6.5, 10), (13.5, 4.5))),
}


def _lerp(a: tuple[float, float], b: tuple[float, float], p: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p


def _clamp(x: float, y: float) -> tuple[float, float]:
    return round(min(max(x, 0.5), PITCH_LENGTH - 0.5), 2), round(min(max(y, 0.5), PITCH_WIDTH - 0.5), 2)


def build_state(template: str, p: float, *, score: tuple[int, int], t_left: int, length: int = 120,
                stamina: float = 0.8, direction: str = "right", jitter_seed: int | None = None,
                objective: str | None = None, possession_age_s: int | None = None, **overrides) -> dict:
    tpl = TEMPLATES[template]
    if possession_age_s is None:  # scenarios: a counter starts right after a turnover
        possession_age_s = 2 if template in ("counter_us", "counter_them") else 10
    rng = random.Random(jitter_seed) if jitter_seed is not None else None

    def pos(a, b, i):
        x, y = _lerp(a, b, p)
        if rng and i is not None:
            x += rng.uniform(-0.5, 0.5)
            y += rng.uniform(-0.5, 0.5)
        x, y = _clamp(x, y)
        if direction == "left":
            x, y = round(PITCH_LENGTH - x, 2), round(PITCH_WIDTH - y, 2)
        return x, y

    def side(key):
        start, end = tpl[key]
        return [dict(zip(("x", "y"), pos(start[i], end[i], i)), id=f"{key}_{IDS[i]}", role=ROLES[IDS[i]])
                for i in range(5)]

    bx, by = pos(tpl["ball"][0], tpl["ball"][1], None)
    lead = score[0] - score[1]
    obj = objective or tpl["objective"]
    if objective is None:
        if lead > 0 and t_left <= 30 and tpl["possession"] == "us":
            obj = "keep_lead"
        elif lead < 0 and t_left <= 30 and tpl["possession"] == "us":
            obj = "score_now"
    st = dict(score_us=score[0], score_them=score[1], match_length_s=length, time_remaining_s=t_left,
              possession=tpl["possession"], possession_age_s=possession_age_s,
              ball={"x": bx, "y": by}, attack_direction=direction,
              us=side("us"), them=side("them"), stamina=round(stamina, 2), objective=obj,
              **tpl.get("flags", {}))
    st.update(overrides)
    MatchState.model_validate(st)
    return st


# ---- scenarios --------------------------------------------------------------------------------

BASE = [
    ("losing_late", "Losing late, opponent has the ball in their half", "press_them", 0.3,
     dict(score=(0, 1), t_left=20, stamina=0.6)),
    ("protect_lead", "Protecting a narrow lead near full time", "protect", 0.5, dict(score=(2, 1), t_left=25, stamina=0.5)),
    ("regain_space", "Ball regained with open space ahead", "counter_us", 0.2, dict(score=(1, 1), t_left=70, stamina=0.7)),
    ("hold_near_goal", "Holding the ball near their goal", "attack", 0.8, dict(score=(0, 0), t_left=80, stamina=0.8)),
    ("aggressive_press", "Facing an aggressive press", "pressed", 0.4, dict(score=(0, 0), t_left=90, stamina=0.8)),
    ("defend_counter", "Defending a dangerous counterattack", "counter_them", 0.5, dict(score=(0, 0), t_left=60, stamina=0.7)),
    ("tired_few_options", "Tired players with few passing options", "protect", 0.6,
     dict(score=(1, 1), t_left=50, stamina=0.25, open_passing_options=0, opponent_density_near_ball=3)),
    ("facing_low_block", "Facing a compact low block", "low_block_them", 0.5, dict(score=(0, 1), t_left=90, stamina=0.8)),
]

SCORES = [(0, 0), (1, 0), (0, 1), (2, 1), (1, 2), (2, 2)]
TIMES = [110, 75, 45, 28, 12]
STAMINAS = [0.9, 0.6, 0.3]


def build_scenarios(variants_per_base: int = 6, seed: int = 7) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    items, labels = [], {}

    def add(item_id, title, kind, base_id, template, p, kw):
        st = build_state(template, p, **kw)
        pol, reason = reference_policy(MatchState.model_validate(st))
        items.append({"id": item_id, "title": title, "kind": kind, "base_id": base_id, "template": template, "state": st})
        labels[item_id] = {"policy": pol, "reason": reason}

    for bid, title, tpl, p, kw in BASE:
        add(bid, title, "base", bid, tpl, p, kw)
    for bid, title, tpl, p, kw in BASE:
        for k in range(variants_per_base):
            v = dict(kw)
            changes = []
            if k % 2 == 0:
                v["score"] = rng.choice(SCORES)
                changes.append(f"score {v['score'][0]}-{v['score'][1]}")
            if k % 3 != 2:
                v["t_left"] = rng.choice(TIMES)
                changes.append(f"{v['t_left']}s left")
            if k in (1, 4, 5):
                v["stamina"] = rng.choice(STAMINAS)
                changes.append(f"stamina {v['stamina']}")
            pp = min(max(p + rng.choice([-0.3, -0.15, 0.15, 0.3]), 0.0), 1.0) if k >= 3 else p
            if k == 2 and "opponent_density_near_ball" not in v:
                v["opponent_density_near_ball"] = rng.choice([0, 1, 3, 4])
                changes.append(f"density {v['opponent_density_near_ball']}")
            v["direction"] = "left" if k % 2 == 1 else "right"
            v["jitter_seed"] = rng.randint(0, 10_000)
            changes.append(f"attacking {v['direction']}")
            add(f"{bid}_v{k + 1}", f"{title} — {', '.join(changes)}", "variant", bid, tpl, pp, v)
    return items, labels


# ---- scripted matches -------------------------------------------------------------------------

MATCHES = [
    {"id": "m1_late_comeback", "title": "Late comeback: 0-1 down, win 2-1", "stamina": (1.0, 0.45),
     "phases": [("build_own_half", 5, None), ("attack", 6, None), ("counter_them", 4, "them"),
                ("build_own_half", 4, None), ("pressed", 5, None), ("low_block_them", 4, None),
                ("attack", 5, None), ("press_them", 5, None), ("counter_us", 4, "us"),
                ("press_them", 4, None), ("counter_us", 4, "us"), ("protect", 6, None), ("they_attack", 4, None)]},
    {"id": "m2_protect_the_lead", "title": "Early goal, then protect the lead", "stamina": (1.0, 0.4),
     "phases": [("build_own_half", 4, None), ("counter_us", 4, "us"), ("they_attack", 5, None),
                ("pressed", 5, None), ("protect", 6, None), ("counter_them", 4, None), ("they_attack", 4, None),
                ("press_them", 5, None), ("attack", 5, None), ("protect", 5, None), ("they_attack", 4, None),
                ("protect", 5, None), ("counter_them", 4, None)]},
    {"id": "m3_press_and_block", "title": "Breaking a low block, trading goals", "stamina": (0.95, 0.3),
     "phases": [("low_block_them", 6, None), ("attack", 4, None), ("counter_them", 4, "them"),
                ("press_them", 5, None), ("counter_us", 4, "us"), ("pressed", 5, None), ("build_own_half", 4, None),
                ("low_block_them", 6, None), ("they_attack", 5, None), ("press_them", 5, None),
                ("low_block_them", 5, None), ("counter_them", 4, None), ("press_them", 3, None)]},
]


def build_match(spec: dict, length: int = 120, tick_s: int = 2) -> dict:
    total = sum(n for _, n, _ in spec["phases"])
    assert total == length // tick_s, (spec["id"], total)
    ticks, score, tick = [], [0, 0], 0
    s0, s1 = spec["stamina"]
    last_poss, age = None, 0
    for pi, (tpl, n, goal) in enumerate(spec["phases"]):
        for k in range(n):
            p = k / max(n - 1, 1)
            t_left = length - tick * tick_s
            stamina = s0 + (s1 - s0) * tick / (total - 1)
            direction = "right" if tick < total // 2 else "left"  # teams switch ends at half time
            poss = TEMPLATES[tpl]["possession"]
            age = age + tick_s if poss == last_poss else 0
            last_poss = poss
            st = build_state(tpl, p, score=tuple(score), t_left=t_left, length=length, stamina=stamina,
                             direction=direction, jitter_seed=tick * 31 + pi, possession_age_s=age)
            pol, reason = reference_policy(MatchState.model_validate(st))
            event = f"goal_{goal}" if goal and k == n - 1 else None
            ticks.append({"tick": tick, "phase": tpl, "event": event, "state": st,
                          "reference_policy": pol, "reference_reason": reason})
            tick += 1
        if goal:
            score[0 if goal == "us" else 1] += 1
    return {"id": spec["id"], "title": spec["title"], "length_s": length, "tick_s": tick_s,
            "final_score": score, "ticks": ticks}


def write_all(data_dir: Path) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "matches").mkdir(exist_ok=True)
    items, labels = build_scenarios()
    (data_dir / "scenarios.json").write_text(json.dumps(items, indent=1))
    (data_dir / "reference_labels.json").write_text(json.dumps(labels, indent=1))
    summary = {"scenarios": len(items), "labelled": sum(1 for v in labels.values() if v["policy"])}
    for spec in MATCHES:
        m = build_match(spec)
        (data_dir / "matches" / f"{spec['id']}.json").write_text(json.dumps(m, indent=1))
        summary[spec["id"]] = {"ticks": len(m["ticks"]), "labelled": sum(1 for t in m["ticks"] if t["reference_policy"]),
                               "final": m["final_score"]}
    return summary
