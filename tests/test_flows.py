from fakes import FakeDecider, FakeTactics

from matchsense.baseline_flow import B1Lane, B2Lane
from matchsense.hybrid_flow import HybridLane


def test_a2_plans_only_when_tactic_changes():
    dec = FakeDecider([("KEEP_POSSESSION", 0.9), ("KEEP_POSSESSION", 0.9), ("COUNTERATTACK", 0.9),
                       ("COUNTERATTACK", 0.3), ("COUNTERATTACK", 0.9)])
    t = FakeTactics(fast_policy="COUNTERATTACK")
    lane = HybridLane(dec, t, "mock", threshold=0.7, deadline_s=1.0, flow="A2")
    res = [lane.step(i, f"s{i}") for i in range(5)]
    assert [r.plan_called for r in res] == [True, False, True, False, False]  # tick 3: fallback, same tactic
    assert t.plan_calls == 2 and t.choose_calls == 1
    assert [r.bedrock_calls for r in res] == [1, 0, 1, 1, 0]
    assert res[2].policy_changed and not res[1].policy_changed


def test_a_decider_decides_every_tick_without_llm():
    from matchsense.runtime import runtime

    dec = FakeDecider([("KEEP_POSSESSION", 0.9), ("COUNTERATTACK", 0.05), ("COUNTERATTACK", 0.1)])
    t = FakeTactics(fast_policy="LOW_BLOCK")
    lane = HybridLane(dec, t, "mock", threshold=0.7, deadline_s=1.0, fallback_mode="none", flow="A")
    res = [lane.step(i, "s") for i in range(3)]
    assert [r.decision.effective_policy for r in res] == ["KEEP_POSSESSION", "COUNTERATTACK", "COUNTERATTACK"]
    assert t.choose_calls == 0 and t.plan_calls == 2 and all(r.decision.decided_by == "decider" for r in res)
    rt = runtime("mock")
    assert rt.lane("A").fallback_mode == "none" and rt.lane("A").flow == "A" and rt.lane("A2").flow == "A2"


def test_b1_decides_every_tick_and_plans_on_change():
    t = FakeTactics(fast_policy="LOW_BLOCK")
    lane = B1Lane(t, "mock", deadline_s=1.0)
    res = [lane.step(i, "s") for i in range(4)]
    assert t.choose_calls == 4 and t.plan_calls == 1
    assert [r.plan_called for r in res] == [True, False, False, False]


def test_b2_calls_planner_every_tick():
    t = FakeTactics()
    lane = B2Lane(t, "mock", deadline_s=1.0)
    res = [lane.step(i, "s") for i in range(3)]
    assert t.choose_and_plan_calls == 3 and all(r.plan_called and r.bedrock_calls == 1 for r in res)
    assert all(r.decision.decided_by == "nova_planner" for r in res)


def test_same_state_text_reaches_all_flows():
    from matchsense.runtime import runtime
    from matchsense.replay import run_match

    seen = {}
    rt = runtime("mock")
    orig_choose, orig_cp = rt.tactics.choose_policy, rt.tactics.choose_and_plan
    orig_dec = rt.decider.decide_choice
    rt.decider.decide_choice = lambda t, q, o: seen.setdefault("A", t) and orig_dec(t, q, o)
    rt.tactics.choose_policy = lambda t: seen.setdefault("B1", t) and orig_choose(t)
    rt.tactics.choose_and_plan = lambda t: seen.setdefault("B2", t) and orig_cp(t)
    run = run_match("m1_late_comeback", ["A", "B1", "B2"], rt, run_id="t", max_ticks=1)
    assert seen["A"] == seen["B1"] == seen["B2"] == run["ticks"][0]["state_text"]


class FlakyPlanner(FakeTactics):
    """write_plan fails on chosen calls, or returns a plan for the wrong tactic."""

    def __init__(self, fail_on=(), wrong_on=()):
        super().__init__()
        self.fail_on, self.wrong_on = set(fail_on), set(wrong_on)

    def write_plan(self, text, policy):
        from matchsense.bedrock_client import LLMError
        from matchsense.mock import mock_plan

        n = self.plan_calls
        self.plan_calls += 1
        if n in self.fail_on:
            raise LLMError("ModelErrorException: boom", self._u("pro"), 1)
        if n in self.wrong_on:
            return mock_plan("LOW_BLOCK" if policy != "LOW_BLOCK" else "HIGH_PRESS"), self._u("pro"), 1
        return mock_plan(policy), self._u("pro"), 1


def test_failed_plan_is_retried_next_moment():
    dec = FakeDecider([("KEEP_POSSESSION", 0.9), ("COUNTERATTACK", 0.9), ("COUNTERATTACK", 0.9), ("COUNTERATTACK", 0.9)])
    t = FlakyPlanner(fail_on={1})   # the plan for COUNTERATTACK fails the first time
    lane = HybridLane(dec, t, "mock", threshold=0.7, deadline_s=1.0, fallback_mode="none", flow="A")
    res = [lane.step(i, "s") for i in range(4)]
    assert [r.plan_called for r in res] == [True, True, True, False]
    assert res[1].plan_error and res[1].plan_valid is False
    assert res[2].plan_valid and lane.plan.policy.value == "COUNTERATTACK"
    assert not res[2].policy_changed  # retried even though the tactic did not change again


def test_plan_for_wrong_tactic_is_rejected_and_retried():
    dec = FakeDecider([("COUNTERATTACK", 0.9)] * 3)
    t = FlakyPlanner(wrong_on={0})
    lane = HybridLane(dec, t, "mock", threshold=0.7, deadline_s=1.0, fallback_mode="none", flow="A")
    res = [lane.step(i, "s") for i in range(3)]
    assert res[0].plan is None and res[0].plan_valid is False and "rejected" in res[0].plan_error
    assert res[1].plan_called and res[1].plan_valid and not res[2].plan_called
    assert lane.plan.policy.value == "COUNTERATTACK"


def test_b1_retries_failed_plan_too():
    t = FlakyPlanner(fail_on={0})
    lane = B1Lane(t, "mock", deadline_s=1.0)
    res = [lane.step(i, "s") for i in range(3)]
    assert [r.plan_called for r in res] == [True, True, False]


def test_default_threshold_is_030(monkeypatch):
    from matchsense.config import settings

    monkeypatch.delenv("CONFIDENCE_THRESHOLD", raising=False)
    monkeypatch.setattr("matchsense.config.load_dotenv", lambda *a, **k: None)
    settings.cache_clear()
    assert settings().confidence_threshold == 0.30
    settings.cache_clear()
