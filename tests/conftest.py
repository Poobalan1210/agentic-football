import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Tests never touch real services: mock mode, a fake key, and a temp results dir.
os.environ["APP_MODE"] = "mock"
os.environ["DECIDER_API_KEY"] = "dcd_test_SECRET_never_exposed"
os.environ["DECIDER_BASE_URL"] = "https://decider.invalid"
os.environ["TICK_SECONDS"] = "0"
os.environ["DECIDER_MODE"] = "hosted"
os.environ["FALLBACK_MODE"] = "nova_micro"
os.environ["CONFIDENCE_THRESHOLD"] = "0.7"


@pytest.fixture(autouse=True)
def _results_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    from matchsense.config import settings
    from matchsense.runtime import runtime

    settings.cache_clear()
    runtime.cache_clear()
    yield
    settings.cache_clear()
    runtime.cache_clear()


@pytest.fixture
def state_dict():
    from matchsense.scenarios import scenario

    return dict(scenario("regain_space")["state"])
