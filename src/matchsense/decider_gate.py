"""REUSABLE DECISION PATTERN, Strands wiring: `DeciderPolicyGate`  (#policy)

The same #policy decision as `policy_decision.py`, packaged as a Strands `InterventionHandler` so
any Strands agent gets "Strands Decider 2B decides, the LLM only speaks when the policy changes"
with one line:

    planner = Agent(model=BedrockModel(model_id="us.amazon.nova-pro-v1:0"),
                    interventions=[DeciderPolicyGate(decider, QUESTION, POLICY_OPTIONS)])
    result = planner("Write the plan.", invocation_state={"state_text": state_text})

What happens on every call (`before_invocation`, before any model call):

  1. Decider answers one typed `choice` question about `invocation_state["state_text"]`
     (the question and option definitions you pass in).
  2. Policy unchanged and a plan already exists for it  -> `Deny`: the agent stops before
     calling Bedrock (0 tokens). `result.stop_reason == "end_turn"`, text starts "DENIED:".
  3. Policy changed (or the last plan for it failed)    -> `Transform`: the chosen policy and its
     definition are put at the top of the user message, so the LLM writes for that policy.
  4. Optional `unsure_below=t`: if Decider's own confidence is below t, the LLM is told Decider
     is unsure and decides itself (Decider's ranking is included).

The policy only counts as "planned" after a model call finishes without an exception
(`after_model_call`), so a failed call is retried on the next invocation even if the policy did
not change. `gate.last` holds Decider's last answer (choice, confidence, probabilities, latency).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from strands.interventions import Deny, InterventionHandler, Proceed, Transform

from .decider_client import DeciderError
from .schemas import DeciderResult


class DeciderPolicyGate(InterventionHandler):
    name = "decider-policy-gate"

    def __init__(self, decider: Any, question: str, options: Mapping[str, str], *,
                 state_key: str = "state_text", unsure_below: float | None = None):
        self.decider = decider            # anything with decide_choice(state_text, question, options)
        self.question = question
        self.options = dict(options)
        self.state_key = state_key
        self.unsure_below = unsure_below
        self.planned: str | None = None   # policy the current plan was written for
        self.pending: str | None = None   # policy injected into the call in flight
        self.last: DeciderResult | None = None
        self.last_action: str | None = None   # "deny" | "plan" | "llm_decides" | "decider_error"
        self.denied = 0
        self.passed = 0

    @property
    def on_error(self) -> str:
        return "throw"

    # -------------------------------------------------------------------------------------------

    def _state_text(self, event: Any) -> str:
        text = (event.invocation_state or {}).get(self.state_key)
        if text:
            return str(text)
        for m in reversed(event.messages or []):  # fall back to the user's message text
            if m.get("role") == "user":
                return " ".join(b.get("text", "") for b in m.get("content", []) if "text" in b)
        raise ValueError(f"DeciderPolicyGate needs invocation_state['{self.state_key}'] or a user message")

    @staticmethod
    def _prepend(event: Any, text: str) -> None:
        for m in reversed(event.messages or []):
            if m.get("role") == "user":
                m["content"] = [{"text": text}, *m.get("content", [])]
                return

    def before_invocation(self, event: Any, **kwargs: Any):
        state = self._state_text(event)
        try:
            r = self.decider.decide_choice(state, self.question, self.options)
        except DeciderError as e:   # Decider down: let the LLM decide; never pretend Decider answered
            self.last, self.last_action, self.pending = None, "decider_error", None
            self.planned = None
            self.passed += 1
            note = (f"[Strands Decider 2B was unavailable ({e.kind}). Choose the policy yourself from: "
                    f"{', '.join(self.options)}.]")
            return Transform(apply=lambda ev: self._prepend(ev, note), reason="decider error")
        self.last = r
        policy = r.choice
        if self.unsure_below is not None and r.confidence is not None and r.confidence < self.unsure_below:
            ranked = sorted(r.probabilities.items(), key=lambda kv: -kv[1])
            note = ("[Strands Decider 2B is unsure (confidence "
                    f"{r.confidence:.2f}); its ranking: " + ", ".join(f"{k} {v:.2f}" for k, v in ranked)
                    + ". Choose the policy yourself from these options.]")
            self.last_action, self.pending, self.planned = "llm_decides", None, None
            self.passed += 1
            return Transform(apply=lambda ev: self._prepend(ev, note), reason="decider unsure")
        if policy == self.planned:
            self.last_action = "deny"
            self.denied += 1
            return Deny(reason=f"policy unchanged ({policy}); the current plan stays")
        self.pending, self.last_action = policy, "plan"
        self.passed += 1
        note = (f"POLICY TO FOLLOW (decided by Strands Decider 2B, confidence "
                f"{'n/a' if r.confidence is None else f'{r.confidence:.2f}'}): {policy} — {self.options[policy]}")
        return Transform(apply=lambda ev: self._prepend(ev, note), reason=f"policy changed to {policy}")

    def after_model_call(self, event: Any, **kwargs: Any):
        if getattr(event, "exception", None) is None and self.pending is not None:
            self.planned, self.pending = self.pending, None
        return Proceed()
