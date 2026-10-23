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
