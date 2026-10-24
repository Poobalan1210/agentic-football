# Demo video script (target 2:40, hard limit under 3:00)

No music. Narrate yourself or with Amazon Polly. Record at 1280×800 in the **Watch** tab (it plays a
stored **real** run; keep the "Recorded REAL run" label in frame). Numbers below are from
`docs/results/bench_cli_20261024_023923.json` (final run) (3 matches, 180 moments, 173 with an answer key).

| Time | Shot | Narration (paraphrase freely) |
|---|---|---|
| 0:00–0:15 | Watch tab, title "Which tactic should BLUE play right now?" | "Every 2 seconds a football agent has to pick a tactic, and it gets 1 second. Here two AI coaches answer for the blue team at the same moment." |
| 0:15–0:45 | Press Play at 2×. Point at Coach 2's red time bar and its paid-call counter | "The usual way is to ask a large model every time. Nova Pro takes about 4 seconds, misses the deadline every time, and makes a paid call every moment." |
| 0:45–1:15 | Point at Coach 1: tactic, "How sure is it?", the five probabilities | "Coach 1 is Strands Decider 2B. It doesn't write text: it answers one multiple-choice question, scores all five tactics, and tells you how sure it is — in about 0.4 seconds, with no LLM call." |
| 1:15–1:35 | Pause on a moment where the tactic changes; open the plan bubble / "view" | "Only when the tactic changes does Nova Pro write a coaching plan. That's the one moment the big model is needed." |
| 1:35–1:55 | Pause on an unsure moment (e.g. moment 12, 22% sure, wrong). Tick "Let Nova Pro help" | "When Decider is unsure it's right only about half the time — and it tells us. Tick this box and Nova Pro takes those moments instead." |
| 1:55–2:20 | Score table at the end of the match, then the Results tab | "Across three matches: Decider alone was right 69% of the time, answered every moment within a second, and needed about 16 paid calls per match. Nova Pro every moment: 79%, never within a second, 61 calls. With Nova Pro helping when unsure: 82% — the most accurate — at less than half the cost." |
| 2:20–2:40 | `src/matchsense/decider_gate.py` on screen | "The pattern is reusable: one Strands InterventionHandler. Add it to any agent, and it's denied before calling Bedrock whenever the policy hasn't changed. Tags: #strands-decider-2b and #policy." |

**Which numbers are on screen:** the Watch score table at the end of each match shows that match only.
The narration uses the 3-match totals (173 labelled moments): right tactic Decider 69.4% · Decider + Nova Pro 82.1% ·
Nova Micro 48.6% · Nova Pro 79.2%; within 1 s 100% · 53% · 42% · 0%; Bedrock calls/match 15.7 · 44.7 · 79.3 · 60.7;
cost/match $0.036 · $0.068 · $0.048 · $0.154. The **Results** tab combines matches + scenarios (228 labelled):
70.6% · 82.0% · 47.8% · 75.9% — say "across matches and scenarios" if you read numbers off that screen.

Close on the repo URL: https://github.com/Poobalan1210/agentic-football.
Credit on screen: "Inspired by AWS's Agentic Football Cup. Built with the AWS User Group Madurai Strands
Decider hackathon kit." Say once: the match is a scripted replay, answers are checked against our written
answer key, and costs are Bedrock only.
