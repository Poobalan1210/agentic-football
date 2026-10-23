from matchsense.bedrock_client import LLMError
from matchsense.decider_client import DeciderTimeout
from matchsense.mock import mock_plan
from matchsense.schemas import DeciderResult, LLMUsage, PolicyChoice


class FakeDecider:
    """Returns a scripted (choice, confidence) per call, or raises."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.texts = []

    def decide_choice(self, state_text, question, options):
        self.texts.append(state_text)
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        choice, conf = item
        return DeciderResult(choice=choice, confidence=conf, probabilities={choice: 0.9}, client_latency_ms=50.0)


class FakeTactics:
    def __init__(self, fast_policy="LOW_BLOCK", fail_fast=False):
        self.fast_policy = fast_policy
        self.fail_fast = fail_fast
        self.choose_calls = self.plan_calls = self.choose_and_plan_calls = 0
        self.texts = []

    def _u(self, m):
        return LLMUsage(model_id=m, input_tokens=10, output_tokens=5, latency_ms=1.0, cost_usd=0.0001)

    def choose_policy(self, text):
        self.texts.append(text)
        self.choose_calls += 1
        if self.fail_fast:
            raise LLMError("boom", self._u("fast"), 1)
        return PolicyChoice(policy=self.fast_policy, reason="r"), self._u("fast"), 1

    def write_plan(self, text, policy):
        self.texts.append(text)
        self.plan_calls += 1
        return mock_plan(policy), self._u("pro"), 1

    def choose_and_plan(self, text):
        self.texts.append(text)
        self.choose_and_plan_calls += 1
        return mock_plan(self.fast_policy), self._u("pro"), 1


def timeout():
    return DeciderTimeout("no answer")
