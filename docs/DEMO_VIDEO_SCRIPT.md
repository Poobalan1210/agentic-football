# Demo video script (target 2:40, hard limit under 3:00)

No music. Narration by you (or Amazon Polly). Record at 1280×800. Use a stored **real** run for the
replay (the label "Recorded REAL run — <timestamp>" stays visible) and say so on screen.
Fill every [number] from the benchmark screen; do not round in your favour.

| Time | Shot | Narration (paraphrase freely) |
|---|---|---|
| 0:00–0:15 | Match Replay, B2 lane counters climbing: Bedrock calls = ticks, deadline misses | "An LLM-only football agent calls the big model on every 2-second tick. Sixty ticks, sixty Nova Pro calls, and it misses the 1-second deadline [n] times." |
| 0:15–0:35 | Header + both lanes | "MatchSense splits the job. Strands Decider 2B is the instinct: one typed choice question per tick. Amazon Nova is the coach's voice: it writes a plan only when the tactics change." |
| 0:35–1:05 | Play the recorded real run at 2×; pause on a policy switch, open the Nova plan card | "Here we win the ball back with space ahead. Decider switches to COUNTERATTACK with confidence [x]. That switch — and only that — triggers one Nova Pro plan." |
| 1:05–1:20 | Point at a yellow (low-confidence) tick and the fallback flag | "When Decider is unsure, below 0.7, Nova Micro decides from the same options. Both answers are recorded." |
| 1:20–1:45 | Match Lab: pick "Defending a dangerous counterattack", Run Both on Same State, open "How #policy works" | "Same state text, both flows, side by side. Here is the exact request and the raw probabilities." |
| 1:45–2:20 | Benchmark tab with the stored real run | "Over [n] decisions: Bedrock calls per match [A] vs [B2]; cost per match [A] vs [B2]; accuracy against our reference labels [A] vs [B1] vs [B2]. Honest caveat: the hosted Decider took about [p50] ms per call, so it misses a 1-second deadline too; that is network and hosting, and it is the next thing to fix." |
| 2:20–2:40 | `docs/DECISION_PATTERN.md` on screen | "The pattern is reusable: a question, five definitions written as 'when X, so we do Y', a confidence gate, and 'call the LLM only on change'. Tags: #policy and #strands-decider-2b." |

Close on the repo URL: [repo link]. Credit: "Inspired by AWS's Agentic Football Cup. Built with the AWS
User Group Madurai Strands Decider hackathon kit."
