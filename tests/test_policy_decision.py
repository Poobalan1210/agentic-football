from fakes import FakeDecider, FakeTactics, timeout

from matchsense.decider_client import DeciderAuthError
from matchsense.policy_decision import decide_policy


def test_confident_decider_is_used_without_llm():
    t = FakeTactics()
    d, calls = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.8)]), t, 0.7)
    assert d.effective_policy == "COUNTERATTACK" and d.decided_by == "decider"
    assert not d.fallback and calls == 0 and t.choose_calls == 0


def test_threshold_is_inclusive():
    d, _ = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.7)]), FakeTactics(), 0.7)
    assert not d.fallback


def test_low_confidence_falls_back_and_keeps_raw():
    d, calls = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.4)]), FakeTactics("LOW_BLOCK"), 0.7)
    assert d.raw_decider_policy == "COUNTERATTACK" and d.decider_confidence == 0.4
    assert d.effective_policy == "LOW_BLOCK" and d.decided_by == "nova_fast"
    assert d.fallback and d.fallback_reason == "low_confidence" and calls == 1


def test_missing_confidence_falls_back():
    d, _ = decide_policy("s", FakeDecider([("COUNTERATTACK", None)]), FakeTactics(), 0.7)
    assert d.fallback and d.fallback_reason == "no_confidence_field" and d.decider_confidence is None


def test_timeout_and_error_fall_back_without_pretending():
    d, _ = decide_policy("s", FakeDecider([timeout()]), FakeTactics("HIGH_PRESS"), 0.7)
    assert d.fallback_reason == "decider_timeout" and d.raw_decider_policy is None and d.effective_policy == "HIGH_PRESS"
    d, _ = decide_policy("s", FakeDecider([DeciderAuthError("bad key")]), FakeTactics(), 0.7)
    assert d.fallback_reason == "decider_error" and "decider_auth" in d.decider_error


def test_both_fail_on_first_tick_gives_no_decision():
    d, calls = decide_policy("s", FakeDecider([timeout()]), FakeTactics(fail_fast=True), 0.7)
    assert d.effective_policy is None and d.llm_error and calls == 1


def test_both_fail_later_keeps_current_tactic():
    d, _ = decide_policy("s", FakeDecider([timeout()]), FakeTactics(fail_fast=True), 0.7, current_policy="LOW_BLOCK")
    assert d.effective_policy == "LOW_BLOCK" and d.decided_by == "hold" and d.decider_error and d.llm_error


def test_nova_fails_when_unsure_uses_deciders_pick():
    d, calls = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.1)]), FakeTactics(fail_fast=True), 0.3,
                             mode="nova_pro", current_policy="LOW_BLOCK")
    assert d.effective_policy == "COUNTERATTACK" and d.decided_by == "decider" and d.llm_error and d.fallback


def test_hold_keeps_current_policy_without_llm():
    t = FakeTactics("LOW_BLOCK")
    d, calls = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.1)]), t, 0.3, mode="hold",
                             current_policy="KEEP_POSSESSION")
    assert d.effective_policy == "KEEP_POSSESSION" and d.decided_by == "hold" and calls == 0 and t.choose_calls == 0
    assert d.raw_decider_policy == "COUNTERATTACK" and d.fallback


def test_hold_first_tick_uses_decider_top_choice():
    d, calls = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.1)]), FakeTactics(), 0.3, mode="hold")
    assert d.effective_policy == "COUNTERATTACK" and d.decided_by == "decider" and calls == 0


def test_none_mode_trusts_decider_and_holds_on_error():
    d, _ = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.05)]), FakeTactics(), 0.3, mode="none")
    assert d.effective_policy == "COUNTERATTACK" and not d.fallback
    d, _ = decide_policy("s", FakeDecider([timeout()]), FakeTactics(), 0.3, mode="none", current_policy="LOW_BLOCK")
    assert d.effective_policy == "LOW_BLOCK" and d.decided_by == "hold"


def test_nova_pro_fallback_uses_strong_model():
    class Strong(FakeTactics):
        def choose_policy_strong(self, text):
            self.strong = True
            return self.choose_policy(text)

    t = Strong("HIGH_PRESS")
    d, calls = decide_policy("s", FakeDecider([("COUNTERATTACK", 0.1)]), t, 0.3, mode="nova_pro")
    assert d.decided_by == "nova_strong" and d.effective_policy == "HIGH_PRESS" and t.strong and calls == 1


def test_local_mode_uses_systemone_without_key():
    import httpx

    from matchsense.decider_client import DeciderClient
    from matchsense.policy_decision import POLICY_OPTIONS, QUESTION

    seen = {}

    def h(req):
        seen["path"], seen["auth"] = req.url.path, req.headers.get("authorization")
        return httpx.Response(200, json={"answers": {"policy": {"type": "choice", "choice": "LOW_BLOCK",
                                                               "probabilities": {"LOW_BLOCK": 0.9}, "confidence": 0.8}}})

    c = DeciderClient(base_url="http://127.0.0.1:8099", api_key="ignored", mode="local", transport=httpx.MockTransport(h))
    assert c.decide_choice("s", QUESTION, POLICY_OPTIONS).choice == "LOW_BLOCK"
    assert seen == {"path": "/v1/systemone", "auth": None}
