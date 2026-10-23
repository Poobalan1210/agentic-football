"""Typed match state, decisions, plans and per-tick records (Pydantic).

Pitch frame: five-a-side pitch, 40 m long (x) by 20 m wide (y). `attack_direction` says which goal
we attack: "right" means the goal at x=40, "left" the goal at x=0. `state_text` normalises this so
both directions read the same.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PITCH_LENGTH = 40.0
PITCH_WIDTH = 20.0


class Policy(str, Enum):
    HIGH_PRESS = "HIGH_PRESS"
    COUNTERATTACK = "COUNTERATTACK"
    KEEP_POSSESSION = "KEEP_POSSESSION"
    PROTECT_LEAD = "PROTECT_LEAD"
    LOW_BLOCK = "LOW_BLOCK"


POLICY_NAMES = [p.value for p in Policy]

Role = Literal["GK", "DEF", "MID", "FWD"]
REQUIRED_ROLES = sorted(["GK", "DEF", "MID", "MID", "FWD"])

Objective = Literal[
    "score_now",          # we need a goal, now
    "build_attack",       # create a good chance without rushing
    "keep_lead",          # see the game out
    "win_ball_back",      # regain possession
    "exploit_space",      # attack open space quickly
    "survive_pressure",   # get out of an opponent press
    "stop_counter",       # stop a dangerous opponent counterattack
    "break_low_block",    # unlock a deep, compact defence
]

OBJECTIVE_TEXT = {
    "score_now": "score now",
    "build_attack": "create a good scoring chance",
    "keep_lead": "keep the lead until full time",
    "win_ball_back": "win the ball back",
    "exploit_space": "exploit the open space quickly",
    "survive_pressure": "get out of the opponent's press without losing the ball",
    "stop_counter": "stop the opponent's fast break towards our goal",
    "break_low_block": "break down a deep, compact defence",
}


class Point(BaseModel):
    x: float = Field(ge=0, le=PITCH_LENGTH)
    y: float = Field(ge=0, le=PITCH_WIDTH)


class Player(BaseModel):
    id: str
    role: Role
    x: float = Field(ge=0, le=PITCH_LENGTH)
    y: float = Field(ge=0, le=PITCH_WIDTH)


class MatchState(BaseModel):
    """One decision point. Derived numbers (density, open options) may be given or computed."""

    score_us: int = Field(ge=0, le=30)
    score_them: int = Field(ge=0, le=30)
    match_length_s: int = Field(gt=0, le=3600)
    time_remaining_s: int = Field(ge=0)
    possession: Literal["us", "them", "loose"]
    possession_age_s: int | None = Field(default=None, ge=0, description="seconds since the current possession began")
    ball: Point
    attack_direction: Literal["right", "left"]
    us: list[Player]
    them: list[Player]
    opponent_density_near_ball: int | None = Field(default=None, ge=0, le=5)
    open_passing_options: int | None = Field(default=None, ge=0, le=4)
    stamina: float = Field(ge=0, le=1, description="team stamina, 0 exhausted .. 1 fresh")
    objective: Objective
    opponent_pressing: bool = False   # the opponent is pressing high right now
    opponent_low_block: bool = False  # the opponent sits deep and compact

    @field_validator("us", "them")
    @classmethod
    def _five_a_side(cls, v: list[Player]) -> list[Player]:
        if len(v) != 5:
            raise ValueError("each side has exactly 5 players")
        if sorted(p.role for p in v) != REQUIRED_ROLES:
            raise ValueError("roles must be GK, DEF, MID, MID, FWD")
        return v

    @model_validator(mode="after")
    def _time(self) -> "MatchState":
        if self.time_remaining_s > self.match_length_s:
            raise ValueError("time_remaining_s cannot exceed match_length_s")
        return self


class DeciderResult(BaseModel):
    """Exactly what the hosted Decider returned for one choice question (nothing computed)."""

    choice: str
    confidence: float | None  # the response's own `confidence` field; None if absent
    probabilities: dict[str, float]
    model: str | None = None
    request_id: str | None = None
    server_latency_ms: float | None = None
    client_latency_ms: float
    input_tokens: int | None = None


class LLMUsage(BaseModel):
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class PolicyChoice(BaseModel):
    """Structured output for an LLM picking the policy (Nova Micro baseline and fallback)."""

    policy: Policy
    reason: str = Field(description="one short sentence")


class RoleInstruction(BaseModel):
    role: Literal["DEF", "MID_LEFT", "MID_RIGHT", "FWD"]
    instruction: str


class TacticalPlan(BaseModel):
    """The Nova planner's output. Model-generated recommendation, not proven strategy."""

    policy: Policy
    tactical_objective: str
    why_this_policy: str
    goalkeeper_instruction: str
    outfield_instructions: list[RoleInstruction] = Field(min_length=4, max_length=4)
    immediate_actions: list[str] = Field(min_length=1, max_length=4)
    passing_movement: str
    main_risk: str
    mitigation: str
    reassess_signals: list[str] = Field(min_length=1, max_length=4)
    alternative_if_changes: str


class PolicyAndPlan(BaseModel):
    """Flow B2: one planner call picks the policy and writes the plan."""

    plan: TacticalPlan


class PolicyDecision(BaseModel):
    """Everything about one policy decision, raw and effective, kept apart."""

    raw_decider_policy: str | None = None
    decider_confidence: float | None = None
    decider_probabilities: dict[str, float] | None = None
    decider_latency_ms: float | None = None
    decider_server_latency_ms: float | None = None
    decider_input_tokens: int | None = None
    decider_error: str | None = None
    llm_policy: str | None = None          # policy chosen by Nova (baseline or fallback)
    llm_reason: str | None = None
    llm_usage: LLMUsage | None = None
    llm_error: str | None = None
    effective_policy: str | None = None
    fallback: bool = False
    fallback_reason: str | None = None     # low_confidence | no_confidence_field | decider_error | decider_timeout
    fallback_mode: str | None = None       # nova_micro | nova_pro | hold | none
    decided_by: Literal["decider", "nova_fast", "nova_strong", "nova_planner", "hold", "none"] = "none"
    decision_latency_ms: float = 0.0       # total time to an effective policy (incl. fallback)


class TickResult(BaseModel):
    """One lane's result for one tick."""

    flow: Literal["A", "A2", "B1", "B2"]
    tick: int
    decision: PolicyDecision
    active_policy_before: str | None
    policy_changed: bool
    plan_called: bool
    plan: TacticalPlan | None = None
    plan_usage: LLMUsage | None = None
    plan_error: str | None = None
    plan_valid: bool | None = None
    deadline_missed: bool
    tick_latency_ms: float
    bedrock_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    mode: Literal["real", "mock"]
