"""Shared bookkeeping for the three flows. Each flow's decision logic lives in its own module."""

from __future__ import annotations

from typing import Literal

from .bedrock_client import LLMError
from .config import settings
from .schemas import LLMUsage, PolicyDecision, TacticalPlan, TickResult


class Lane:
    """One agent playing through a match: holds the active policy and the current plan."""

    flow: Literal["A", "A2", "B1", "B2"]

    def __init__(self, tactics, mode: Literal["real", "mock"], deadline_s: float | None = None):
        self.tactics = tactics
        self.mode = mode
        self.deadline_s = deadline_s if deadline_s is not None else settings().decision_deadline_s
        self.active_policy: str | None = None
        self.plan: TacticalPlan | None = None

    def reset(self) -> None:
        self.active_policy, self.plan = None, None

    def step(self, tick: int, state_text: str) -> TickResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def needs_plan(self, policy: str | None) -> bool:
        """Write a plan when there is none for this tactic: the tactic changed, or the last plan call
        failed or came back for a different tactic (so a failed plan is retried on the next moment)."""
        return policy is not None and (self.plan is None or self.plan.policy.value != policy)

    # -------------------------------------------------------------------------------------------

    def _write_plan(self, state_text: str, policy: str) -> tuple[TacticalPlan | None, LLMUsage | None, str | None, int]:
        try:
            plan, usage, calls = self.tactics.write_plan(state_text, policy)
            return plan, usage, None, calls
        except LLMError as e:
            return None, e.usage, str(e), e.calls

    def _result(self, tick: int, d: PolicyDecision, before: str | None, plan_called: bool,
                plan: TacticalPlan | None, plan_usage: LLMUsage | None, plan_error: str | None,
                bedrock_calls: int, tick_ms: float) -> TickResult:
        changed = d.effective_policy is not None and d.effective_policy != before
        if d.effective_policy is not None:
            self.active_policy = d.effective_policy
        plan_valid = None
        if plan_called:
            plan_valid = plan is not None and plan.policy.value == d.effective_policy
            if plan is not None and not plan_valid:
                # never keep a plan written for another tactic; needs_plan() asks again next moment
                plan_error = plan_error or (f"plan rejected: written for {plan.policy.value}, "
                                            f"requested {d.effective_policy}")
                plan = None
        if plan is not None:
            self.plan = plan
        usages = [u for u in (d.llm_usage, plan_usage) if u is not None]
        return TickResult(
            flow=self.flow, tick=tick, decision=d, active_policy_before=before, policy_changed=changed,
            plan_called=plan_called, plan=plan, plan_usage=plan_usage, plan_error=plan_error, plan_valid=plan_valid,
            deadline_missed=d.effective_policy is None or d.decision_latency_ms > self.deadline_s * 1000,
            tick_latency_ms=round(tick_ms, 1), bedrock_calls=bedrock_calls,
            input_tokens=sum(u.input_tokens for u in usages), output_tokens=sum(u.output_tokens for u in usages),
            cost_usd=sum(u.cost_usd for u in usages), mode=self.mode,
        )
