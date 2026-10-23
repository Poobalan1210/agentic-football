# Reusable decision pattern: `#policy` — classify the state into a policy every tick

Code: [`src/matchsense/policy_decision.py`](../src/matchsense/policy_decision.py) (labelled `REUSABLE DECISION PATTERN`).

## The idea

An agent loop gets a new state on every tick. Instead of asking an LLM "what now?" each time, a small
decision model classifies the state into one of a few named policies with one typed `choice` question.
The LLM is called only when the policy changes (or when the decision model is unsure).

```
state ──> state_to_text ──> Strands Decider 2B: choice(policy) ──┬─ conf ≥ T ─> effective policy
                                                                 └─ conf < T / error ─> Nova Micro picks from the same options
effective policy changed (or fallback fired)? ──yes──> Nova Pro writes a new plan
                                               └─no──> keep the current plan
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
| `confidence ≥ CONFIDENCE_THRESHOLD` (0.70) | Decider's choice | raw = effective, `decided_by=decider` |
| `confidence < threshold` | Nova Micro picks from the same options, same text | raw Decider choice kept, `fallback_reason=low_confidence` |
| Decider error / timeout | Nova Micro | `fallback_reason=decider_error / decider_timeout`, raw = None |
| both fail | none (tick counts as an error / missed deadline) | both errors |

## 5. "Call the LLM only on change"

```python
if effective != active_policy or decision.fallback:
    plan = nova_pro.write_plan(state_text, effective)   # structured TacticalPlan (Pydantic)
```

## 6. Copy-paste version for another agent

```python
from matchsense.decider_client import DeciderClient          # or the kit's decider_kit.Decider
from matchsense.policy_decision import decide_policy

QUESTION = "Which handling policy fits this support ticket?"
POLICY_OPTIONS = {"self_serve": "the answer is in the docs, so we reply with a link",
                  "escalate":   "money or data is at risk, so a human takes over",
                  "clarify":    "the request is ambiguous, so we ask one question"}

decision, bedrock_calls = decide_policy(render(ticket), DeciderClient(), my_llm_fallback, threshold=0.7)
if decision.effective_policy != current_policy or decision.fallback:
    plan = my_llm.write_plan(render(ticket), decision.effective_policy)
```

(`decide_policy` takes the question and options from the module constants; for another domain, copy
the module and change `QUESTION` / `POLICY_OPTIONS`.)
