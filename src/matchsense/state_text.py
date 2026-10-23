"""Match state -> plain sentences for Decider and Nova.

A 2B decision model is weak at geometry from raw coordinates, so all geometry is computed here and
written as short facts. Coordinates are first normalised so that we always attack towards x=40
(a 180-degree rotation for "left": x' = 40 - x, y' = 20 - y), which keeps "left" and "right" the
same from our team's point of view. "attacking right" and "attacking left" give identical text.
"""

from __future__ import annotations

import math

from .schemas import OBJECTIVE_TEXT, PITCH_LENGTH, PITCH_WIDTH, MatchState, Player

NEAR_BALL_M = 6.0      # "near the ball"
MARKED_M = 4.0         # a player with an opponent within this distance is marked
NUMBERS = ["no", "one", "two", "three", "four", "five"]
GOAL_Y = PITCH_WIDTH / 2


def _num(n: int) -> str:
    return NUMBERS[n] if 0 <= n < len(NUMBERS) else str(n)


def normalise(state: MatchState) -> tuple[tuple[float, float], list[Player], list[Player]]:
    """Ball and players in the frame where we attack towards x=40."""
    if state.attack_direction == "right":
        return (state.ball.x, state.ball.y), list(state.us), list(state.them)

    def flip(p: Player) -> Player:
        return p.model_copy(update={"x": PITCH_LENGTH - p.x, "y": PITCH_WIDTH - p.y})

    return ((PITCH_LENGTH - state.ball.x, PITCH_WIDTH - state.ball.y),
            [flip(p) for p in state.us], [flip(p) for p in state.them])


def _d(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _side(y: float) -> str:
    # attacking towards +x, our left is +y
    return "left" if y > 13 else "right" if y < 7 else "central"


def _role_name(p: Player, team: list[Player]) -> str:
    if p.role == "MID":
        mids = sorted([q for q in team if q.role == "MID"], key=lambda q: -q.y)
        return "left midfielder" if p.id == mids[0].id else "right midfielder"
    return {"GK": "goalkeeper", "DEF": "defender", "FWD": "forward"}[p.role]


def derived(state: MatchState) -> dict:
    """Numbers the text is built from (also handy for the UI)."""
    ball, us, them = normalise(state)
    density = state.opponent_density_near_ball
    if density is None:
        density = sum(1 for p in them if _d(ball, (p.x, p.y)) <= NEAR_BALL_M)
    carrier_side = us if state.possession == "us" else them if state.possession == "them" else []
    carrier = min(carrier_side, key=lambda p: _d(ball, (p.x, p.y))) if carrier_side else None
    unmarked = [p for p in us if p.role != "GK" and (carrier is None or p.id != carrier.id)
                and min(_d((p.x, p.y), (o.x, o.y)) for o in them) > MARKED_M]
    open_opts = state.open_passing_options
    if open_opts is None:
        open_opts = len(unmarked)
    them_goal_side = sum(1 for p in them if p.role != "GK" and p.x > ball[0])
    us_goal_side = sum(1 for p in us if p.role != "GK" and p.x < ball[0])
    return {
        "ball": ball, "us": us, "them": them, "density": density, "carrier": carrier,
        "unmarked": unmarked, "open_options": open_opts,
        "dist_to_their_goal": _d(ball, (PITCH_LENGTH, GOAL_Y)),
        "dist_to_our_goal": _d(ball, (0.0, GOAL_Y)),
        "them_goal_side": them_goal_side, "us_goal_side": us_goal_side,
        "their_line": sum(p.x for p in them if p.role != "GK") / 4,
    }


def _clock(s: int) -> str:
    if s >= 60:
        m, r = divmod(s, 60)
        mins = f"{m} minute" + ("s" if m > 1 else "")
        return f"{mins} {r} seconds" if r else mins
    return f"{s} second" + ("" if s == 1 else "s")


def _length(s: int) -> str:
    if s % 60 == 0:
        return f"{s // 60}-minute"
    return f"{s}-second"


def state_to_text(state: MatchState) -> str:
    d = derived(state)
    s: list[str] = []
    us_, them_ = state.score_us, state.score_them
    if us_ > them_:
        score = f"We are winning {us_}-{them_}"
    elif us_ < them_:
        score = f"We are losing {us_}-{them_}"
    else:
        score = f"The score is level at {us_}-{them_}"
    s.append(f"{score} with {_clock(state.time_remaining_s)} left in a {_length(state.match_length_s)} match.")

    bx = d["ball"][0]
    if bx > PITCH_LENGTH / 2 + 3:
        where_us = f"in the opponent's half, {d['dist_to_their_goal']:.0f} m from their goal"
        where_them = f"in their own half, {d['dist_to_our_goal']:.0f} m from our goal"
    elif bx < PITCH_LENGTH / 2 - 3:
        where_us = f"in our own half, {d['dist_to_our_goal']:.0f} m from our goal"
        where_them = f"in our half, {d['dist_to_our_goal']:.0f} m from our goal"
    else:
        where_us = where_them = "around the halfway line"
    where = where_us

    if state.possession == "us":
        s.append(f"We have the ball {where}.")
        if state.possession_age_s is not None:
            s.append("We won the ball back just now." if state.possession_age_s <= 2
                     else f"We have had the ball for {_clock(state.possession_age_s)}.")
        n = d["them_goal_side"]
        s.append(f"{_num(n).capitalize()} opposing outfield player{'s are' if n != 1 else ' is'} between the ball and their goal.")
        if n <= 1 and bx < PITCH_LENGTH - 8:
            s.append("Their defence is out of position and there is open space in front of us.")
        elif n >= 3:
            s.append("Their defence is set and organised behind the ball.")
        if d["unmarked"]:
            names = []
            for p in d["unmarked"]:
                name = _role_name(p, d["us"])
                if p.role != "MID" and _side(p.y) != "central":
                    name += f" on the {_side(p.y)}"
                names.append("our " + name)
            s.append(f"Unmarked team-mates: {', '.join(names)}.")
        else:
            s.append("All our team-mates are marked.")
        s.append(f"We have {_num(d['open_options'])} open passing option{'s' if d['open_options'] != 1 else ''}.")
    elif state.possession == "them":
        s.append(f"The opponent has the ball {where_them}.")
        if state.possession_age_s is not None:
            s.append("They won the ball just now." if state.possession_age_s <= 2
                     else f"They have had the ball for {_clock(state.possession_age_s)}.")
        n = d["us_goal_side"]
        s.append(f"{_num(n).capitalize()} of our outfield players {'are' if n != 1 else 'is'} between the ball and our goal.")
        if n <= 1 and bx > 8:
            s.append("They are breaking fast into the space behind our players.")
        elif bx < PITCH_LENGTH / 2 - 3:
            s.append("They are attacking towards our goal.")
        elif bx > PITCH_LENGTH / 2 + 3:
            s.append("They are building up from deep in their own half.")
    else:
        s.append(f"The ball is loose {where}.")

    k = d["density"]
    s.append(f"{_num(k).capitalize()} opponent{'s are' if k != 1 else ' is'} within {NEAR_BALL_M:.0f} m of the ball.")
    if state.opponent_pressing:
        s.append("The opponent is pressing high and aggressively.")
    if state.opponent_low_block:
        s.append("The opponent is defending deep in a compact low block.")
    elif d["their_line"] < PITCH_LENGTH / 2 and state.possession != "them":
        s.append("Their outfield players are pushed up, leaving space behind them.")

    st = state.stamina
    fatigue = "fresh" if st >= 0.7 else "moderately tired" if st >= 0.4 else "very tired"
    s.append(f"Our players are {fatigue}.")
    s.append(f"Objective: {OBJECTIVE_TEXT[state.objective]}.")
    return " ".join(s)
