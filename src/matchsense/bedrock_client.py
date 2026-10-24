"""Amazon Nova on Amazon Bedrock through the Strands Agents SDK, structured output only.

Every call is one Strands `Agent` (no tools, no memory) with a Pydantic `structured_output_model`.
Token counts come from the SDK's `accumulated_usage`; `cycle_count` gives the number of model
invocations the SDK made (structured-output retries included), which we count as Bedrock calls.
"""

from __future__ import annotations

import threading
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from .config import settings
from .schemas import LLMUsage

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens (input, output), Amazon Bedrock on-demand, us-east-1, standard tier.
# Official page: https://aws.amazon.com/bedrock/pricing/ (prices load dynamically, so not machine-read).
# Values taken from the hackathon kit's decider_kit/llm.py ("October 2026") and cross-checked on
# 2026-10-23 against https://models.litellm.ai/models/nova-micro (Micro $0.035 / $0.14, as of
# 2026-10-19) and an AWS ML blog table (Pro ~$0.80 / ~$3.20). Re-check before publishing numbers.
NOVA_PRICES = {
    "amazon.nova-micro-v1:0": (0.035, 0.14),
    "amazon.nova-lite-v1:0": (0.06, 0.24),
    "amazon.nova-pro-v1:0": (0.80, 3.20),
}


def base_model_id(model_id: str) -> str:
    head, _, rest = model_id.partition(".")
    return rest if head in ("us", "eu", "apac", "global") and rest else model_id


def cost_usd(model_id: str, tin: int, tout: int) -> float:
    pin, pout = NOVA_PRICES.get(base_model_id(model_id), (0.0, 0.0))
    return tin / 1e6 * pin + tout / 1e6 * pout


RETRYABLE = ("ToolUse", "StructuredOutput", "Throttl", "ServiceUnavailable", "TooManyRequests")


class LLMError(RuntimeError):
    def __init__(self, msg: str, usage: LLMUsage | None = None, calls: int = 1):
        super().__init__(msg)
        self.usage = usage
        self.calls = calls


class NovaClient:
    """Shares one Strands BedrockModel (and boto3 client) per model id across threads."""

    def __init__(self, region: str | None = None, timeout_s: float | None = None):
        s = settings()
        self.region = region or s.aws_region
        self.timeout_s = timeout_s or s.bedrock_timeout_s
        self._models: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _model(self, model_id: str, max_tokens: int) -> Any:
        key = f"{model_id}|{max_tokens}"
        with self._lock:
            if key not in self._models:
                from botocore.config import Config
                from strands.models import BedrockModel

                cfg = Config(read_timeout=self.timeout_s, connect_timeout=5, retries={"max_attempts": 1, "mode": "standard"})  # no hidden retries
                self._models[key] = BedrockModel(model_id=model_id, region_name=self.region, boto_client_config=cfg,
                                                 max_tokens=max_tokens, temperature=0.0, streaming=False)
            return self._models[key]

    def structured(self, model_id: str, system: str, prompt: str, output_model: type[T],
                   max_tokens: int = 600, attempts: int = 2) -> tuple[T, LLMUsage, int]:
        """Returns (validated output, usage, number of model invocations).

        botocore retries are switched off (max_attempts=1) so no Bedrock call is hidden. This method
        retries once itself on Nova's malformed structured-output tool call ("invalid sequence as part
        of ToolUse") and on throttling / service-unavailable errors; every attempt's tokens, latency
        and invocations are counted in the returned call count.
        """
        tot_in = tot_out = calls = 0
        ms = 0.0
        last: LLMError | None = None
        for _ in range(attempts):
            try:
                out, u, c = self._structured_once(model_id, system, prompt, output_model, max_tokens)
                tot_in, tot_out, calls, ms = tot_in + u.input_tokens, tot_out + u.output_tokens, calls + c, ms + u.latency_ms
                return out, self._usage(model_id, tot_in, tot_out, ms), calls
            except LLMError as e:
                last = e
                if e.usage:
                    tot_in, tot_out, ms = tot_in + e.usage.input_tokens, tot_out + e.usage.output_tokens, ms + e.usage.latency_ms
                calls += e.calls
                if not any(k in str(e) for k in RETRYABLE):
                    break
        raise LLMError(str(last), self._usage(model_id, tot_in, tot_out, ms), calls)

    @staticmethod
    def _usage(model_id: str, tin: int, tout: int, ms: float) -> LLMUsage:
        return LLMUsage(model_id=model_id, input_tokens=tin, output_tokens=tout, latency_ms=round(ms, 1),
                        cost_usd=cost_usd(model_id, tin, tout))

    def _structured_once(self, model_id: str, system: str, prompt: str, output_model: type[T],
                         max_tokens: int) -> tuple[T, LLMUsage, int]:
        from strands import Agent

        agent = Agent(model=self._model(model_id, max_tokens), system_prompt=system, callback_handler=None)
        t0 = time.perf_counter()
        try:
            result = agent(prompt, structured_output_model=output_model)
        except Exception as e:  # noqa: BLE001 - recorded, never hidden
            ms = (time.perf_counter() - t0) * 1000
            usage, calls = _usage_from_agent(agent, model_id, ms)
            raise LLMError(f"{type(e).__name__}: {str(e)[:300]}", usage, calls) from e
        ms = (time.perf_counter() - t0) * 1000
        u = result.metrics.accumulated_usage
        tin, tout = int(u.get("inputTokens", 0)), int(u.get("outputTokens", 0))
        usage = LLMUsage(model_id=model_id, input_tokens=tin, output_tokens=tout, latency_ms=round(ms, 1),
                         cost_usd=cost_usd(model_id, tin, tout))
        calls = max(1, int(getattr(result.metrics, "cycle_count", 1) or 1))
        out = result.structured_output
        if not isinstance(out, output_model):
            raise LLMError("structured output missing or wrong type", usage, calls)
        return out, usage, calls

    def ping(self) -> dict[str, Any]:
        """Cheapest reachability check: one tiny Nova Micro call."""
        from .policy_decision import FAST_SYSTEM, fast_prompt
        from .schemas import PolicyChoice

        text = ("The score is level at 0-0 with 1 minute left. We have the ball in our own half. Their defence "
                "is set and organised behind the ball. Our players are fresh. Objective: create a good scoring chance.")
        try:
            out, usage, _ = self.structured(settings().nova_fast_model_id, FAST_SYSTEM, fast_prompt(text), PolicyChoice, 150)
            return {"ok": True, "latency_ms": usage.latency_ms, "model_id": usage.model_id}
        except LLMError as e:
            return {"ok": False, "error": str(e)}


def _usage_from_agent(agent: Any, model_id: str, ms: float) -> tuple[LLMUsage, int]:
    try:
        m = agent.event_loop_metrics
        u = m.accumulated_usage
        tin, tout = int(u.get("inputTokens", 0)), int(u.get("outputTokens", 0))
        calls = max(1, int(m.cycle_count or 1))
    except Exception:  # noqa: BLE001
        tin = tout = 0
        calls = 1
    return LLMUsage(model_id=model_id, input_tokens=tin, output_tokens=tout, latency_ms=round(ms, 1),
                    cost_usd=cost_usd(model_id, tin, tout)), calls
