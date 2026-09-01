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
