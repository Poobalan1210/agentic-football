"""Our agent, in two variants (both: Strands Decider 2B decides the tactic, Amazon Nova Pro writes the plan).

Flow A   "Decider decides"                 Decider's pick is used on every tick, however sure it is.
Flow A2  "Decider + Nova Pro when unsure"  below CONFIDENCE_THRESHOLD, Nova Pro answers the same
                                           question instead (FALLBACK_MODE, default nova_pro).

In both, Nova Pro writes a new plan only when there is no plan for the current tactic (the tactic
changed, or the last plan call failed / came back for another tactic, so it is retried). If anything fails, the tick still
gets a tactic (Decider's pick, or the current one) and the errors are recorded.
"""

from __future__ import annotations

import time

from .config import settings
from .flow_base import Lane
from .policy_decision import decide_policy
from .schemas import TickResult


class HybridLane(Lane):
    def __init__(self, decider, tactics, mode, threshold: float | None = None, deadline_s: float | None = None,
                 fallback_mode: str | None = None, flow: str = "A2"):
        super().__init__(tactics, mode, deadline_s)
        s = settings()
        self.flow = flow
        self.decider = decider
        self.threshold = threshold if threshold is not None else s.confidence_threshold
        self.fallback_mode = fallback_mode or ("none" if flow == "A" else s.fallback_mode)

    def step(self, tick: int, state_text: str) -> TickResult:
        t0 = time.perf_counter()
        before = self.active_policy
        d, calls = decide_policy(state_text, self.decider, self.tactics, self.threshold,
                                 mode=self.fallback_mode, current_policy=before)
        d.fallback_mode = self.fallback_mode
        plan = usage = err = None
        plan_called = False
        if self.needs_plan(d.effective_policy):
            plan_called = True
            plan, usage, err, pc = self._write_plan(state_text, d.effective_policy)
            calls += pc
        return self._result(tick, d, before, plan_called, plan, usage, err, calls, (time.perf_counter() - t0) * 1000)
