"""REUSABLE DECISION PATTERN: policy classification  (#policy)

What it does
    Every tick, the incoming request is the match state. Before the agent acts, Strands Decider 2B
    classifies it into one of five tactical policies with one typed `choice` question. The policy
    then drives everything downstream (here: whether Amazon Nova must write a new plan).

Question and options
    QUESTION and POLICY_OPTIONS below. Each option has a one-line definition that Decider reads.

Confidence and fallback
    - Decider's own `confidence` >= threshold  -> use Decider's choice.
    - below threshold                           -> the fast Nova model picks from the SAME options
                                                   with the SAME state text (fallback_reason=low_confidence).
    - Decider error / timeout                   -> the same Nova fallback (fallback_reason=decider_error
                                                   or decider_timeout). Decider is never reported as
                                                   having answered.
    The raw Decider policy and the effective policy are always recorded separately.

How to reuse it
    Replace QUESTION / POLICY_OPTIONS with your own policies and `state_text` with your own state
    renderer; keep `decide_policy` as is.
"""

from __future__ import annotations

import time
from typing import Protocol

from .decider_client import DeciderError
from .schemas import POLICY_NAMES, DeciderResult, LLMUsage, PolicyChoice, PolicyDecision

QUESTION = "Given the current five-a-side match situation, which tactical policy should the team follow next?"

# Condition-first definitions ("when X, so we do Y"). In a probe on 57 labelled states this
# wording scored 30/57 against 18/57 for action-first definitions (see docs/BENCHMARK_METHODOLOGY.md).
POLICY_OPTIONS: dict[str, str] = {
    "HIGH_PRESS": ("the opponent has the ball deep in their own half, far from our goal, and we press them high up "
                   "the pitch to force a turnover"),
    "COUNTERATTACK": ("we have just won the ball and their defence is out of position, so we attack the open space "
                      "at speed"),
    "KEEP_POSSESSION": "we have the ball but their defenders are in place, so we pass safely and build patiently",
    "PROTECT_LEAD": "we are ahead near the end of the match, so we take no risks and run down the clock",
    "LOW_BLOCK": ("the opponent has the ball in our half or is breaking towards our goal, so we drop deep, protect the centre "
                  "and break out with controlled transitions"),
}

assert list(POLICY_OPTIONS) == POLICY_NAMES

FAST_SYSTEM = ("You are a five-a-side football tactical analyst. Choose exactly one tactical policy for our "
               "team from the given options. Answer with the requested structure only.")


def fast_prompt(state_text: str) -> str:
    opts = "\n".join(f"- {k}: {v}" for k, v in POLICY_OPTIONS.items())
    return f"MATCH STATE:\n{state_text}\n\nQUESTION: {QUESTION}\n\nOPTIONS:\n{opts}\n\nPick one option and give a one-sentence reason."


class ChoiceDecider(Protocol):
    def decide_choice(self, state_text: str, question: str, options: dict[str, str]) -> DeciderResult: ...


class PolicyLLM(Protocol):
    def choose_policy(self, state_text: str) -> tuple[PolicyChoice, LLMUsage, int]: ...


def decide_policy(state_text: str, decider: ChoiceDecider, fallback: PolicyLLM | None, threshold: float,
                  mode: str = "nova_micro", current_policy: str | None = None) -> tuple[PolicyDecision, int]:
    """Decider first; what happens when it is unsure or fails depends on `mode`:

    nova_micro  ask the fast Nova model (same options, same text)      -> decided_by="nova_fast"
    nova_pro    ask the strong Nova model (same options, same text)    -> decided_by="nova_strong"
    hold        keep the current policy (no LLM call); on the first tick take Decider's top choice
    none        always take Decider's top choice; on an error keep the current policy

    Returns (decision, Bedrock calls). The raw Decider answer is always recorded.
    """
    d = PolicyDecision()
    t0 = time.perf_counter()
    unsure = False
    try:
        r = decider.decide_choice(state_text, QUESTION, POLICY_OPTIONS)
        d.raw_decider_policy = r.choice
        d.decider_confidence = r.confidence
        d.decider_probabilities = r.probabilities
        d.decider_latency_ms = r.client_latency_ms
        d.decider_server_latency_ms = r.server_latency_ms
        d.decider_input_tokens = r.input_tokens
        if r.confidence is not None and r.confidence >= threshold:
            d.effective_policy, d.decided_by = r.choice, "decider"
        else:
            unsure = True
            d.fallback_reason = "low_confidence" if r.confidence is not None else "no_confidence_field"
    except DeciderError as e:
        d.decider_error = f"{e.kind}: {e}"
        d.decider_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        unsure = True
        d.fallback_reason = "decider_timeout" if e.kind == "decider_timeout" else "decider_error"

    calls = 0
    if unsure:
        d.fallback = True
        errored = d.raw_decider_policy is None
        if mode == "none" and not errored:
            d.effective_policy, d.decided_by, d.fallback = d.raw_decider_policy, "decider", False
            d.fallback_reason = None
        elif mode in ("hold", "none") and current_policy is not None:
            d.effective_policy, d.decided_by = current_policy, "hold"
        elif mode == "hold" and not errored:
            d.effective_policy, d.decided_by = d.raw_decider_policy, "decider"  # first tick: nothing to hold
        elif fallback is None:
            d.llm_error = "no fallback model configured"
        else:
            strong = mode == "nova_pro" and hasattr(fallback, "choose_policy_strong")
            calls = llm_policy_into(d, state_text, fallback, strong=strong)
            if d.llm_policy:
                d.effective_policy, d.decided_by = d.llm_policy, "nova_strong" if strong else "nova_fast"
    # Never end a tick without a tactic: if the fallback also failed, use Decider's own pick,
    # and if Decider gave nothing either, keep the current tactic. Both errors stay recorded.
    if d.effective_policy is None:
        if d.raw_decider_policy is not None:
            d.effective_policy, d.decided_by = d.raw_decider_policy, "decider"
        elif current_policy is not None:
            d.effective_policy, d.decided_by = current_policy, "hold"
    d.decision_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    return d, calls


def llm_policy_into(d: PolicyDecision, state_text: str, llm: PolicyLLM, strong: bool = False) -> int:
    """Ask the LLM for the policy and record the result (or the error) in `d`. Returns calls."""
    from .bedrock_client import LLMError

    try:
        choice, usage, calls = (llm.choose_policy_strong if strong else llm.choose_policy)(state_text)
        d.llm_policy, d.llm_reason, d.llm_usage = choice.policy.value, choice.reason, usage
        return calls
    except LLMError as e:
        d.llm_error, d.llm_usage = str(e), e.usage
        return e.calls
