"""Builds the real or mock Decider / Nova pair for the configured APP_MODE (one shared instance)."""

from __future__ import annotations

import threading
from functools import lru_cache

from .baseline_flow import BASELINES
from .config import settings
from .hybrid_flow import HybridLane


class Runtime:
    def __init__(self, mode: str | None = None):
        self.mode = mode or settings().app_mode
        if self.mode == "mock":
            from .mock import MockDecider, MockTactics

            self.decider, self.tactics = MockDecider(), MockTactics()
        else:
            from .decider_client import DeciderClient
            from .tactical_planner import NovaTactics

            self.decider, self.tactics = DeciderClient(), NovaTactics()
        self._lock = threading.Lock()

    def lane(self, flow: str, threshold: float | None = None, fallback_mode: str | None = None):
        if flow == "A":   # Decider decides every tick (no fallback)
            return HybridLane(self.decider, self.tactics, self.mode, threshold=threshold, fallback_mode="none", flow="A")
        if flow == "A2":  # Decider + Nova Pro (FALLBACK_MODE) when Decider is unsure
            return HybridLane(self.decider, self.tactics, self.mode, threshold=threshold, fallback_mode=fallback_mode,
                              flow="A2")
        return BASELINES[flow](self.tactics, self.mode)


@lru_cache(maxsize=2)
def runtime(mode: str | None = None) -> Runtime:
    return Runtime(mode)
