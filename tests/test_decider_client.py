import httpx
import pytest

from matchsense.decider_client import (DeciderAuthError, DeciderBadResponse, DeciderClient, DeciderRateLimited,
                                       DeciderTimeout)
from matchsense.policy_decision import POLICY_OPTIONS, QUESTION

GOOD = {"model": "strands-decider-2b-hobson-v19", "id": "req_1", "latency_ms": 12.5, "usage": {"input_tokens": 100},
        "answers": {"policy": {"type": "choice", "choice": "COUNTERATTACK",
                               "probabilities": {"HIGH_PRESS": 0.05, "COUNTERATTACK": 0.9, "KEEP_POSSESSION": 0.03,
                                                 "PROTECT_LEAD": 0.01, "LOW_BLOCK": 0.01},
                               "confidence": 0.88}}}


def client(handler, timeout=2.0):
    return DeciderClient(base_url="https://d.test", api_key="k_secret", timeout_s=timeout,
                         transport=httpx.MockTransport(handler))


def test_parses_response_and_sends_bearer_and_choice_question():
    seen = {}

    def h(req: httpx.Request):
        seen["auth"] = req.headers.get("authorization")
        seen["path"] = req.url.path
        seen["body"] = req.read()
        return httpx.Response(200, json=GOOD)

    r = client(h).decide_choice("state", QUESTION, POLICY_OPTIONS)
    assert seen["auth"] == "Bearer k_secret" and seen["path"] == "/v1/decide"
    assert b'"type":"choice"' in seen["body"].replace(b" ", b"")
    assert r.choice == "COUNTERATTACK" and r.confidence == 0.88
    assert r.probabilities["COUNTERATTACK"] == 0.9 and r.server_latency_ms == 12.5 and r.input_tokens == 100


def test_missing_confidence_is_none_not_computed():
    body = {"answers": {"policy": {k: v for k, v in GOOD["answers"]["policy"].items() if k != "confidence"}}}
    r = client(lambda req: httpx.Response(200, json=body)).decide_choice("s", QUESTION, POLICY_OPTIONS)
    assert r.confidence is None


def test_timeout():
    def h(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(DeciderTimeout):
        client(h).decide_choice("s", QUESTION, POLICY_OPTIONS)


@pytest.mark.parametrize("code,exc", [(401, DeciderAuthError), (403, DeciderAuthError), (429, DeciderRateLimited)])
def test_http_errors(code, exc):
    with pytest.raises(exc):
        client(lambda req: httpx.Response(code, text="no")).decide_choice("s", QUESTION, POLICY_OPTIONS)


def test_invalid_option_rejected():
    body = {"answers": {"policy": {**GOOD["answers"]["policy"], "choice": "ALL_OUT_ATTACK"}}}
    with pytest.raises(DeciderBadResponse):
        client(lambda req: httpx.Response(200, json=body)).decide_choice("s", QUESTION, POLICY_OPTIONS)


def test_malformed_payload():
    with pytest.raises(DeciderBadResponse):
        client(lambda req: httpx.Response(200, json={"oops": 1})).decide_choice("s", QUESTION, POLICY_OPTIONS)


def test_repr_hides_key():
    assert "k_secret" not in repr(client(lambda r: httpx.Response(200, json=GOOD)))
