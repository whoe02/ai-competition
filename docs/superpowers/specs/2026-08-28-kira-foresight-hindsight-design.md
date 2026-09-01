# Kira — Foresight, Hindsight and the Nightly Butler: Architecture Design

Date: 2026-08-28
Status: Approved (product owner confirmed scope, sequence and packaging)
Supersedes: §13 (build order) of `2026-08-24-kira-architecture-design.md`, and
relaxes its "no worker" packaging decision.
Completes: §15 of `2026-08-27-kira-butler-agent-design.md`, which left the
goal-scenario engine unbuilt and the scenario-comparison approval card a stub.

## 1. What this builds and why

The Butler can read every module and explain any number in the app. It cannot yet
help the user *change* anything, because the projection engine the architecture
document scheduled for weeks 3–4 was never built. The approval interrupt, the
two-tier registry and the audit trail currently guard writes that amount to CRUD.

This work adds the engine and three surfaces on top of it:

- **Foresight** — a 90-day simulation from the user's own spending history,
  expressed as a probability per goal and a ranked list of the changes that move
  that probability most.
- **Hindsight** — Kira replays her own past advice against what actually happened
  and reports her record: how often she was followed, how far off she was, and
  what following her would have been worth.
- **The nightly Butler** — a real scheduled worker that runs before the user wakes
  up, records the day's advice, runs detectors, and leaves an inbox of prepared
  proposals that are one tap from approved.

Hindsight is the piece no competitor ships. It is possible only because the engine
is pure and every past answer persisted the snapshot it consumed — an accident of
good architecture turned into a product feature.

### 1.1 Non-goals

The day planner and map (architecture document week 6), CSV import, real OCR and
speech vendors, and push notification delivery. None are prerequisites for the
above and none are started here.

## 2. Decisions made

| Decision | Choice | Why |
|---|---|---|
| Probability representation | Integer basis points, 0..10000 | The engine's no-float rule holds all the way through the new work |
| Simulation method | Empirical resampling from observed daily amounts, seeded PRNG | Honest about the user's actual distribution; needs no float; reproducible, therefore golden-file testable |
| Randomness source | `engine/prng.py`, an integer xorshift64* written in the engine | `tests/engine/test_engine_purity.py` forbids the engine importing `random`. A tiny integer PRNG keeps that guardrail intact and is reproducible across Python versions, which `random`'s internals do not promise |
| Scenario comparison | Every lever re-simulated under the **same seed** | Two runs differing by noise rather than by the lever would be a lie |
| Advice provenance | A `daily_advice` row written nightly | `safe_today` is computed on read and never stored; Hindsight needs an exact record, not a reconstruction |
| Hindsight scorer | A pure function in `engine/`, not a service | Proven by golden tests before any UI exists |
| Scheduling | APScheduler `AsyncIOScheduler` with a Postgres jobstore, in a second container | Real clock, survives restarts, retries — without adding Redis or a second datastore |
| Worker image | The same image as `app`, different command | Two containers, one build |
| Proposal delivery | Rows in the existing `butler_approvals` table, `status='pending'` | The morning inbox reuses the approval machinery already built and tested |
| Fix actions in Foresight | The existing write tools (`update_goal`, `update_commitment`) | No second approval path; the write boundary stays where it is |

### 2.1 The packaging decision this reverses

`2026-08-24-kira-architecture-design.md` §2 states "Async work: None for MVP. No
Redis, no Celery, no worker" and "`docker compose up` is the whole setup". The
product owner has accepted a second container so that "Kira works while you sleep"
is genuinely true on a clock rather than triggered on app open.

The cost is contained deliberately: one extra service, built from the same image,
scheduled by a library rather than a broker, storing its jobs in the Postgres
instance that already runs. `docker compose up` remains the whole setup — it now
starts three services instead of two.

## 3. Module split and sequence

Foundation first. Each step ends with something demonstrable; the step whose
correctness is hardest to argue about — pure arithmetic, testable offline with no
vendor — lands first.

| Order | Module | Days | Blocks |
|---|---|---|---|
| M0 | Seed depth: 90 days of history | 1 | M2, M3 |
| M1 | Projection engine (`engine/projection.py`), pure | 3 | M2, M4 |
| M2 | Foresight: service, API, Butler tools, Plan screen | 4 | — |
| M4 | Nightly worker, detectors, briefing inbox | 3 | M3's data source |
| M3 | Hindsight: scoring service, API, track-record card | 2 | — |
| — | Demo script document, seed tuning, rehearsal | 2 | — |

M4 precedes M3 because the worker is what writes `daily_advice`, and Hindsight
reads it. The seed backfills the same table for history predating the worker, so
M3 is demonstrable on day one of its own build.

## 4. M0 — Seed depth

`kira/seed/demo.py` currently seeds roughly eight days of cycle-to-date spending
(from 2026-08-29). A behaviour profile built from eight days is noise, and a track
record over eight days is not a record.

The seed grows to **90 days of confirmed history** with deliberate texture:

- a weekly rhythm — groceries on Sunday around RM180, transport on weekdays;
- one large mid-month purchase per month;
- **three or four genuine overspend days**, without which Hindsight has nothing
  interesting to say;
- category and source distribution matching the existing demo entries.

It also backfills **90 `daily_advice` rows**.

**These rows must be generated by running the real engine over each historical
day's reconstructed snapshot, never hand-written.** A hand-tuned track record
would score Kira at or near 100%, which is both false and obviously false. The
seed script imports `safe_to_spend` and computes them, exactly as the worker will.

## 5. M1 — The projection engine

`apps/api/kira/engine/projection.py`. Pure: no I/O, no database session, no
`datetime.now()`. Every date arrives on the input, as in
`engine/safe_to_spend.py`. The no-float lint rule extends to this file.

### 5.1 New types in `engine/types.py`

```python
@dataclass(frozen=True, slots=True)
class DailySpendProfile:
    """Observed discretionary spend, bucketed by weekday. Integer sen only."""
    by_weekday: tuple[tuple[int, ...], ...]   # 7 tuples of observed daily totals
    lookback_days: int
    currency: str

@dataclass(frozen=True, slots=True)
class ProjectionDay:
    on: date
    opening: Money
    commitments_due: Money
    expected_spend: Money
    goal_accrual: Money
    closing: Money

@dataclass(frozen=True, slots=True)
class Projection:
    days: tuple[ProjectionDay, ...]
    p10: tuple[Money, ...]
    p50: tuple[Money, ...]
    p90: tuple[Money, ...]

@dataclass(frozen=True, slots=True)
class Simulation:
    """What a Monte Carlo run answers: the bands, and a probability per goal."""
    bands: Projection
    outlooks: tuple[GoalOutlook, ...]
    trials: int
    seed: int

@dataclass(frozen=True, slots=True)
class GoalOutlook:
    goal_id: str
    target_date: date
    probability_bp: int          # 0..10000 basis points
    median_shortfall: Money

@dataclass(frozen=True, slots=True)
class Lever:
    kind: str                    # goal_monthly | commitment_amount | daily_spend | payday
    target_id: str
    delta: Money

@dataclass(frozen=True, slots=True)
class ScenarioResult:
    lever: Lever
    outlooks: tuple[GoalOutlook, ...]
    safe_today_after: Money

@dataclass(frozen=True, slots=True)
class Driver:
    lever: Lever
    probability_bp_before: int
    probability_bp_after: int
    bp_per_ringgit: int          # the ranking key
```

`GoalInput` gains `target`, `saved` and `target_date`, all with defaults so the
existing golden fixtures and `safe_to_spend` continue to pass unchanged. The
`Goal` model gains a nullable `target_date` column (Alembic migration); a goal
without one is projected but carries no probability.

**Income.** A projection crossing a payday needs money to arrive, and neither
`Snapshot` nor `User` carries income today — `safe_to_spend` never needed it,
because it only ever looks as far as the next payday. `Snapshot` gains
`income: Money = Money.zero()` and `User` gains a `monthly_income` column.
Income lands on `next_payday` and every `cycle_days` thereafter. The default of
zero means every existing golden fixture and `safe_to_spend` itself are
untouched.

**Commitments recur.** A `CommitmentInput` carries a single due date, because
`safe_to_spend` never looks past one payday and so never had to decide. A
projection does: the engine charges each commitment every `cycle_days` across
the horizon. Charging rent once would forecast a user living rent-free for five
of the next six months — a five-figure error at a 180-day horizon, and the
reason an early build showed every goal as trivially fundable.

**How a goal is funded in the projection.** On each payday, a goal receives its
monthly contribution if the balance after that cycle's commitments covers it,
and otherwise receives what is left. A goal's probability is the share of trials
in which `saved` reaches `target` on or before `target_date`. This is a model,
and it is stated on the surface as one.

### 5.2 Functions

| Function | Contract |
|---|---|
| `project(snapshot, profile, days) -> Projection` | Deterministic median path. No randomness. Commitments land on their due dates; goals accrue daily; the balance walks forward. |
| `simulate(snapshot, profile, days, trials, seed) -> Simulation` | Monte Carlo. Each trial draws each day's discretionary spend by **integer index** into that weekday's observed amounts, via `Prng(seed)` from `engine/prng.py`. Percentile bands come from sorting integers and indexing — no float, no distributional assumption. |
| `run_scenarios(snapshot, profile, levers, seed) -> tuple[ScenarioResult, ...]` | Applies each lever to a copy of the snapshot or profile and re-simulates **under the same seed**, so results differ by the lever and not by noise. |
| `drivers(snapshot, profile, goal_id, candidates, seed) -> tuple[Driver, ...]` | Ranks candidate levers by basis points of probability gained per ringgit of change. This produces "+RM40 a month → 62% becomes 91%". |
| `score_advice(records) -> TrackRecord` | The Hindsight scorer. Pure, and tested here rather than in the service, so it is proven before any UI consumes it. |

`TrackRecord` holds: days recorded, days followed (actual ≤ advised), mean absolute
deviation, the counterfactual closing balance had every day been followed, and the
resulting change in goal probability.

### 5.3 Performance

2,000 trials × 90 days of integer arithmetic in pure Python is the one number in
this design nobody can predict from the armchair. **M1 measures it before M2 is
written.**

**Measured:** 105 ms at 2,000 trials and 26 ms at 500, over 90 days with two
goals and five commitments, on the development machine. A single forecast is
comfortably inside the budget.

**But ranking is not a single forecast.** `drivers()` re-simulates once per
candidate lever, so eleven candidates cost twelve runs — about 1.3 s at the
default trial count, which is too slow to serve. Ranking therefore runs at
`DRIVER_TRIALS = 500` (~310 ms for the same twelve), while the headline band and
probability keep the full 2,000. The trial count is a parameter precisely so the
two can differ: the band is what the user reads, and the ranking only has to get
the order right. If a `GET /v1/foresight` cannot answer in under 400 ms, the fallbacks
in order are: reduce trials to 500 (bands stay stable, the probability moves by
well under a percentage point at demo scale), then precompute the cumulative
per-weekday draws once per request rather than per trial. The trial count is a
settings value, not a literal.

## 6. M2 — Foresight

### 6.1 Services

`services/behaviour.py` — `build_profile(session, user, lookback_days=90)`:

- reads **confirmed transactions only**, so the draft invariant needs no restating;
- excludes anything matching a commitment, which the projection models explicitly —
  counting it twice would be the obvious bug here;
- buckets by weekday and returns the observed amounts as a `DailySpendProfile`.

`services/foresight.py` — assembles the snapshot via the existing `load_snapshot`,
builds the profile, calls the engine. **Nothing is cached**, exactly as
`safe_to_spend` is computed on read. There is no invalidation logic because there
is no stored derivative.

### 6.2 API

```
GET  /v1/foresight?horizon=90        bands, per-goal probability, ranked drivers
POST /v1/foresight/scenarios         compare an explicit list of levers
```

### 6.3 Butler tools

Three **read** tools in `agent/tools/foresight.py`: `project_future`,
`compare_scenarios`, `explain_probability`. Registered exactly like the existing
read tools; the agent itself does not change.

The fix a driver proposes is executed by the **existing** write tools —
`update_goal`, `update_commitment` — so it routes through the `interrupt()` and the
`butler_approvals` row already built and tested. This work adds no second approval
path and does not move the write boundary.

### 6.4 Plan screen

`apps/web/src/screens/Plan.tsx`, replacing the `Placeholder` on that tab: a
percentile fan chart over the horizon, a probability ring per goal, and a driver
card per ranked change. Each driver card carries a "let Kira do it" action that
posts into the Butler thread and surfaces the same approval card the Butler
already renders.

**Every probability is labelled with its assumption** — "based on your last 90
days" — on the surface, not in a tooltip. A probability read as a promise is a
trust failure, and the fix is honest presentation rather than a softer number.

## 7. M3 — Hindsight

### 7.1 The provenance gap

`safe_today` is computed on read and stored nowhere, and a `butler_messages` row
exists only when the user asked something. So Kira has, today, no record of what
she advised. Hindsight cannot be built on reconstruction: recomputing a past day's
advice from today's data would silently use goals and commitments as they are
*now*.

A new table closes it:

```
daily_advice(
  id, user_id, on_date,
  safe_today,          -- Money
  snapshot,            -- JSON, the exact input consumed
  source,              -- worker | seed
  created_at,
  UNIQUE (user_id, on_date)
)
```

Written nightly by the worker (§8) and backfilled by the seed (§4).

### 7.2 Scoring

`services/hindsight.py` joins `daily_advice` with that day's actual confirmed
spend, builds `AdviceRecord` tuples, and hands them to `engine.score_advice`.
The service does no arithmetic of its own.

Output: the follow rate ("you took my number on 8 of 11 days"), the mean
deviation, and the counterfactual — "had you followed it every day you would be
RM240 ahead, and the wedding goal would sit 19 points higher".

### 7.3 Surface

`GET /v1/hindsight`. One Butler read tool, `review_my_advice`. A track-record card
at the top of the Butler screen, with the detail under More.

## 8. M4 — The nightly worker

### 8.1 Packaging

A `worker` service in `docker-compose.yml`, built from the same image as `app`
with a different command. It runs an APScheduler `AsyncIOScheduler` with a
SQLAlchemy jobstore pointed at the existing Postgres database, so scheduled jobs
survive a restart.

### 8.2 The job

`nightly_briefing(user_id, on_date)`, scheduled per user in Asia/Kuala_Lumpur.
Idempotent: the `UNIQUE (user_id, on_date)` constraint on `daily_advice` and a
matching one on the briefing row mean a second run on the same day produces no
second set of proposals.

Steps, in order:

1. load the snapshot for `on_date`;
2. write the `daily_advice` row;
3. run the detectors;
4. for each hit, write a `butler_approvals` row with `status='pending'`, its tool,
   its **validated** arguments, its summary and its evidence;
5. write one `kira` role `butler_messages` row as the briefing itself.

### 8.3 Detectors

Pure functions in `engine/detectors.py`, unit-tested in isolation:
`buffer_breach_ahead`, `goal_probability_dropped`, `unconfirmed_drafts_piling`,
`spend_pattern_anomaly`, `commitment_due_unfunded`.

### 8.4 Morning surface

A band at the top of Today — "Kira did three things last night" — opening the
inbox. Each proposal is approved through the existing
`POST /v1/butler/approvals/{id}/respond`, which is unchanged.

`POST /v1/briefings/run` triggers a run on demand. It exists so a demo is never at
the mercy of stage timing, and it is the same code path as the schedule.

## 9. Data model changes

| Table | Change |
|---|---|
| `daily_advice` | New. §7.1 |
| `briefings` | New: `user_id`, `on_date`, `summary`, `proposal_count`, unique on `(user_id, on_date)` |
| `goals` | New nullable `target_date` |
| APScheduler jobs | Created by the library in its own table, outside Alembic, like the LangGraph checkpoint tables |

All Alembic-managed except the last.

## 10. Testing

- **Golden files** for `project`, `simulate` and `score_advice`, at a fixed seed.
- **Determinism test**: the same `(snapshot, profile, seed)` simulated twice is
  equal bit for bit. This is what backs the reproducibility claim.
- **No-float lint** extended to `projection.py` and `detectors.py`.
- **Draft invariant**: an unconfirmed draft changes neither the behaviour profile
  nor any projection.
- **Double-count test**: a transaction matching a commitment appears in the
  projection once, not twice.
- **Worker idempotency**: two runs for the same `(user, date)` produce one
  `daily_advice` row and one set of proposals.
- **Write boundary**: after a worker run, every financial table is byte-identical
  and the only new rows are pending approvals, a briefing and a message.
- **Import-linter**: `engine` still imports nothing; the worker entrypoint may
  import `services`, and `api` must not import the worker.

## 11. Risks

**Simulation latency** (§5.3) — the only unquantified number in this design.
Measured in M1, with two named fallbacks. It is deliberately measured before
anything is built on top of it.

**A probability read as a promise** — mitigated by labelling the assumption on the
surface (§6.4), not by weakening the claim.

**Goal probability is close to a step function.** Contributions accrue at a
fixed daily rate that the balance almost always covers, so `saved` at the target
date barely varies between trials: the probability jumps from near 0 to near 100
across a few days of target date. The spending variance the simulation models
never reaches the goal, because the two do not compete for the same money until
the balance approaches the buffer. This is an honest limitation, not a bug, and
it is stated rather than tuned away.

The named improvement, if it proves to matter, is a **block bootstrap**:
resample whole weeks rather than independent days, so the autocorrelation in
real spending — heavy weeks follow heavy weeks — survives into the horizon
instead of averaging out. That widens the tails materially over 180 days and
would make the probability a curve rather than a step. It is deliberately not
built yet.

**Seed realism** — a hand-written track record would be transparently false. The
seed generates its advice rows with the real engine (§4). If Kira's demo track
record comes out unflatteringly low, that is a signal about the seeded behaviour,
and the seed is what changes — never the scorer.

## 12. Demo script

Both prior specs cite "the competition demo script" as the authority on scope, and
it exists nowhere in the repository. It is written down as part of this work, in
`docs/demo-script.md`, before the rehearsal step. Seed tuning aims at it.
