# Benchmark methodology and results

All numbers below come from two real runs on 2026-10-23, stored in `docs/results/` (JSON summary +
one CSV row per trial). Nothing is estimated except the cost conversion and the clearly marked
simulated threshold sweep.

## Setup

| | |
|---|---|
| Decider | `strands-decider-2b-hobson-v19`, AWS User Group Madurai hosted API (`/v1/decide`, CloudFront), called from a laptop in India |
| Bedrock | us-east-1, `us.amazon.nova-micro-v1:0` (fast chooser / fallback), `us.amazon.nova-pro-v1:0` (planner), Strands Agents 1.62.0, structured output, temperature 0 |
| Flows | **A** "Decider decides": Decider's pick every tick; Nova Pro plans on tactic change. **A2** "Decider + Nova Pro when unsure" (run 4 only): below the bar Nova Pro answers instead. **B1**: Nova Micro decides every tick, Nova Pro plans on change. **B2**: Nova Pro decides and writes the plan every tick. In runs 1–3 there was a single "hybrid" flow A with a fallback (Nova Micro in runs 1–2, Nova Pro in run 3) that also re-planned after each fallback; the tables for those runs use that older meaning of A. |
| Same input | every flow gets the identical state text for the item; the three flows run concurrently per item |
| Deadline | 1.0 s per decision (the Agentic Football Cup contract). Decision latency = time to an effective policy, including any fallback call |
| Trials | 1 per item (time-boxed). Run-to-run variance was not measured |

## Data and labels

- `variants` suite: 8 base scenarios + 48 generated variants (score, time, possession, fatigue, density, attack direction). 55 labelled, 1 ambiguous.
- `matches` suite: 3 scripted matches × 60 ticks (2 s per tick), 173 labelled ticks, 7 ambiguous.
- Reference labels come from an explicit, written rule (`scenarios.reference_policy`) with a one-line reason per item. **They are evaluation references, not objective truth**; ambiguous situations are left unlabelled and excluded from accuracy. Matches are scripted state sequences, not a game engine.

## Tuning history (honest record)

1. Option wording and state text were tuned on a 57-state probe drawn from these same datasets (raw Decider 18/57 → 30/57 → 42/57). This overlaps the evaluation data, so treat raw Decider accuracy as optimistic.
2. **Run 1** (threshold 0.70, both suites, `bench_cli_20261023_191933`): Decider's confidence was below 0.70 on 91% of items, so the hybrid mostly ran Nova Micro. Nova Micro also failed structured output 20 times (malformed tool use; max-token cutoff at 150 tokens).
3. Fixes: Nova Micro token cap raised to 400; one retry on Nova's "invalid sequence as part of ToolUse" error (retries are counted as calls and tokens). Threshold chosen from the **simulated sweep on the variants split only**: 0.30 (80.0% simulated on variants).
4. **Run 2** (threshold 0.30, `matches` suite only, `bench_cli_20261023_194954`): the reported held-out split. This is the headline.

## Run 5 (final headline) — after the fixes, both suites

`bench_cli_20261024_023923` (2026-10-24), same setup as run 4 (local Decider v19 on MLX, Nova Pro / Micro
on Bedrock us-east-1, threshold 0.30), with the fixes below: re-plan when there is no plan for the current
tactic, wrong-tactic plans rejected, botocore retries off. 944 trial rows, 0 errors, all plans valid.

Scripted matches (180 moments, 173 labelled):

| | **Decider decides** | **Decider + Nova Pro when unsure** | Nova Micro decides every moment | Nova Pro decides + plans every moment |
|---|---|---|---|---|
| Right tactic (n=173) | 69.4% | **82.1%** | 48.6% | 79.2% |
| Decision time p50 / p95 | **0.37 s** / 0.78 s | 0.76 s / 2.50 s | 1.01 s / 1.19 s | 3.98 s / 5.01 s |
| Decided within 1 s | **100%** | 53% | 42% | 0% |
| Bedrock calls / match | **15.7** | 44.7 | 79.3 | 60.7 |
| Bedrock cost / match | **$0.036** | $0.068 | $0.048 | $0.154 |
| Errors / incomplete | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Scenarios (56, 55 labelled; one decision each, no per-match numbers): accuracy Decider 74.5%,
Decider + Nova Pro 81.8%, Nova Micro 45.5%, Nova Pro 65.5%; decision p50 0.39 s / 0.69 s / 1.01 s / 3.92 s.

Compared with run 4 on the same matches: Decider's answers were the same (69.4%); "+ Nova Pro" 82.1% vs
80.3% (Nova Pro's answers vary run to run); Nova Pro alone 79.2% both times.

## Fixes made after run 4

- A plan is now (re)written whenever there is no plan for the current tactic, not only when the tactic
  changes, so a failed plan call is retried next moment; a plan written for the wrong tactic is rejected.
  Run 4 had 0 plan errors and 100% valid plans in every flow, so its numbers are unaffected.
- The code default threshold is now 0.30 (was 0.70), matching `.env.example` and the reported runs.

## Run 4 (headline) — the two variants of our agent vs two LLM-only agents

`bench_cli_20261023_233703`, scripted matches, Decider v19 local (MLX, Apple M4), threshold 0.30.
Changes since run 3: the agent comes in two named variants; Nova Pro re-plans **only** when the tactic
changes (no longer also after every hand-over); if Nova Pro fails on a handed-over tick, Decider's own
pick is used.

| Metric | A Decider decides | A2 Decider + Nova Pro when unsure | B1 Nova Micro | B2 Nova Pro |
|---|---|---|---|---|
| Accuracy (n=173) | 69.4% | **80.3%** | 48.5% | 79.2% |
| Decided by | Decider 180 | Decider 96, Nova Pro 84 | — | — |
| Decision latency p50 / p95 | 419 / 817 ms | 969 / 2587 ms | 991 / 1257 ms | 4087 / 6400 ms |
| Deadline-miss rate (1 s, n=180) | 1.7% | 50.0% | 45.0% | 100% |
| Bedrock calls / match (n=3) | 15.3 | 44.7 | 78.3 | 60.3 |
| Nova Pro plan calls / match | 15.0 | 16.0 | 18.3 | 60.0 |
| Bedrock cost / match | $0.035 | $0.068 | $0.045 | $0.153 |
| Errors / incomplete | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Notes: A and A2 queried the same local Decider at the same time each tick, so A2's Decider latency
(p50 668 ms) includes queueing behind A's request. A2 scored 82.7% in run 3 and 80.3% here on the same
ticks; the Decider answers were identical, so the difference is run-to-run variation in Nova Pro's
answers on the handed-over ticks (and run 3 also re-planned after each hand-over).

## Run 3 — local Decider, Nova Pro fallback, scripted matches

`bench_cli_20261023_210105`. Decider v19 served locally with `strands-decider serve --device mlx` on an
Apple M4 (16 GB); answers matched the hosted API (same choice, confidence within ±0.01 on 6 spot checks).
`FALLBACK_MODE=nova_pro`, threshold 0.30. Both were chosen by re-scoring recorded run-1 answers on the
**variants** split (Nova Pro fallback 80.4% vs Nova Micro 71.4% vs no fallback 73.2% at 0.30).

| Metric | A Hybrid | B1 Nova Micro | B2 Nova Pro |
|---|---|---|---|
| Accuracy (n=173) | **82.7%** | 48.5% | 80.9% |
| Raw Decider accuracy | 69.4% | — | — |
| Decided by | Decider 96 ticks, Nova Pro 84 | — | — |
| Decision latency p50 / p95 | 501 / 2254 ms | 1002 / 1179 ms | 4083 / 5150 ms |
| Decider latency p50 / p95 | 355 / 579 ms | — | — |
| Deadline-miss rate (1 s) | 46.7% (all on Nova fallback ticks) | 51.7% | 100% |
| Bedrock calls / match | 62.3 | 78.3 | 60.3 |
| Bedrock cost / match | $0.109 | $0.045 | $0.153 |
| Errors | 0 | 0 | 0 |

Run-to-run note: B1 and B2 were re-run here; B2 scored 80.9% (run 2: 79.2%), B1 48.5% both times.

## Run 2 — hosted Decider, Nova Micro fallback, scripted matches, threshold 0.30

| Metric | A Hybrid | B1 Nova Micro | B2 Nova Pro |
|---|---|---|---|
| Accuracy vs reference (n=173) | **67.0%** | 48.5% | **79.2%** |
| Raw Decider accuracy (n=173) | 69.4% | — | — |
| Fallback rate (n=180) | 46.7% (83 low confidence, 1 timeout) | — | — |
| Decision latency p50 / p95 | 2802 / 4106 ms | 1006 / 1279 ms | 3946 / 5133 ms |
| Decider-only latency p50 / p95 (client) | 2406 / 3196 ms (server p50 1967 ms) | — | — |
| Deadline-miss rate (1 s, n=180) | 100% | 52.8% | 100% |
| Bedrock calls per match (n=3) | 62.0 | 79.3 | 60.3 |
| Nova Pro plan calls per match | 33.7 | 18.3 | 60.0 |
| Bedrock cost per match | $0.080 | $0.047 | $0.152 |
| Bedrock cost per 1,000 decisions | $1.33 | $0.78 | $2.53 |
| Plan-schema valid rate | 100% (n=101) | 100% (n=55) | 100% (n=180) |
| Errors / incomplete | 0 / 0 | 0 / 0 | 0 / 0 |

Agreement: A–B1 66.7%, A–B2 65.6%, B1–B2 58.9% (n=180 each).

### Run 1 for comparison (threshold 0.70, both suites, n=228 labelled)

Hybrid 44.7%, raw Decider 70.6%, B1 44.3%, B2 77.6%; hybrid fallback 90.7%; per match Bedrock calls
A 111.7 / B1 81.7 / B2 60.7, cost A $0.126 / B1 $0.046 / B2 $0.154; 20 Nova Micro errors in each of A and B1.

### Calibration (run 2, raw Decider, matches)

| Decider confidence | 0–0.2 | 0.2–0.4 | 0.4–0.6 | 0.6–0.7 | 0.8–0.9 | 0.9–1.0 |
|---|---|---|---|---|---|---|
| Accuracy | 33.3% (n=39) | 80.0% (n=65) | 82.9% (n=41) | 50.0% (n=12) | 100% (n=13) | 100% (n=2) |

Decider's confidence on this task is mostly low (the five options are close), but very low confidence
(< 0.2) does separate the bad answers. Simulated sweep on run 2 (Nova Micro answers recorded in the
same run): threshold 0 → 69.8%, 0.2 → 70.3%, 0.3 → 66.9% (actual run: 67.0%), 0.7 → 48.3% (n=172).

## What this shows (and what it does not)

- **Decision quality:** Decider 2B (69.4% raw) beat Nova Micro (48.5%) on the same question and text, and was below Nova Pro (79.2%). Nova Micro as the fallback *lowers* hybrid accuracy; a lower threshold or a better fallback model would help.
- **Cost:** the hybrid cut Bedrock cost per match by 47% versus the naive Nova Pro agent ($0.080 vs $0.152). It did **not** cut the number of Bedrock calls (62 vs 60) at this threshold, because fallbacks and policy flips add calls; the saving comes from cheap Micro calls replacing Pro calls. B1 is cheaper still.
- **Latency:** the hosted Decider did not meet the 1-second deadline: 2.4 s client-side p50 (≈2.0 s server-reported, plus network from India to the CloudFront endpoint). It queues concurrent requests (8 parallel calls timed out at 5 s). Nova Micro alone was the fastest flow (p50 1.0 s). A Decider hosted close to the agent (or local) is required for the 2-s/1-s football contract; we have not measured that here.
- **Not included:** hosted Decider cost (no real figure; it is not zero). Single trial; no confidence intervals; labels are ours.

## Cost assumptions

USD per 1M tokens, Amazon Bedrock on-demand, us-east-1: Nova Micro $0.035 in / $0.14 out; Nova Pro
$0.80 in / $3.20 out. Official page https://aws.amazon.com/bedrock/pricing/ (prices load dynamically
and could not be machine-read on 2026-10-23); values match the hackathon kit's table ("October 2026"),
https://models.litellm.ai/models/nova-micro (as of 2026-10-19) and an AWS ML blog table for Nova Pro.
Retrieved 2026-10-23. Token counts are the Strands SDK's `accumulated_usage`.

## Missing data and timeouts

Decider timeout 5 s; Bedrock read timeout 20 s. During runs 1–4 botocore was allowed one silent
retry (max_attempts=2) that is not visible in "Bedrock calls"; it is now off (max_attempts=1) and the
client retries once itself on malformed structured output or throttling, counting every attempt. A failed decision is recorded with
its error, counted as incomplete and as wrong for accuracy, and as a missed deadline. Mock results live
in `results/mock/` and are rejected by `summarize()` if mixed with real rows.

Reproduce: `python scripts/run_benchmark.py --suites variants matches` (≈28 min, ≈$0.85 of Bedrock).
