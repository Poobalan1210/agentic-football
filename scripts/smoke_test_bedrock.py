"""Real Nova calls: Nova Micro policy choice and Nova Pro tactical plan, structured output."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matchsense.bedrock_client import LLMError  # noqa: E402
from matchsense.scenarios import scenario, state_of  # noqa: E402
from matchsense.state_text import state_to_text  # noqa: E402
from matchsense.tactical_planner import NovaTactics  # noqa: E402

if __name__ == "__main__":
    t = NovaTactics()
    text = state_to_text(state_of(scenario("regain_space")))
    print("state:", text)
    try:
        choice, usage, calls = t.choose_policy(text)
        print(f"{t.fast_model_id}: {choice.model_dump_json()}\n  usage: {usage.model_dump_json()} calls={calls}")
        plan, usage, calls = t.write_plan(text, choice.policy.value)
        print(f"{t.planner_model_id}: {plan.model_dump_json(indent=1)}\n  usage: {usage.model_dump_json()} calls={calls}")
    except LLMError as e:
        print("FAILED:", e)
        sys.exit(1)
