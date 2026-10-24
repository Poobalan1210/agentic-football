# Architecture

```mermaid
flowchart LR
  subgraph Data
    S[data/scenarios.json<br/>56 states] --> T
    M[data/matches/*.json<br/>3 × 60 ticks] --> T
  end
  T[state_to_text] --> A & B1 & B2
  subgraph A[Our agent: A = Decider decides · A2 = + Nova Pro when unsure]
    D[Strands Decider 2B<br/>local /v1/systemone or hosted /v1/decide] --> E[tactic]
    D -->|A2 only: conf < 0.3| F[Nova Pro answers instead] --> E
    E -->|tactic changed| P[Nova Pro plan]
  end
  subgraph B1[Flow B1 — LLM decides]
    N1[Nova Micro picks policy] -->|changed| P1[Nova Pro plan]
  end
  subgraph B2[Flow B2 — naive LLM agent]
    N2[Nova Pro picks policy + writes plan, every tick]
  end
  A & B1 & B2 --> R[TickResult records] --> J[(results/real · results/mock)]
  J --> API[FastAPI + SSE] --> UI[web/ single page]
```

| Module | Role |
|---|---|
| `config.py` | settings from env / `.env`; `public()` never includes the key |
| `schemas.py` | `MatchState`, `DeciderResult`, `PolicyDecision`, `TacticalPlan`, `TickResult` |
| `state_text.py` | geometry → sentences, direction-normalised |
| `decider_client.py` | hosted Decider: `health()`, `decide_choice()`, typed errors, one keep-alive `httpx` session |
| `policy_decision.py` | the `#policy` pattern: question, options, threshold, fallback |
| `bedrock_client.py` | Strands `Agent` + `BedrockModel`, Pydantic structured output, token usage, cost |
| `tactical_planner.py` | Nova Micro chooser, Nova Pro planner, Nova Pro choose-and-plan (B2) |
| `hybrid_flow.py`, `baseline_flow.py` | our agent (A "Decider decides", A2 "+ Nova Pro when unsure") and the LLM-only baselines B1, B2 |
| `decider_gate.py` | the same pattern as a Strands `InterventionHandler` (`Deny` the planner when the policy is unchanged) |
| `replay.py` | plays a match through the lanes, same text per tick, lanes in parallel |
| `benchmark_runner.py`, `metrics.py` | trials → rows → summary, CSV/JSON |
| `persistence.py`, `jobs.py` | stored runs (real/mock folders), background jobs |
| `server.py` | API, SSE stream, static frontend |
| `mock.py` | `APP_MODE=mock` fixtures, labelled "NOT A REAL MODEL RESULT" |

Only Amazon Nova models are used on Bedrock (Nova Micro and Nova Pro, cross-region `us.` inference
profiles in us-east-1). Decider runs on the AWS User Group Madurai hosted decision cloud.

Security: the server has **no authentication** and is meant for localhost. Anyone who can reach it can
spend your Bedrock and Decider quota. Do not expose it publicly without adding auth.
