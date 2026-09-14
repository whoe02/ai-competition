# Kira — AI Money Butler

Kira is a Malaysia-first personal finance companion that turns a person's financial picture into safe, understandable daily decisions. Rather than merely listing transactions, it answers the practical question: **“What can I spend today without putting my bills, savings goals, or upcoming commitments at risk?”**

It is built as a mobile-first web app with an AI Butler, a deterministic finance engine, a KL-aware day planner, goal planning, activity tracking, and an overnight financial briefing.

> Kira never moves money. It has no bank-transfer endpoint or provider write path. Every proposed financial change stays a draft until the user reviews and confirms it.

## What Kira does

| Capability | What the user sees | What Kira does behind the scenes |
| --- | --- | --- |
| **Today** | A safe-to-spend amount, daily budget, bills, and goal progress | Calculates cash, protected commitments, goal reserves, buffers, and cycle progress from the confirmed ledger |
| **Activity** | A transparent timeline of income and spending | Keeps confirmed transactions separate from drafts, so a proposal cannot silently affect the balance |
| **AI Butler** | A conversational financial assistant | Understands a request, retrieves verified financial context, calls bounded tools, explains its answer, and creates an approval card only when a write is requested |
| **Capture** | Type, speak, or photograph an expense | Uses speech-to-text or receipt OCR when enabled, then turns the result into a reviewable draft—not an automatic transaction |
| **Daily Planner** | Nearby food and transport choices within today’s budget | Uses location when available, mapped KL places, travel estimates, preferences, and safe-to-spend limits to compare outings |
| **Goals** | A target, monthly plan, scenarios, and progress | Calculates the contribution required, shows trade-offs, protects approved goal allocations, and can suggest part-time work for a goal |
| **Foresight & hindsight** | Financial risks, possible adjustments, and Kira’s track record | Runs scenarios from the same finance engine and compares prior advice with what later happened |
| **Nightly briefing** | A morning-ready summary and proposed actions | A separate Kuala Lumpur-time worker detects relevant changes and prepares approval-gated proposals before the user opens the app |

## The core idea: AI explains, the finance engine decides

Kira intentionally separates language intelligence from financial truth.

```text
User message / voice / receipt
            │
            ▼
      AI Butler or capture adapter
            │  interprets intent; retrieves relevant context
            ▼
   Deterministic finance engine and services
            │  integer-sen arithmetic; ledger, commitments, goals, dates
            ▼
  Explanation or a reviewable approval card
            │
            ▼
      User confirms, edits, or rejects
            │
            ▼
       Audited confirmed ledger change
```

The model can help interpret a request and write a natural response. It cannot invent a balance, bypass the ledger, or commit a change by itself. Financial arithmetic uses integer sen—not floating-point values—and derives its result from the current confirmed records.

## Typical user journey

1. **Open Today.** Kira shows the money available for today after accounting for bills, goal reserves, and a buffer.
2. **Ask naturally.** The user can say, type, or photograph something such as “I spent RM18 on lunch,” “Can I afford dinner?”, or “Help me save RM10,000.”
3. **See Kira’s reasoning.** The Butler retrieves relevant information and responds with an explanation, evidence, or a proposed next step.
4. **Review the draft.** If a ledger change is needed, Kira shows a proposal. Nothing changes yet.
5. **Confirm deliberately.** The user can approve, edit, correct, discard, or reject the proposal. Only a confirmation writes to Activity and refreshes Today.
6. **Plan ahead.** The user can explore nearby places, compare options, create a goal plan, inspect future scenarios, or review the morning briefing.

## Demo-video storyboard

This is a practical 3–4 minute recording order. Keep the phone viewport visible and narrate the bold sentence for each scene.

| Time | Show on screen | Key message to say |
| --- | --- | --- |
| 0:00–0:20 | **Today** dashboard | “Kira is an AI Money Butler. It converts my current financial situation into one clear safe-to-spend figure for today.” |
| 0:20–0:45 | Today’s budget breakdown and upcoming bills/goals | “This is not just my balance. Kira protects commitments, goal money, and a buffer before it tells me what is safe.” |
| 0:45–1:25 | Open **Butler**; ask to record a realistic expense | “I can tell Kira naturally. The AI understands the request, but it prepares a draft instead of changing my money automatically.” |
| 1:25–1:45 | Approval card; edit or approve it | “I stay in control: I can review, edit, reject, or confirm. Only confirmation updates the ledger.” |
| 1:45–2:05 | Return to **Today** and **Activity** | “After confirmation, the transaction is visible in Activity and Kira recalculates today’s remaining money from the authoritative ledger.” |
| 2:05–2:35 | **Plan → Daily**; choose food/transport filters and a nearby option | “Kira helps me choose an outing that fits today’s money, using location when available and showing travel and estimated cost.” |
| 2:35–3:05 | **Plan → Goals**; open an existing goal or create one | “For a goal, Kira calculates a realistic monthly contribution and shows the trade-offs before I commit to it.” |
| 3:05–3:25 | Butler track record, foresight card, or morning briefing | “Kira looks forward with scenario planning and looks back at its own advice, so its recommendations stay accountable.” |
| 3:25–3:40 | Return to Today | “Kira does not move money. It gives me understandable choices and keeps every financial action under my approval.” |

### Suggested demo prompts

Use realistic, short requests. The exact response depends on the seeded data and current date.

```text
I spent RM18 on lunch at McDonald's
Can I afford dinner tonight?
Help me create a RM10,000 savings goal
Show me part-time work suggestions for this goal
What is putting my budget at risk this month?
```

For a clean demo, use the existing seeded account and avoid confirming a large number of transactions before recording. If you want to demonstrate an income top-up, use **+ → Manual → Received** and confirm it; a recurring salary profile forecasts income but does not itself add cash.

## Run the demo

```bash
docker compose up --build
```

Open <http://localhost:8001> and sign in with:

```text
Email:    demo@kira.app
Password: demo-money-butler
```

Kira uses the current **Asia/Kuala_Lumpur** date by default. New drafts created by Kira and newly confirmed transactions are therefore dated today.

For a reproducible historical snapshot only, pin the business date before starting Docker:

```bash
DEMO_TODAY=2026-09-03 docker compose up --build
```

That snapshot starts with RM52.97 safe to spend. Do not set `DEMO_TODAY` for a live-date demo.

If port 8001 is already in use:

```bash
KIRA_PORT=8002 docker compose up --build
```

## Demo reliability notes

- **Location:** Allow browser location permission, then tap the location chip to retry. If the device cannot provide a position, Kira uses its KL fallback and states that it is doing so.
- **Voice and receipt capture:** The Docker app uses PaddleOCR and faster-whisper. Their models download the first time the feature is used, so test each feature before recording or use typed Butler prompts for a fast offline-safe demo.
- **AI provider resilience:** The Butler uses its configured Qwen model, with a fallback and an offline stand-in if the provider is unavailable. Financial safety rules and approval gating remain in force in every mode.
- **Job suggestions:** Kira bounds and validates live job-board candidates before the model ranks them. A suggestion is informational; it never creates an application or changes financial records.
- **Date accuracy:** Kira’s backend is the authoritative business clock. Leave `DEMO_TODAY` unset for the current Kuala Lumpur date.

## Technical architecture

```text
Mobile-first React PWA (apps/web)
        │
        ▼
FastAPI API (apps/api/kira/api)
        │
        ├── Butler agent: LangGraph workflow, tool guard, streamed responses,
        │   durable conversation memory and approval interrupts
        ├── Services: the only layer allowed to write transactions, goals,
        │   commitments, approvals, and audit records
        ├── Finance engine: pure integer-sen calculations; no I/O or clock
        ├── Adapters: Qwen, OCR, speech-to-text, routing, job boards, and
        │   deterministic fakes / graceful fallbacks
        │
        ▼
PostgreSQL: ledger, goals, commitments, Butler threads, approvals, memories,
audit events, forecasts, and briefing records

Separate worker: Kuala Lumpur-time scheduled nightly briefing
```

### Safety and privacy boundaries

- No transfer endpoint and no provider write path.
- AI-generated writes are always approval-gated.
- Drafts do not change safe-to-spend or the confirmed ledger.
- The user can correct or forget Butler memories.
- The finance engine has no network/database access and uses integer sen.
- External data is bounded and has explicit fallback behavior.

## Development and verification

```bash
# API, database and worker in Docker
docker compose up -d db

# Local API
cd apps/api && .venv/bin/uvicorn kira.api.app:app --reload --port 8000

# Local web app (proxies /v1)
npm --workspace apps/web run dev

# Checks
cd apps/api && .venv/bin/pytest && .venv/bin/lint-imports
npm --workspace apps/web run test
```

For an immediate run of the same idempotent briefing path used by the nightly worker, call `POST /v1/briefings/run` after signing in.

## Repository map

- `apps/web` — React PWA and mobile interface.
- `apps/api/kira/engine` — pure financial calculations.
- `apps/api/kira/services` — business services and the only write boundary.
- `apps/api/kira/agent` — Butler graph, tools, approvals, and memory.
- `apps/api/kira/adapters` — external integrations plus deterministic fakes.
- `packages/contracts` — TypeScript contracts generated from OpenAPI.
- `docs/superpowers/specs` — architecture and design decisions.

## Further design references

- [Core architecture](docs/superpowers/specs/2026-08-24-kira-architecture-design.md)
- [Butler agent design](docs/superpowers/specs/2026-08-27-kira-butler-agent-design.md)
- [Foresight, hindsight, and nightly briefing](docs/superpowers/specs/2026-08-28-kira-foresight-hindsight-design.md)
