"""Real run of DeciderPolicyGate on a Strands planner agent (Strands Decider 2B + Amazon Nova Pro).

    python scripts/gate_demo.py --ticks 12

Each moment calls the planner agent; the gate decides whether Bedrock is called at all.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strands import Agent  # noqa: E402
from strands.models import BedrockModel  # noqa: E402

from matchsense.config import settings  # noqa: E402
from matchsense.decider_client import DeciderClient  # noqa: E402
from matchsense.decider_gate import DeciderPolicyGate  # noqa: E402
from matchsense.policy_decision import POLICY_OPTIONS, QUESTION  # noqa: E402
from matchsense.scenarios import match  # noqa: E402
from matchsense.schemas import MatchState, TacticalPlan  # noqa: E402
from matchsense.state_text import state_to_text  # noqa: E402
from matchsense.tactical_planner import PLANNER_SYSTEM  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="m1_late_comeback")
    ap.add_argument("--ticks", type=int, default=12)
    a = ap.parse_args()
    s = settings()
    gate = DeciderPolicyGate(DeciderClient(), QUESTION, POLICY_OPTIONS)
    model = BedrockModel(model_id=s.nova_planner_model_id, region_name=s.aws_region, max_tokens=900, temperature=0.0)
    calls = tin = tout = 0
    for t in match(a.match)["ticks"][: a.ticks]:
        text = state_to_text(MatchState.model_validate(t["state"]))
        planner = Agent(model=model, system_prompt=PLANNER_SYSTEM, interventions=[gate], callback_handler=None)
        t0 = time.perf_counter()
        r = planner(f"MATCH STATE:\n{text}\n\nWrite the tactical plan for the policy above.",
                    invocation_state={"state_text": text}, structured_output_model=TacticalPlan)
        ms = (time.perf_counter() - t0) * 1000
        u = r.metrics.accumulated_usage
        tin, tout = tin + u.get("inputTokens", 0), tout + u.get("outputTokens", 0)
        calls += r.metrics.cycle_count
        d = gate.last
        plan = r.structured_output
        what = (f"PLAN written for {plan.policy.value}" if plan else str(r).strip()[:70])
        print(f"moment {t['tick'] + 1:2}: Decider {d.choice:16} conf {d.confidence:.2f} | {gate.last_action:5} | "
              f"{ms:6.0f} ms | tokens {u.get('inputTokens', 0):5}/{u.get('outputTokens', 0):4} | {what}")
    print(f"\n{a.ticks} moments: {gate.passed} planner calls, {gate.denied} denied before Bedrock "
          f"(model cycles {calls}, tokens {tin} in / {tout} out)")
