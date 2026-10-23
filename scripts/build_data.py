"""Regenerate data/scenarios.json, data/reference_labels.json and data/matches/*.json."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matchsense.config import DATA_DIR  # noqa: E402
from matchsense.scenario_builder import write_all  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(write_all(DATA_DIR), indent=1))
