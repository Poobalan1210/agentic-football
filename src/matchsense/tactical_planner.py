"""Amazon Nova roles: fast policy chooser (Nova Micro) and tactical planner (Nova Pro).

Plans are model-generated recommendations, not proven strategy.
"""

from __future__ import annotations

from .bedrock_client import NovaClient
from .config import settings
from .policy_decision import FAST_SYSTEM, POLICY_OPTIONS, QUESTION, fast_prompt
from .schemas import LLMUsage, PolicyAndPlan, PolicyChoice, TacticalPlan

PLANNER_SYSTEM = (
    "You are the coach of a five-a-side football team (goalkeeper, one defender, two midfielders, one "
    "forward). Write a short, concrete tactical plan that follows the given policy exactly. Be specific "
    "to the situation, one sentence per field. outfield_instructions must have exactly four entries, "
    "for roles DEF, MID_LEFT, MID_RIGHT and FWD.")


def plan_prompt(state_text: str, policy: str) -> str:
    return (f"MATCH STATE:\n{state_text}\n\nPOLICY TO FOLLOW: {policy} ({POLICY_OPTIONS[policy]})\n\n"
            f"Write the tactical plan. Its `policy` field must be {policy}.")


def choose_and_plan_prompt(state_text: str) -> str:
    opts = "\n".join(f"- {k}: {v}" for k, v in POLICY_OPTIONS.items())
    return (f"MATCH STATE:\n{state_text}\n\nFirst decide: {QUESTION}\nOPTIONS:\n{opts}\n\n"
            f"Then write the tactical plan for the policy you chose (put it in plan.policy).")


class NovaTactics:
    def __init__(self, client: NovaClient | None = None, fast_model_id: str | None = None,
                 planner_model_id: str | None = None):
        s = settings()
        self.client = client or NovaClient()
        self.fast_model_id = fast_model_id or s.nova_fast_model_id
        self.planner_model_id = planner_model_id or s.nova_planner_model_id

    def choose_policy(self, state_text: str) -> tuple[PolicyChoice, LLMUsage, int]:
        return self.client.structured(self.fast_model_id, FAST_SYSTEM, fast_prompt(state_text), PolicyChoice, 400)

    def choose_policy_strong(self, state_text: str) -> tuple[PolicyChoice, LLMUsage, int]:
        """The same question to the planner model (fallback mode nova_pro)."""
        return self.client.structured(self.planner_model_id, FAST_SYSTEM, fast_prompt(state_text), PolicyChoice, 400)

    def write_plan(self, state_text: str, policy: str) -> tuple[TacticalPlan, LLMUsage, int]:
        return self.client.structured(self.planner_model_id, PLANNER_SYSTEM, plan_prompt(state_text, policy),
                                      TacticalPlan, 900)

    def choose_and_plan(self, state_text: str) -> tuple[TacticalPlan, LLMUsage, int]:
        out, usage, calls = self.client.structured(self.planner_model_id, PLANNER_SYSTEM,
                                                   choose_and_plan_prompt(state_text), PolicyAndPlan, 1000)
        return out.plan, usage, calls
