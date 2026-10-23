# Draft — "Instinct and voice: a 2B decision model watches the match, Amazon Nova speaks when tactics change"

Tags: `#strands-decider-2b` `#policy` · Repo: [repo link] · Video: [video link]

*Draft for review. Every number is from a stored run in the repo (`docs/results/`).*

## The problem

AWS's Agentic Football Cup gives every agent a decision point every 2 seconds and 1 second to answer.
The obvious build is an LLM that reads the state and says what to do — every tick. That is sixty large-model
calls for a two-minute match, most of which say "keep doing what you're doing".

I wanted to test one claim honestly: *a small decision model can re-decide the team's tactical policy
every tick, and the generative model only needs to speak when the tactics actually change.*

## Why a typed choice fits

The per-tick question is a classification: which of five policies — `HIGH_PRESS`, `COUNTERATTACK`,
`KEEP_POSSESSION`, `PROTECT_LEAD`, `LOW_BLOCK` — fits now? Strands Decider 2B answers typed questions
with calibrated probabilities in one forward pass and never writes text. That makes it the team's
*instinct*. Amazon Nova Pro is the *coach's voice*: when the policy changes, it writes a structured
plan (goalkeeper, each outfield role, immediate actions, risks, signals to reassess).

## How they cooperate

1. Code turns the match state into sentences. A 2B model is weak at geometry from coordinates, so the code
   computes "one opposing outfield player is between the ball and their goal", "their defence is out of
   position", and normalises attack direction so both halves read the same.
2. One `choice` question to Decider (`POST /v1/decide`), with each option defined.
3. If Decider's own confidence is below the threshold, Nova Micro chooses from the same options and the
   same text. Both answers are recorded.
4. Only if the effective policy changed (or a fallback fired) does Nova Pro write a new plan.

## A worked moment

Late comeback, 40 seconds left, 0–1 down. We win the ball; the state text says one defender is goal-side
and there is open space. Decider: `COUNTERATTACK`, confidence 0.868, 2.4 s round trip, zero Bedrock calls
that tick. Two ticks earlier the switch to `COUNTERATTACK` had triggered exactly one Nova Pro plan. The
naive baseline wrote a fresh Nova Pro plan on all 41 ticks up to that point.

## Lesson 1: write options as conditions

My first option definitions described actions ("pressure the opponent high up the pitch…"). Decider
picked `COUNTERATTACK` for nearly every state with the ball. Rewriting every option as *"when <condition>,
so we <action>"* and adding two computed facts to the state ("their defence is set", "they are attacking
towards our goal") took a 57-state probe from 18 to 42 correct. The model was fine; my question was vague.

## Measured findings (including where the hybrid did worse)

**Final run** (Decider v19 local on an Apple M4 via MLX; 180 ticks, 173 labelled; one trial):

| | Decider decides | Decider + Nova Pro when unsure | Nova Micro every tick | Nova Pro every tick |
|---|---|---|---|---|
| Accuracy | 69.4% | 80.3% | 48.5% | 79.2% |
| Decision p50 | 0.42 s | 0.97 s | 0.99 s | 4.09 s |
| Decided within 1 s | 98% | 50% | 55% | 0% |
| Bedrock calls / match | 15.3 | 44.7 | 78.3 | 60.3 |
| Bedrock cost / match | $0.035 | $0.068 | $0.045 | $0.153 |

Two honest options, not one magic one. Decider alone is the fast, cheap instinct: it meets the deadline and
needs a quarter of the Bedrock calls, at 10 points lower accuracy. Letting Nova Pro take the 47% of ticks where
Decider is under 30% sure matches the LLM-only agent's accuracy at under half the cost — but those ticks wait ~2 s.
Decider's confidence is what makes the hand-over possible: on its unsure ticks it was right about half the time,
on its confident ticks 85%. An LLM gives no such measured signal.

The table below is an earlier run with the hosted Decider (~2.4 s per call from India) and Nova Micro as the
helper — kept because it shows what went wrong.

Held-out split: 3 scripted matches, 180 ticks, 173 labelled by an explicit rule; threshold 0.30 chosen on
the other split. One trial.

| | Hybrid | Nova Micro decides | Nova Pro decides + plans |
|---|---|---|---|
| Accuracy vs reference | 67.0% | 48.5% | 79.2% |
| Raw Decider accuracy | 69.4% | — | — |
| Bedrock calls / match | 62.0 | 79.3 | 60.3 |
| Bedrock cost / match | $0.080 | $0.047 | $0.152 |
| Decision latency p50 | 2.80 s | 1.01 s | 3.95 s |

- Decider beat Nova Micro on the same question by ~21 points, and was ~10 points behind Nova Pro.
- The hybrid cut Bedrock cost per match by about half versus the naive Nova Pro agent — but not the call count, because Nova Micro fallbacks and policy flips add calls.
- My first run used a 0.70 threshold: Decider's confidence was below it 91% of the time on this task, so the "hybrid" was really Nova Micro, and accuracy fell to 44.7%. The calibration table showed why: on five close options the confidence is mostly low, but confidence under 0.2 is where the wrong answers cluster.
- Latency is the honest weak spot: the hosted Decider took ~2.4 s per call from my laptop (≈2.0 s server-side), so it missed a 1-second deadline on every tick. For the real football contract it must run close to the agent.
- Hosted Decider cost is not included in the cost numbers (no real figure; not zero).

## Architecture

FastAPI backend, a single HTML page with a hand-built SVG pitch, Server-Sent Events for live replays,
Strands Agents with `BedrockModel` and Pydantic structured output for every Nova call, a mock mode that
is labelled on screen and never mixed into real results. [diagram from README]

## Reuse the pattern

Question + options-as-conditions + state-to-sentences + a confidence gate + "call the LLM only on change".
The module `policy_decision.py` is about 100 lines; swap the question and options for ticket triage,
fraud review or robot modes. See `docs/DECISION_PATTERN.md`.

## Lessons learned

1. The decision model's job is narrow; make the question narrow and the options mutually exclusive.
2. Measure calibration before choosing a threshold, and choose it on a different split than you report.
3. Cheap fallbacks are not free accuracy: a weak fallback can pull the hybrid below the decision model alone.
4. Hosting decides latency. Measure where your decision model runs.

Credits: inspired by AWS's Agentic Football Cup. Built with the AWS User Group Madurai Strands Decider
hackathon kit. Strands Decider and Strands Agents are Apache-2.0.
