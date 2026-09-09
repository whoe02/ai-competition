# Kira — AI Money Butler

Turns a financial picture into safe daily decisions. Malaysia-first: money is
integer sen, the day planner knows KL.

## Run it

```bash
docker compose up --build
```

That starts both the API and a separate KL-time nightly briefing worker. You
can run the same idempotent briefing manually with `POST /v1/briefings/run`
after signing in.

Then open <http://localhost:8001> and sign in as `demo@kira.app` /
`demo-money-butler`. Today should read **RM52.97**.

If port 8001 is already in use, choose another host port, for example:

```bash
KIRA_PORT=8002 docker compose up --build
```

## Develop

```bash
docker compose up -d db
cd apps/api && .venv/bin/uvicorn kira.api.app:app --reload --port 8000
npm --workspace apps/web run dev  # http://localhost:5173, proxies /v1
```

## Receipt and voice capture

Butler supports follow-up conversation and prepares app actions for confirmation:
expense/income drafts, draft confirmation/discard/correction, recurring income,
unprotected bills, goal planning, and daily-plan entries. Every change still requires
approval. It uses the registered service actions; it does not automate arbitrary
screens or transfer money. Chat keeps the latest 40 messages as context, with
remembered preferences for longer-lived context. Shift+Enter adds a line in the
composer; Enter sends the message.

The Docker app uses PaddleOCR for receipt photos and faster-whisper for
speech-to-text. Models are downloaded the first time each is used. For a local
API process, install the optional dependencies and enable the providers in
`apps/api/.env`:

```bash
cd apps/api && .venv/bin/pip install -e '.[capture]'
```

```env
CAPTURE_OCR_PROVIDER=paddleocr
CAPTURE_OCR_LANGUAGE=en
CAPTURE_VOICE_PROVIDER=whisper
CAPTURE_VOICE_MODEL=small
CAPTURE_VOICE_LANGUAGE=en
```

Receipt reads and spoken expenses become proposals the user must save and
confirm. A spoken question is transcribed and sent directly to the Butler — it
never becomes a transaction merely because it contains an amount.

After pulling schema changes, run `cd apps/api && poetry run alembic upgrade head`.

Income is recorded separately from spending: a recurring salary profile is a
forecast, while confirmed salary/other-income transactions change cash. Kira's
goal split is deterministic and approval-gated; approved contributions are
earmarked for goals and immediately reduce Daily Planner safe-to-spend without
pretending that money was transferred out of the user's accounts.

## Check it

```bash
cd apps/api && .venv/bin/pytest && .venv/bin/lint-imports
npm --workspace apps/web run test
```

## Layout

- `apps/api/kira/engine` — pure finance math. No I/O, no clock, no float.
- `apps/api/kira/services` — the only layer that writes.
- `apps/api/kira/agent` — the Butler graph and its typed Goal-planning subgraph.
- `apps/api/kira/adapters` — every external service, behind a Protocol with a fake.
- `apps/web` — the PWA, decomposed from `kira-prototype.jsx`.
- `packages/contracts` — TypeScript types generated from the OpenAPI schema.

## Design

- Spec: [architecture design](docs/superpowers/specs/2026-08-24-kira-architecture-design.md)
- Plan: [week-one plan](docs/superpowers/plans/2026-08-24-kira-week-1-base.md)

No part of this system can move money. There is no transfer endpoint, no
provider write path, and the agent has no write tool.
