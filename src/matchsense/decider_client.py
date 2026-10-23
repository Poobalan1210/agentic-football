"""Client for the hosted Strands Decider 2B (AWS User Group Madurai decision cloud).

Wire format, confirmed from the hackathon kit (decider_kit/client.py) and a live call:

    POST {DECIDER_BASE_URL}/v1/decide        Authorization: Bearer <key>
    {"state": "<text>", "questions": {"policy": {"type": "choice", "instructions": "...",
                                                 "criteria": {"OPTION": "definition", ...}}}}
    -> {"model": "...", "id": "req_...", "latency_ms": 1134.1, "usage": {"input_tokens": 160, ...},
        "answers": {"policy": {"type": "choice", "choice": "OPTION",
                               "probabilities": {"OPTION": 0.53, ...}, "confidence": 0.42}}}

    GET {DECIDER_BASE_URL}/v1/models         -> {"data": [{"id": "...", "ready": true, ...}]}

`confidence` is the server's own number (per the strands-decider docs: the top probability
rescaled so an even split is 0 and certainty is 1). It is recorded as returned, or None if absent.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from .config import settings
from .schemas import DeciderResult

QUESTION_KEY = "policy"


class DeciderError(RuntimeError):
    """Base class: the Decider did not give a usable answer."""

    kind = "decider_error"


class DeciderTimeout(DeciderError):
    kind = "decider_timeout"


class DeciderAuthError(DeciderError):
    kind = "decider_auth"


class DeciderRateLimited(DeciderError):
    kind = "decider_rate_limited"


class DeciderBadResponse(DeciderError):
    kind = "decider_bad_response"


class DeciderClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, auth_header: str | None = None,
                 timeout_s: float | None = None, transport: httpx.BaseTransport | None = None,
                 mode: str | None = None):
        s = settings()
        # hosted: POST /v1/decide with a Bearer key; local strands-decider serve: POST /v1/systemone, no key
        self.mode = mode or s.decider_mode
        default_url = s.decider_local_url if self.mode == "local" else s.decider_base_url
        self.base_url = (base_url if base_url is not None else default_url).rstrip("/")
        self._key = "" if self.mode == "local" else (api_key if api_key is not None else s.decider_api_key)
        self.decide_path = "/v1/systemone" if self.mode == "local" else "/v1/decide"
        self.auth_header = auth_header or s.decider_auth_header
        self.timeout_s = timeout_s if timeout_s is not None else s.decider_timeout_s
        headers = {"content-type": "application/json"}
        if self._key:
            headers[self.auth_header] = f"Bearer {self._key}" if self.auth_header.lower() == "authorization" else self._key
        # one keep-alive session for every call
        self._http = httpx.Client(base_url=self.base_url, headers=headers, timeout=self.timeout_s, transport=transport,
                                  limits=httpx.Limits(max_keepalive_connections=8, max_connections=16))
        self._lock = threading.Lock()
        self.calls = 0

    def __repr__(self) -> str:  # never show the key
        return f"DeciderClient(mode={self.mode!r}, base_url={self.base_url!r}, key_set={bool(self._key)})"

    def close(self) -> None:
        self._http.close()

    # -------------------------------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            r = self._http.get("/health" if self.mode == "local" else "/v1/models", timeout=max(self.timeout_s, 10.0))
        except httpx.TimeoutException as e:
            raise DeciderTimeout(f"health check timed out after {self.timeout_s}s") from e
        except httpx.HTTPError as e:
            raise DeciderError(f"health check failed: {type(e).__name__}: {e}") from e
        ms = (time.perf_counter() - t0) * 1000
        self._raise_for_status(r)
        body = r.json()
        if self.mode == "local":
            return {"ok": body.get("status") == "ok", "latency_ms": round(ms, 1), "where": "local",
                    "models": [{"id": body.get("model"), "ready": body.get("status") == "ok", "device": body.get("device")}]}
        models = body.get("data", []) if isinstance(body, dict) else []
        return {"ok": any(m.get("ready") for m in models), "latency_ms": round(ms, 1), "where": "hosted",
                "models": [{"id": m.get("id"), "ready": m.get("ready"), "question_types": m.get("question_types")}
                           for m in models]}

    def decide_choice(self, state_text: str, question: str, options: dict[str, str]) -> DeciderResult:
        """One typed choice question about one state. Decider never writes text."""
        if not options:
            raise DeciderError("no options")
        body = {"state": state_text,
                "questions": {QUESTION_KEY: {"type": "choice", "instructions": question, "criteria": dict(options)}}}
        t0 = time.perf_counter()
        try:
            r = self._http.post(self.decide_path, json=body)
        except httpx.TimeoutException as e:
            raise DeciderTimeout(f"no answer within {self.timeout_s}s") from e
        except httpx.HTTPError as e:
            raise DeciderError(f"request failed: {type(e).__name__}: {e}") from e
        client_ms = (time.perf_counter() - t0) * 1000
        with self._lock:
            self.calls += 1
        self._raise_for_status(r)
        try:
            payload = r.json()
        except ValueError as e:
            raise DeciderBadResponse("response is not JSON") from e
        return parse_choice(payload, list(options), client_ms)

    @staticmethod
    def _raise_for_status(r: httpx.Response) -> None:
        if r.status_code < 400:
            return
        detail = r.text[:200]
        if r.status_code in (401, 403):
            raise DeciderAuthError(f"HTTP {r.status_code}: check DECIDER_API_KEY ({detail})")
        if r.status_code in (402, 429):
            raise DeciderRateLimited(f"HTTP {r.status_code}: quota or rate limit ({detail})")
        raise DeciderError(f"HTTP {r.status_code}: {detail}")


def parse_choice(payload: Any, options: list[str], client_ms: float) -> DeciderResult:
    """Validate a /v1/decide payload for our one choice question. Nothing is invented."""
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise DeciderBadResponse("response has no 'answers' object")
    ans = payload["answers"].get(QUESTION_KEY)
    if not isinstance(ans, dict) or ans.get("type") != "choice":
        raise DeciderBadResponse(f"no choice answer under '{QUESTION_KEY}'")
    choice = ans.get("choice")
    if choice not in options:
        raise DeciderBadResponse(f"choice {choice!r} is not one of the options")
    probs_raw = ans.get("probabilities") or {}
    try:
        probs = {str(k): float(v) for k, v in probs_raw.items()}
    except (TypeError, ValueError, AttributeError) as e:
        raise DeciderBadResponse("probabilities are not numbers") from e
    conf = ans.get("confidence")
    usage = payload.get("usage") or {}
    return DeciderResult(
        choice=choice,
        confidence=float(conf) if isinstance(conf, (int, float)) else None,
        probabilities=probs,
        model=payload.get("model"),
        request_id=payload.get("id"),
        server_latency_ms=payload.get("latency_ms"),
        client_latency_ms=round(client_ms, 1),
        input_tokens=usage.get("input_tokens"),
    )
