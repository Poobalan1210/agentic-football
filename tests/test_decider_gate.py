from types import SimpleNamespace

from fakes import FakeDecider

from matchsense.decider_client import DeciderTimeout
from matchsense.decider_gate import DeciderPolicyGate
from matchsense.policy_decision import POLICY_OPTIONS, QUESTION
from strands.interventions import Deny, Proceed, Transform


def ev(text="state", user="Write the plan."):
    return SimpleNamespace(invocation_state={"state_text": text},
                           messages=[{"role": "user", "content": [{"text": user}]}], exception=None)


def call(gate, e, ok=True):
    """Simulate one agent invocation: before_invocation, then (if not denied) one model call."""
    a = gate.before_invocation(e)
    if isinstance(a, Transform):
        a.apply(e)
        gate.after_model_call(SimpleNamespace(exception=None if ok else RuntimeError("bedrock down")))
    return a


def test_denies_when_policy_unchanged_and_injects_on_change():
    gate = DeciderPolicyGate(FakeDecider([("KEEP_POSSESSION", 0.6), ("KEEP_POSSESSION", 0.5), ("COUNTERATTACK", 0.8)]),
                             QUESTION, POLICY_OPTIONS)
    e1 = ev()
    assert isinstance(call(gate, e1), Transform)
    assert e1.messages[0]["content"][0]["text"].startswith("POLICY TO FOLLOW") and "KEEP_POSSESSION" in e1.messages[0]["content"][0]["text"]
    assert isinstance(call(gate, ev()), Deny) and gate.denied == 1
    e3 = ev()
    assert isinstance(call(gate, e3), Transform) and "COUNTERATTACK" in e3.messages[0]["content"][0]["text"]
    assert gate.planned == "COUNTERATTACK" and gate.passed == 2


def test_failed_model_call_is_retried_even_if_policy_unchanged():
    gate = DeciderPolicyGate(FakeDecider([("LOW_BLOCK", 0.7)] * 3), QUESTION, POLICY_OPTIONS)
    assert isinstance(call(gate, ev(), ok=False), Transform) and gate.planned is None
    assert isinstance(call(gate, ev()), Transform) and gate.planned == "LOW_BLOCK"
    assert isinstance(call(gate, ev()), Deny)


def test_unsure_lets_llm_decide_with_ranking():
    gate = DeciderPolicyGate(FakeDecider([("HIGH_PRESS", 0.1)]), QUESTION, POLICY_OPTIONS, unsure_below=0.3)
    e = ev()
    assert isinstance(call(gate, e), Transform) and gate.last_action == "llm_decides"
    assert "unsure" in e.messages[0]["content"][0]["text"] and gate.planned is None


def test_decider_error_never_pretends_and_lets_llm_decide():
    gate = DeciderPolicyGate(FakeDecider([DeciderTimeout("slow")]), QUESTION, POLICY_OPTIONS)
    e = ev()
    assert isinstance(call(gate, e), Transform) and gate.last is None and gate.last_action == "decider_error"
    assert "unavailable" in e.messages[0]["content"][0]["text"]


def test_after_model_call_returns_proceed():
    gate = DeciderPolicyGate(FakeDecider([("LOW_BLOCK", 0.7)]), QUESTION, POLICY_OPTIONS)
    assert isinstance(gate.after_model_call(SimpleNamespace(exception=None)), Proceed)


def test_real_strands_agent_deny_makes_no_model_call():
    """End to end through Strands: a denied invocation stops before the model (no network needed)."""
    from strands import Agent
    from strands.models import BedrockModel

    gate = DeciderPolicyGate(FakeDecider([("LOW_BLOCK", 0.7)]), QUESTION, POLICY_OPTIONS)
    gate.planned = "LOW_BLOCK"  # a plan for LOW_BLOCK already exists
    agent = Agent(model=BedrockModel(model_id="us.amazon.nova-pro-v1:0", region_name="us-east-1"),
                  interventions=[gate], callback_handler=None)
    r = agent("Write the plan.", invocation_state={"state_text": "s"})
    assert str(r).startswith("DENIED:") and r.metrics.cycle_count == 0
    assert r.metrics.accumulated_usage.get("inputTokens", 0) == 0


def test_reusable_with_any_question_and_options():
    """The gate is domain-agnostic: it sends the question and options it was given, not the football ones."""
    question = "Which handling policy fits this support ticket?"
    options = {"self_serve": "the answer is in the docs, so we reply with a link",
               "escalate": "money or data is at risk, so a human takes over",
               "clarify": "the request is ambiguous, so we ask one question"}
    seen = []

    class RecordingDecider(FakeDecider):
        def decide_choice(self, state_text, q, opts):
            seen.append((q, dict(opts)))
            return super().decide_choice(state_text, q, opts)

    gate = DeciderPolicyGate(RecordingDecider([("escalate", 0.8), ("escalate", 0.7), ("clarify", 0.6)]), question, options,
                             state_key="ticket_text")
    e1 = SimpleNamespace(invocation_state={"ticket_text": "I was charged twice"},
                         messages=[{"role": "user", "content": [{"text": "Reply to the customer."}]}], exception=None)
    assert isinstance(call(gate, e1), Transform)
    assert "escalate — money or data is at risk" in e1.messages[0]["content"][0]["text"]
    assert isinstance(call(gate, e1), Deny)
    assert isinstance(call(gate, e1), Transform) and gate.planned == "clarify"
    assert seen == [(question, options)] * 3
