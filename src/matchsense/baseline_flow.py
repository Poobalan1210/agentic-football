"""LLM-only baselines.

Flow B1 (decision only): Nova Micro picks the policy every tick; Nova Pro re-plans only on change
(the same rule as Flow A), so the only variable is who decides.

Flow B2 (naive agent): one Nova Pro call per tick picks the policy and writes the full plan.
"""

from __future__ import annotations

import time

from .bedrock_client import LLMError
from .flow_base import Lane
from .policy_decision import llm_policy_into
from .schemas import PolicyDecision, TickResult


class B1Lane(Lane):
    flow = "B1"

    def step(self, tick: int, state_text: str) -> TickResult:
        t0 = time.perf_counter()
        before = self.active_policy
        d = PolicyDecision()
        calls = llm_policy_into(d, state_text, self.tactics)
        d.decision_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if d.llm_policy:
            d.effective_policy, d.decided_by = d.llm_policy, "nova_fast"
        plan = usage = err = None
        plan_called = False
        if d.effective_policy is not None and d.effective_policy != before:
            plan_called = True
            plan, usage, err, pc = self._write_plan(state_text, d.effective_policy)
            calls += pc
        return self._result(tick, d, before, plan_called, plan, usage, err, calls, (time.perf_counter() - t0) * 1000)


class B2Lane(Lane):
    flow = "B2"

    def step(self, tick: int, state_text: str) -> TickResult:
        t0 = time.perf_counter()
        before = self.active_policy
        d = PolicyDecision()
        plan = err = None
        try:
            plan, usage, calls = self.tactics.choose_and_plan(state_text)
            d.llm_policy, d.llm_reason = plan.policy.value, plan.why_this_policy
            d.effective_policy, d.decided_by = plan.policy.value, "nova_planner"
        except LLMError as e:
            usage, calls, err = e.usage, e.calls, str(e)
            d.llm_error = err
        d.decision_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        # the single call is both decision and plan: count its usage once, as the plan's
        return self._result(tick, d, before, True, plan, usage, err, calls, (time.perf_counter() - t0) * 1000)


BASELINES = {"B1": B1Lane, "B2": B2Lane}
