# MatchSense — Decider watches the match, Nova speaks when tactics change

`#strands-decider-2b` `#policy`

A five-a-side football tactical agent for the **AWS Agent Experience Hackathon: Strands Decider**.
Every 2-second tick, **Strands Decider 2B** classifies the match state into one of five tactical
policies with one typed `choice` question. **Amazon Nova** (on Amazon Bedrock, via Strands Agents)
writes a tactical plan **only when the policy changes** or Decider is unsure.

Inspired by AWS's Agentic Football Cup (independent of it: no game engine, scripted matches).
Built with the AWS User Group Madurai Strands Decider hackathon kit.

## The decision handed to Decider

> "Given the current five-a-side match situation, which tactical policy should the team follow next?"
> `HIGH_PRESS` · `COUNTERATTACK` · `KEEP_POSSESSION` · `PROTECT_LEAD` · `LOW_BLOCK`

The reusable pattern is in [`src/matchsense/policy_decision.py`](src/matchsense/policy_decision.py)
(labelled `REUSABLE DECISION PATTERN`) and explained in [`docs/DECISION_PATTERN.md`](docs/DECISION_PATTERN.md).
Decider never writes text; Nova writes the plan because a plan *is* text.

```mermaid
flowchart LR
  S[match state] --> T[state_to_text]
  T --> D{Decider 2B<br/>choice + confidence}
  D --> E[tactic]
  D -->|"optional: under 30% sure"| M[Nova Pro decides instead] --> E
  E -->|tactic changed| P[Nova Pro writes the plan]
  T --> B1[LLM-only: Nova Micro decides] -->|changed| P1[Nova Pro plan]
  T --> B2[LLM-only: Nova Pro decides + plans every tick]
```

## Measured results (final real run, 2026-10-24, `docs/results/bench_cli_20261024_023923.json`)

Our agent comes in two variants; both use Decider for the tactic and Nova Pro for the plan (written only
when there is no plan for the current tactic). Compared with two LLM-only agents on the same 3 scripted
matches (180 moments, 173 with an answer key). Decider v19 local on an Apple M4 (MLX); Nova on Bedrock
us-east-1. The 30% bar and Nova Pro as the helper were chosen on a separate set of 56 scenarios.

| | **Decider decides** | **Decider + Nova Pro when unsure** | Nova Micro decides every moment | Nova Pro decides + plans every moment |
|---|---|---|---|---|
| Right tactic (n=173) | 69.4% | **82.1%** | 48.6% | 79.2% |
| Decision time p50 / p95 | **0.37 s** / 0.78 s | 0.76 s / 2.50 s | 1.01 s / 1.19 s | 3.98 s / 5.01 s |
| Decided within 1 s | **100%** | 53% | 42% | 0% |
| Bedrock calls / match | **15.7** | 44.7 | 79.3 | 60.7 |
| Bedrock cost / match | **$0.036** | $0.068 | $0.048 | $0.154 |
| Errors / incomplete | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

On the 56 scenarios (n=55 labelled): Decider 74.5%, Decider + Nova Pro 81.8%, Nova Micro 45.5%, Nova Pro 65.5%.

How to read it:
- **Decider decides** is the fastest and cheapest: every decision within 1 second, about a quarter of the
  Bedrock calls and ~77% lower Bedrock cost than the Nova-Pro-every-moment agent, at ~10 points lower accuracy.
- **+ Nova Pro when unsure** hands the 47% of moments where Decider is under 30% sure to Nova Pro: the most
  accurate option (82.1% vs 79.2%), with 26% fewer Bedrock calls and 56% lower cost — but those handed-over
  moments take ~2 s.
- Not included: Decider's own compute (local here; hosted is not free). Through the hosted API the same
  Decider took ~2.4 s per call (earlier run). One trial per moment; labels are ours.

## The pattern as a Strands `InterventionHandler`

[`src/matchsense/decider_gate.py`](src/matchsense/decider_gate.py) packages the decision for **any Strands agent**:

```python
from strands import Agent
from matchsense.decider_gate import DeciderPolicyGate
from matchsense.decider_client import DeciderClient
from matchsense.policy_decision import QUESTION, POLICY_OPTIONS

planner = Agent(model=nova_pro, system_prompt=PLANNER_SYSTEM,
                interventions=[DeciderPolicyGate(DeciderClient(), QUESTION, POLICY_OPTIONS)])
planner("Write the plan.", invocation_state={"state_text": state_text})
```

On every call, `before_invocation` asks Decider for the policy. If it is unchanged, the gate returns
`Deny` and the agent stops **before any Bedrock call**. If it changed, it returns `Transform` and puts
the policy at the top of the prompt. A failed plan call is retried on the next call.
Real run (`python scripts/gate_demo.py --ticks 12`, local Decider + Nova Pro): 12 moments → 2 planner
calls, **10 denied before Bedrock** (0 tokens each, ~0.3 s for the Decider check).

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env          # add DECIDER_API_KEY; AWS credentials via your normal AWS config
python scripts/build_data.py  # (re)generates data/ — already committed
python scripts/smoke_test_decider.py   # health check + real choice calls
python scripts/serve_local_decider.py  # optional: local Decider on Apple silicon (see the script for install), then DECIDER_MODE=local
python scripts/smoke_test_bedrock.py   # real Nova Micro + Nova Pro structured calls
```

Your AWS account needs Bedrock access to Amazon Nova Micro and Nova Pro in `AWS_REGION`
(`aws bedrock list-inference-profiles --region us-east-1` should list `us.amazon.nova-micro-v1:0` and
`us.amazon.nova-pro-v1:0`). Only Amazon Nova models are used.

## Run

```bash
uvicorn matchsense.server:app --reload       # http://localhost:8000
APP_MODE=mock uvicorn matchsense.server:app  # no AWS / Decider; banner: MOCK MODE — NOT A REAL MODEL RESULT
```

- **Watch** (opens first): one moment at a time — the situation, what each AI coach chose and told the BLUE team,
  Decider's confidence for all 5 tactics, right or wrong, answer time, paid LLM calls, and a running score.
  Plays a stored **real** run (labelled). "See exactly what each model received and returned" shows the raw inputs/outputs.
- **Detailed replay:** pick a match, our agent and an LLM-only baseline, **Run live** (SSE, real calls, real timing) or open a stored run.
- **Try a situation:** edit any scenario (form or drag players on the pitch) and run both coaches on the same state.
- **Benchmark:** run all flows on the same items, see metrics with n, charts, export CSV/JSON.

The server has **no authentication**; keep it on localhost (it spends your Bedrock and Decider quota).

## Test and benchmark

```bash
pytest -q                                              # 61 tests, all external services mocked
python scripts/run_benchmark.py --suites variants matches
python scripts/ui_check.py                             # headless check of the three tabs (needs playwright)
```

## Worked example (real output)

State text: *"The score is level at 1-1 with 1 minute 10 seconds left in a 2-minute match. We have the
ball around the halfway line. … One opposing outfield player is between the ball and their goal. Their
defence is out of position and there is open space in front of us. … Objective: exploit the open space quickly."*
Decider: `COUNTERATTACK`, confidence 0.913 (probabilities 0.930 / HIGH_PRESS 0.052 / …), ~2.4 s round trip.
Nova Pro then wrote one structured plan (1,260 in / 428 out tokens, $0.0024).

## Limitations

- Reference labels are rule-based and ours; scripted matches are not a simulation.
- Single trial per item; option wording was tuned on data overlapping the evaluation (see methodology).
- Hosted Decider latency (~2.4 s) is network/hosting; local MLX on an M4 was ~0.4 s. Ticks handed to Nova Pro take ~2 s.
- Plans are model-generated recommendations, not proven strategy.

## Layout

`src/matchsense/` (core) · `web/` (single page, SVG pitch, Chart.js from CDN) · `data/` · `scripts/` ·
`tests/` · `docs/` (architecture, pattern, methodology, article draft, video script, checklist, results).

License: Apache-2.0.
