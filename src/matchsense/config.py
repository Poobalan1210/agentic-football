"""Settings, read only from environment variables (a local `.env` is loaded first, never overriding).

The Decider API key is held here and never logged or returned by the API; use `Settings.public()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"


def load_dotenv(path: Path | None = None) -> None:
    """Minimal KEY=VALUE reader. Existing environment variables always win."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


@dataclass(frozen=True)
class Settings:
    app_mode: str
    decider_mode: str          # hosted | local
    decider_base_url: str
    decider_local_url: str
    fallback_mode: str         # nova_micro | nova_pro | hold | none  (what to do when Decider is unsure)
    decider_api_key: str
    decider_auth_header: str
    decider_model_id: str
    decider_timeout_s: float
    aws_profile: str
    aws_region: str
    nova_planner_model_id: str
    nova_fast_model_id: str
    bedrock_timeout_s: float
    confidence_threshold: float
    tick_seconds: float
    decision_deadline_s: float
    results_dir: Path

    def public(self) -> dict:
        """Everything safe to show in the UI. Never includes the API key."""
        return {
            "app_mode": self.app_mode,
            "decider_mode": self.decider_mode,
            "decider_base_url": self.decider_local_url if self.decider_mode == "local" else self.decider_base_url,
            "fallback_mode": self.fallback_mode,
            "decider_model_id": self.decider_model_id,
            "decider_api_key_set": bool(self.decider_api_key),
            "decider_timeout_s": self.decider_timeout_s,
            "aws_region": self.aws_region,
            "nova_planner_model_id": self.nova_planner_model_id,
            "nova_fast_model_id": self.nova_fast_model_id,
            "confidence_threshold": self.confidence_threshold,
            "tick_seconds": self.tick_seconds,
            "decision_deadline_s": self.decision_deadline_s,
        }


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@lru_cache(maxsize=1)
def settings() -> Settings:
    load_dotenv()
    if os.environ.get("AWS_PROFILE", None) == "":
        os.environ.pop("AWS_PROFILE")  # an empty profile name breaks boto3; fall back to default credentials
    mode = os.environ.get("APP_MODE", "real").strip().lower()
    if mode not in ("real", "mock"):
        mode = "real"
    rd = Path(os.environ.get("RESULTS_DIR", "results"))
    dmode = os.environ.get("DECIDER_MODE", "hosted").strip().lower()
    fmode = os.environ.get("FALLBACK_MODE", "nova_pro").strip().lower()
    return Settings(
        app_mode=mode,
        decider_mode=dmode if dmode in ("hosted", "local") else "hosted",
        decider_local_url=os.environ.get("DECIDER_LOCAL_URL", "http://127.0.0.1:8099").rstrip("/"),
        fallback_mode=fmode if fmode in ("nova_micro", "nova_pro", "hold", "none") else "nova_pro",
        decider_base_url=os.environ.get("DECIDER_BASE_URL", "").rstrip("/"),
        decider_api_key=os.environ.get("DECIDER_API_KEY", ""),
        decider_auth_header=os.environ.get("DECIDER_AUTH_HEADER", "Authorization"),
        decider_model_id=os.environ.get("DECIDER_MODEL_ID", ""),
        decider_timeout_s=_f("DECIDER_TIMEOUT_S", 5.0),
        aws_profile=os.environ.get("AWS_PROFILE", ""),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        nova_planner_model_id=os.environ.get("NOVA_PLANNER_MODEL_ID", "us.amazon.nova-pro-v1:0"),
        nova_fast_model_id=os.environ.get("NOVA_FAST_MODEL_ID", "us.amazon.nova-micro-v1:0"),
        bedrock_timeout_s=_f("BEDROCK_TIMEOUT_S", 20.0),
        confidence_threshold=_f("CONFIDENCE_THRESHOLD", 0.70),
        tick_seconds=_f("TICK_SECONDS", 2.0),
        decision_deadline_s=_f("DECISION_DEADLINE_S", 1.0),
        results_dir=rd if rd.is_absolute() else ROOT / rd,
    )
