"""APP_MODE=mock: deterministic, clearly labelled fixtures. NOT A REAL MODEL RESULT.

The mock Decider reads keywords in the state text; its "confidence" is a made-up deterministic
number so the UI and the fallback logic can be exercised offline. Mock records are tagged
mode="mock" and never mixed into real benchmark summaries.
"""

from __future__ import annotations

import hashlib

from .bedrock_client import cost_usd
from .decider_client import DeciderResult
from .schemas import POLICY_NAMES, LLMUsage, PolicyChoice, RoleInstruction, TacticalPlan

MOCK_LABEL = "MOCK MODE — NOT A REAL MODEL RESULT"


def _h(text: str) -> float:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def heuristic_policy(text: str) -> str:
    t = text.lower()
    if "we are winning" in t and ("seconds left" in t and "minute" not in t.split("left")[0]):
        return "PROTECT_LEAD"
    if "the opponent has the ball" in t:
        if "breaking fast" in t or "attacking towards our goal" in t:
            return "LOW_BLOCK"
        return "HIGH_PRESS"
    if "we have the ball" in t:
        if "open space in front of us" in t:
            return "COUNTERATTACK"
        return "KEEP_POSSESSION"
    return "HIGH_PRESS"


class MockDecider:
    calls = 0

    def health(self) -> dict:
        return {"ok": True, "latency_ms": 0.0, "models": [{"id": "mock-decider", "ready": True}], "mock": True}

    def decide_choice(self, state_text: str, question: str, options: dict[str, str]) -> DeciderResult:
        self.calls += 1
        top = heuristic_policy(state_text)
        conf = round(0.45 + 0.5 * _h(state_text), 4)
        rest = (1 - (0.5 + conf / 2)) / (len(options) - 1)
        probs = {o: round(0.5 + conf / 2 if o == top else rest, 4) for o in options}
        return DeciderResult(choice=top, confidence=conf, probabilities=probs, model="mock-decider",
                             request_id="mock", server_latency_ms=None, client_latency_ms=round(40 + 30 * _h(question + state_text), 1),
                             input_tokens=None)


def _usage(model_id: str, tin: int, tout: int, ms: float) -> LLMUsage:
    return LLMUsage(model_id=f"mock:{model_id}", input_tokens=tin, output_tokens=tout, latency_ms=ms,
                    cost_usd=cost_usd(model_id, tin, tout))


def mock_plan(policy: str) -> TacticalPlan:
    return TacticalPlan(
        policy=policy, tactical_objective=f"[mock] objective for {policy}", why_this_policy="[mock] fixture text",
        goalkeeper_instruction="[mock] goalkeeper instruction",
        outfield_instructions=[RoleInstruction(role=r, instruction=f"[mock] {r} instruction")
                               for r in ("DEF", "MID_LEFT", "MID_RIGHT", "FWD")],
        immediate_actions=["[mock] action"], passing_movement="[mock] passing", main_risk="[mock] risk",
        mitigation="[mock] mitigation", reassess_signals=["[mock] signal"], alternative_if_changes="[mock] alternative")


class MockTactics:
    fast_model_id = "us.amazon.nova-micro-v1:0"
    planner_model_id = "us.amazon.nova-pro-v1:0"

    def choose_policy(self, state_text: str):
        p = heuristic_policy(state_text)
        if _h("b1" + state_text) < 0.15:  # disagree sometimes, deterministically
            p = POLICY_NAMES[(POLICY_NAMES.index(p) + 1) % 5]
        return PolicyChoice(policy=p, reason="[mock] fixture"), _usage(self.fast_model_id, 420, 30, 600.0), 1

    def choose_policy_strong(self, state_text: str):
        return (PolicyChoice(policy=heuristic_policy(state_text), reason="[mock] fixture"),
                _usage(self.planner_model_id, 420, 30, 1500.0), 1)

    def write_plan(self, state_text: str, policy: str):
        return mock_plan(policy), _usage(self.planner_model_id, 650, 380, 3200.0), 1

    def choose_and_plan(self, state_text: str):
        return mock_plan(heuristic_policy(state_text)), _usage(self.planner_model_id, 780, 420, 3600.0), 1
