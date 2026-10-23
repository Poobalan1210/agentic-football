"""Real Decider health check + one real choice call. Prints the actual response (never the key)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matchsense.decider_client import DeciderClient, DeciderError  # noqa: E402
from matchsense.policy_decision import POLICY_OPTIONS, QUESTION  # noqa: E402
from matchsense.scenarios import scenario, state_of  # noqa: E402
from matchsense.state_text import state_to_text  # noqa: E402

if __name__ == "__main__":
    c = DeciderClient()
    print("client:", c)
    try:
        print("health:", json.dumps(c.health()))
        text = state_to_text(state_of(scenario("regain_space")))
        print("state:", text)
        for i in range(3):
            r = c.decide_choice(text, QUESTION, POLICY_OPTIONS)
            print(f"call {i + 1}:", r.model_dump_json())
    except DeciderError as e:
        print(f"FAILED ({e.kind}): {e}")
        sys.exit(1)
