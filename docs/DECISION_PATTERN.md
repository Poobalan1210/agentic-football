# Reusable decision pattern: `#policy` — classify the state into a policy every tick

Code: [`src/matchsense/decider_gate.py`](../src/matchsense/decider_gate.py) (the Strands `InterventionHandler`,
section 6) and [`src/matchsense/policy_decision.py`](../src/matchsense/policy_decision.py) (the plain function),
both labelled `REUSABLE DECISION PATTERN`.

| Hackathon requirement | Where |
|---|---|
| The typed question and option set | `QUESTION`, `POLICY_OPTIONS` in `policy_decision.py` (section 1) |
| The wiring that puts the decision in the agent's path | `DeciderPolicyGate` in `decider_gate.py` (section 6) |
| A short note on how to use it | this file, section 7 |

## The idea

An agent loop gets a new state on every tick. Instead of asking an LLM "what now?" each time, a small
decision model classifies the state into one of a few named policies with one typed `choice` question.
The LLM is called only when the policy changes (or when the decision model is unsure).

```
state ──> state_to_text ──> Strands Decider 2B: choice(policy) ──┬─ conf ≥ T (or no helper) ─> effective policy
                                                                 └─ conf < T / error ─> Nova Pro picks from the same options
no plan yet for the effective policy? ──yes──> Nova Pro writes a new plan
                                       └─no──> keep the current plan (no Bedrock call)
```

## 1. The question and options

```python
QUESTION = "Given the current five-a-side match situation, which tactical policy should the team follow next?"
POLICY_OPTIONS = {
    "HIGH_PRESS":      "the opponent has the ball deep in their own half, far from our goal, and we press them high up the pitch to force a turnover",
    "COUNTERATTACK":   "we have just won the ball and their defence is out of position, so we attack the open space at speed",
    "KEEP_POSSESSION": "we have the ball but their defenders are in place, so we pass safely and build patiently",
    "PROTECT_LEAD":    "we are ahead near the end of the match, so we take no risks and run down the clock",
    "LOW_BLOCK":       "the opponent has the ball in our half or is breaking towards our goal, so we drop deep, protect the centre and break out with controlled transitions",
}
```

Lesson learned: write each option as **"when <condition>, so we <action>"**. Action-only definitions
("pressure the opponent high…") made Decider pick `COUNTERATTACK` for almost every state with the ball.
On a 57-state probe the condition-first wording raised agreement with the reference labels from 18/57
to 30/57; adding computed facts to the state text (below) raised it to 42/57. These were tuning runs on
a subset of the same data — see the benchmark for the reported numbers.

## 2. State schema and `state_to_text`

`MatchState` (Pydantic, `schemas.py`): score, match length, time remaining, possession and how long it
has lasted, ball, attack direction, 5 players a side (GK, DEF, MID, MID, FWD), density near the ball,
open passing options, stamina, objective, opponent pressing / low-block flags.

A 2B model is weak at geometry from coordinates, so `state_text.py` computes the geometry and writes
facts. Coordinates are rotated so we always attack the same way, so attacking left and right give
**identical** text (tested for every scenario). Example:

> The score is level at 1-1 with 1 minute 10 seconds left in a 2-minute match. We have the ball around
> the halfway line. We won the ball back just now. One opposing outfield player is between the ball and
> their goal. Their defence is out of position and there is open space in front of us. … Objective:
> exploit the open space quickly.

## 3. The Decider call

```http
POST {DECIDER_BASE_URL}/v1/decide
Authorization: Bearer <DECIDER_API_KEY>
{"state": "<state text>",
 "questions": {"policy": {"type": "choice", "instructions": QUESTION, "criteria": POLICY_OPTIONS}}}
```

Real response (recorded 2026-10-23):

```json
{"model": "strands-decider-2b-hobson-v19",
 "answers": {"policy": {"type": "choice", "choice": "COUNTERATTACK",
   "probabilities": {"HIGH_PRESS": 0.0518, "COUNTERATTACK": 0.9301, "KEEP_POSSESSION": 0.0101,
                     "PROTECT_LEAD": 0.006, "LOW_BLOCK": 0.002},
   "confidence": 0.9126}},
 "usage": {"input_tokens": 358, "output_tokens": 1}, "id": "req_…", "latency_ms": 2014.5}
```

`confidence` is the server's number (the strands-decider docs: the top probability rescaled so an even
split is 0 and certainty is 1). It is recorded as returned; if it were missing we record `None` and
fall back — we never compute our own.

## 4. Confidence gate and fallback

In MatchSense this gives two named variants: **"Decider decides"** (`FALLBACK_MODE` effectively `none`:
fastest, cheapest) and **"Decider + Nova Pro when unsure"** (`nova_pro` below the bar: most accurate).
If the helper LLM fails, Decider's own pick is used; if Decider fails too, the current tactic is kept.

Why a fallback at all? Decider always returns an answer, but on close calls its confidence says
"I'm not sure". The fallback decides what the agent does then. `FALLBACK_MODE` picks one of:
`nova_pro` (ask the strong LLM the same question — best accuracy in our runs), `nova_micro` (cheap,
but less accurate than Decider itself here, so it hurt), `hold` (keep the current tactic, no LLM call),
or `none` (always trust Decider). Decider errors/timeouts also go to the fallback.

| Situation | Effective policy | Recorded |
|---|---|---|
| `confidence ≥ CONFIDENCE_THRESHOLD` (default 0.30) | Decider's choice | raw = effective, `decided_by=decider` |
| `confidence < threshold` | Nova Micro picks from the same options, same text | raw Decider choice kept, `fallback_reason=low_confidence` |
| Decider error / timeout | Nova Micro | `fallback_reason=decider_error / decider_timeout`, raw = None |
| both fail | none (tick counts as an error / missed deadline) | both errors |

## 5. "Call the LLM only when there is no plan for the current policy"

```python
if lane.needs_plan(effective):   # plan is None or plan.policy != effective
    plan = nova_pro.write_plan(state_text, effective)   # structured TacticalPlan (Pydantic)
```

That is "re-plan when the policy changes", plus: a failed plan call is retried on the next moment,
and a plan that comes back for a different policy is rejected (`plan_valid=False`) and retried.

## 6. The wiring as a Strands `InterventionHandler`

[`src/matchsense/decider_gate.py`](../src/matchsense/decider_gate.py) puts the decision in front of any
Strands agent:

```python
planner = Agent(model=nova_pro, system_prompt=PLANNER_SYSTEM,
                interventions=[DeciderPolicyGate(decider, QUESTION, POLICY_OPTIONS, unsure_below=None)])
result = planner("Write the plan.", invocation_state={"state_text": state_text})
```

| `before_invocation` sees | Gate returns | Effect |
|---|---|---|
| Decider's policy == the policy the current plan was written for | `Deny` | agent stops before any model call (0 tokens) |
| policy changed, or the last plan call for it failed | `Transform` | "POLICY TO FOLLOW: X — definition" is prepended to the user message |
| `unsure_below` set and Decider's confidence is below it | `Transform` | the LLM is told Decider is unsure (with its ranking) and decides itself |
| Decider error / timeout | `Transform` | the LLM decides; `gate.last` is `None` (never pretends Decider answered) |

The policy is marked "planned" only in `after_model_call` when the model call raised no exception.
Real run (`scripts/gate_demo.py`, 12 moments): 2 planner calls, 10 denied before Bedrock.

## 7. How to use it in your own agent

1. Write one `choice` question and a few mutually exclusive options, each as "when [condition], so we [action]".
2. Render your state as plain sentences in code (compute geometry, counts and flags; don't make a 2B model do it).
3. Put `DeciderPolicyGate` on your Strands agent and pass the state text in `invocation_state`.
4. Measure Decider's calibration on your data (the Results tab here shows how) before setting `unsure_below`.

```python
from strands import Agent
from strands.models import BedrockModel
from matchsense.decider_client import DeciderClient   # hosted API (DECIDER_MODE=hosted) or local server
from matchsense.decider_gate import DeciderPolicyGate

QUESTION = "Which handling policy fits this support ticket?"
OPTIONS = {"self_serve": "the answer is in the docs, so we reply with a link",
           "escalate":   "money or data is at risk, so a human takes over",
           "clarify":    "the request is ambiguous, so we ask one question"}

gate = DeciderPolicyGate(DeciderClient(), QUESTION, OPTIONS, state_key="ticket_text")
agent = Agent(model=BedrockModel(model_id="us.amazon.nova-pro-v1:0"), interventions=[gate])

result = agent("Reply to the customer.", invocation_state={"ticket_text": render(ticket)})
# Same policy as last time -> denied before Bedrock (0 tokens). New policy -> the LLM writes for it.
print(gate.last_action, gate.last.choice if gate.last else None)
```

The gate sends exactly the question and options you give it; `tests/test_decider_gate.py`
(`test_reusable_with_any_question_and_options`) checks this with the options above. `render(ticket)` is
your own state-to-sentences function.

If you are not using Strands Agents, `decide_policy()` in `policy_decision.py` gives the same decision as
a plain function, but it reads the module's `QUESTION` / `POLICY_OPTIONS`, so copy the module and change
those two constants.
