# Submission checklist — Agent Experience Hackathon: Strands Decider

Deadline: **Oct 23, 2026, 11:59 PM PDT** (Sat Oct 24, 12:29 PM IST).

- [x] Working agent: Strands Decider 2B (hosted) for the per-tick policy decision + Amazon Bedrock (Amazon Nova Micro / Pro, via Strands Agents) for fallback and plans.
- [x] Labelled reusable decision pattern: `src/matchsense/policy_decision.py` (`REUSABLE DECISION PATTERN … (#policy)`), documented in `docs/DECISION_PATTERN.md`.
- [x] Apache-2.0 `LICENSE` (full text).
- [x] Real benchmark stored in `results/real/benchmarks/` (commit the JSON/CSV you report, or paste the numbers; `results/*` is git-ignored by default).
- [ ] **You:** check `git status` shows no `.env` and run a secret scan before pushing (the key must never be committed).
- [ ] **You:** push a **public** GitHub repo.
- [ ] **You:** record the video (`docs/DEMO_VIDEO_SCRIPT.md`), under 3 minutes, upload as public.
- [ ] **You:** review and publish `docs/BUILDER_CENTER_ARTICLE.md` on AWS Builder Center; add repo and video links.
- [ ] Tags everywhere (README, article, video description): `#strands-decider-2b` and `#policy`.
- [ ] **You:** eligibility — 18+, AWS Builder Center profile, country not excluded: confirm on the official Rules page.
- [ ] **You:** submit the three links (repo, article, video) before the deadline.
