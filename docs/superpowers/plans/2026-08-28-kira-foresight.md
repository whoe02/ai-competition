# Kira Foresight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Kira a projection engine and a 90-day probabilistic forecast, so the Butler can propose changes to a user's plan rather than only explain it.

**Architecture:** A new pure module `kira/engine/projection.py` walks a `Snapshot` forward day by day, resamples the user's own observed daily spending with a deterministic in-engine integer PRNG, and reports percentile balance bands plus a probability per goal. A service layer derives the spending profile from confirmed transactions and hands it to the engine; a read-only API and three read-only Butler tools expose it; a Plan screen renders it. Nothing here writes financial state — proposed fixes are executed by the write tools and approval interrupt that already exist.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, pytest; React 19 + Vite + TypeScript, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-28-kira-foresight-hindsight-design.md`

## Scope of this plan

The spec covers five modules. This plan implements **M0 (seed depth), M1 (projection engine) and M2 (Foresight)** — together a complete, demonstrable product increment: the app forecasts, states a probability, and proposes ranked fixes through the existing approval flow.

**M4 (nightly worker) and M3 (Hindsight) get their own plan**, written after Task 6 of this one. That is not a deferral of scope but a sequencing fact: M4's task detail depends on the simulation latency measured in Task 6 (spec §5.3, the one unquantified number in the design), and M3 consumes `score_advice`'s final signature from Task 8. Writing those tasks now would be writing them twice.

## Global Constraints

Copied from the spec and from the conventions the codebase already enforces. Every task's requirements implicitly include this section.

- **All money is integer sen** in a `Money` value object. Never a float, never a `/`.
- **`kira/engine/` is pure.** `tests/engine/test_engine_purity.py` fails the build on: any `float` literal or the name `float`; any `/` operator; a call to `round`, `open`, `print` or `input`; any `.today()`, `.now()` or `.utcnow()`; and any import outside stdlib, `kira.money` and `kira.engine`. **`random` is on the forbidden list** — hence the PRNG in Task 2.
- **Probabilities are integer basis points, 0..10000.** Never a percentage float.
- **Rounding** uses `kira.money.round_half_up(numerator, denominator)` — both ints, denominator positive. `Money.divide_floor(divisor)` floors.
- **Layering** (`pyproject.toml` import-linter contracts): `api → agent → services → engine`; `engine` imports nothing from `kira` but `kira.money`; `agent` must not import `api`.
- **Every existing golden fixture must still pass unchanged.** New `Snapshot` and `GoalInput` fields carry defaults for exactly this reason. `demo_baseline` must still produce `safe_today: 5297`.
- **The draft invariant holds:** only `status == 'confirmed'` transactions reach any calculation.
- **Test commands:** `cd apps/api && .venv/bin/pytest` and `.venv/bin/lint-imports`; `npm --workspace apps/web run test`.
- **Ruff:** line length 100, `select = ["E", "F", "I", "UP", "B", "ASYNC"]`.
- **Commit after every task.** Message style matches the existing log: lower-case conventional prefix, imperative, no trailing period.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `apps/api/kira/db/models.py` | `DailyAdvice` model; `User.monthly_income`; `Goal.target_date` | 1, 9 |
| `apps/api/alembic/versions/0003_foresight.py` | The three schema changes above | 1 |
| `apps/api/kira/seed/demo.py` | 90 days of textured history | 1 |
| `apps/api/kira/seed/advice.py` | Backfills `daily_advice` by running the real engine | 1 |
| `apps/api/kira/engine/prng.py` | Deterministic integer PRNG. Nothing else. | 2 |
| `apps/api/kira/engine/types.py` | Extended: profile, projection, outlook, lever, driver, track record | 3 |
| `apps/api/kira/engine/projection.py` | `project`, `simulate`, `run_scenarios`, `drivers` | 4, 5, 7 |
| `apps/api/kira/engine/advice.py` | `score_advice` — pure, proven before any UI | 8 |
| `apps/api/kira/services/behaviour.py` | Confirmed ledger → `DailySpendProfile` | 9 |
| `apps/api/kira/services/foresight.py` | Snapshot + profile → engine; no caching | 10 |
| `apps/api/kira/api/routers/foresight.py` | `GET /v1/foresight`, `POST /v1/foresight/scenarios` | 11 |
| `apps/api/kira/agent/tools/foresight.py` | Three read tools | 12 |
| `apps/web/src/screens/Plan.tsx` | Fan chart, probability rings, driver cards | 13 |

---

### Task 1: Ninety days of history, and somewhere to record advice

The seed currently holds sixteen transactions over eight days. A behaviour profile built from that is noise. This task deepens it and adds the `daily_advice` table the forecast's later track record will read — written now because the seed is what backfills it.

**Files:**
- Modify: `apps/api/kira/db/models.py` (add `DailyAdvice`; add `User.monthly_income`)
- Create: `apps/api/alembic/versions/0003_foresight.py`
- Create: `apps/api/kira/seed/history.py`
- Create: `apps/api/kira/seed/advice.py`
- Modify: `apps/api/kira/seed/demo.py`
- Test: `apps/api/tests/test_seed.py`

**Interfaces:**
- Consumes: `Money`, `Account`, `Transaction`, `TXN_CONFIRMED`, `SOURCE_*`, `seed_demo_user`, `load_snapshot`, `safe_to_spend`
- Produces:
  - `DailyAdvice` model with `user_id, on_date, safe_today: Money, snapshot: dict, source: str`, unique on `(user_id, on_date)`
  - `User.monthly_income: Money`
  - `kira.seed.history.history_entries(start: date, end: date) -> tuple[tuple[str, int, str, str, date], ...]` — the same 5-tuple shape as the existing `CONFIRMED` constant
  - `kira.seed.advice.backfill_advice(session, user, start: date, end: date) -> int` — rows written
  - `DEMO_HISTORY_START: date = date(2026, 6, 5)`

- [ ] **Step 1: Write the failing test**

In `apps/api/tests/test_seed.py`, append:

```python
from datetime import date, timedelta

from sqlalchemy import func, select

from kira.db.models import TXN_CONFIRMED, DailyAdvice, Transaction
from kira.seed.demo import DEMO_HISTORY_START, DEMO_TODAY, seed_demo_user


async def test_seed_has_ninety_days_of_confirmed_history(session):
    user = await seed_demo_user(session)
    await session.flush()

    rows = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.status == TXN_CONFIRMED,
            )
        )
    ).scalars().all()

    assert len(rows) >= 250, "a behaviour profile needs real density, not a handful of rows"
    span = max(r.occurred_on for r in rows) - min(r.occurred_on for r in rows)
    assert span >= timedelta(days=85)
    assert min(r.occurred_on for r in rows) == DEMO_HISTORY_START


async def test_seed_history_has_a_weekly_rhythm(session):
    user = await seed_demo_user(session)
    await session.flush()

    rows = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.status == TXN_CONFIRMED,
                Transaction.category == "groceries",
            )
        )
    ).scalars().all()
    sundays = [r for r in rows if r.occurred_on.weekday() == 6]
    assert len(sundays) >= 10, "Sunday groceries are the rhythm the forecast learns"


async def test_seed_backfills_one_advice_row_per_day(session):
    user = await seed_demo_user(session)
    await session.flush()

    count = (
        await session.execute(
            select(func.count()).select_from(DailyAdvice).where(DailyAdvice.user_id == user.id)
        )
    ).scalar_one()
    assert count >= 85

    row = (
        await session.execute(
            select(DailyAdvice).where(
                DailyAdvice.user_id == user.id,
                DailyAdvice.on_date == DEMO_TODAY - timedelta(days=1),
            )
        )
    ).scalar_one()
    assert row.source == "seed"
    assert row.snapshot["balance"] != 0
    assert row.safe_today.sen >= 0


async def test_advice_rows_vary_because_the_engine_computed_them(session):
    """A hand-written track record would be flat, and flatly false."""
    user = await seed_demo_user(session)
    await session.flush()

    values = (
        await session.execute(
            select(DailyAdvice.safe_today).where(DailyAdvice.user_id == user.id)
        )
    ).scalars().all()
    assert len(set(v.sen for v in values)) >= 20


async def test_seeding_twice_leaves_one_advice_row_per_day(session):
    user = await seed_demo_user(session)
    await session.flush()
    await seed_demo_user(session)
    await session.flush()

    pairs = (
        await session.execute(
            select(DailyAdvice.on_date).where(DailyAdvice.user_id == user.id)
        )
    ).scalars().all()
    assert len(pairs) == len(set(pairs))


async def test_today_headline_is_unchanged_by_the_history(session):
    """RM52.97 is the demo's headline. Deepening history must not move it."""
    from kira.engine import safe_to_spend
    from kira.services.snapshot import load_snapshot

    user = await seed_demo_user(session)
    await session.flush()
    result = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
    assert result.safe_today.sen == 5297
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/api && .venv/bin/pytest tests/test_seed.py -v`
Expected: FAIL — `ImportError: cannot import name 'DailyAdvice'`

- [ ] **Step 3: Add the model and the income column**

In `apps/api/kira/db/models.py`, add to `User` after `buffer`:

```python
    monthly_income: Mapped[Money] = mapped_column(MoneyType(), default=lambda: Money(0))
```

and add at the end of the file:

```python
ADVICE_SOURCE_WORKER = "worker"
ADVICE_SOURCE_SEED = "seed"


class DailyAdvice(Base):
    """What Kira advised on a given day, and the exact snapshot she advised it from.

    ``safe_today`` is computed on read and stored nowhere else, so without this
    row a past day's advice could only be reconstructed — and reconstruction
    would silently use today's goals and commitments.
    """

    __tablename__ = "daily_advice"
    __table_args__ = (UniqueConstraint("user_id", "on_date", name="uq_daily_advice_user_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date, index=True)
    safe_today: Mapped[Money] = mapped_column(MoneyType())
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(8), default=ADVICE_SOURCE_WORKER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

Add `UniqueConstraint` to the `from sqlalchemy import (...)` block.

- [ ] **Step 4: Write the migration**

Create `apps/api/alembic/versions/0003_foresight.py`:

```python
"""daily advice, monthly income, goal target dates

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("monthly_income", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("goals", sa.Column("target_date", sa.Date(), nullable=True))
    op.create_table(
        "daily_advice",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("safe_today", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "on_date", name="uq_daily_advice_user_date"),
    )
    op.create_index("ix_daily_advice_user_id", "daily_advice", ["user_id"])
    op.create_index("ix_daily_advice_on_date", "daily_advice", ["on_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_advice_on_date", table_name="daily_advice")
    op.drop_index("ix_daily_advice_user_id", table_name="daily_advice")
    op.drop_table("daily_advice")
    op.drop_column("goals", "target_date")
    op.drop_column("users", "monthly_income")
```

`Goal.target_date` is added to the schema here, in one migration, and mapped on the model in Task 9 where the forecast first reads it.

- [ ] **Step 5: Generate the history**

Create `apps/api/kira/seed/history.py`:

```python
"""Ninety days of textured spending, generated so the forecast has a rhythm to learn.

Deterministic: the same dates always produce the same history, so the demo's
numbers and the golden expectations move only when this file does.
"""

from __future__ import annotations

from datetime import date, timedelta

from kira.db.models import SOURCE_MANUAL, SOURCE_RECEIPT, SOURCE_VOICE

# (merchant, sen, category, source) — drawn by weekday, cycled deterministically.
WEEKDAY_PATTERN: dict[int, tuple[tuple[str, int, str, str], ...]] = {
    0: (("Grab — home to office", 1380, "transport", SOURCE_MANUAL),
        ("Economy rice — Jalan Ampang", 1150, "food", SOURCE_RECEIPT)),
    1: (("Touch 'n Go reload", 3000, "transport", SOURCE_MANUAL),
        ("Zus Coffee", 1090, "food", SOURCE_RECEIPT)),
    2: (("Nasi Kandar Pelita", 1690, "food", SOURCE_RECEIPT),
        ("Grab — office to home", 1420, "transport", SOURCE_VOICE)),
    3: (("Family Mart", 1250, "groceries", SOURCE_RECEIPT),
        ("Mixue", 890, "food", SOURCE_VOICE)),
    4: (("Village Park Restoran", 2350, "food", SOURCE_RECEIPT),
        ("GSC Mid Valley", 4200, "fun", SOURCE_MANUAL),
        ("Grab — Bangsar", 1980, "transport", SOURCE_MANUAL)),
    5: (("Petronas Setapak", 9000, "transport", SOURCE_RECEIPT),
        ("Watsons", 3560, "health", SOURCE_MANUAL)),
    6: (("Jaya Grocer", 18040, "groceries", SOURCE_RECEIPT),),
}

# Deliberate overspend days: the track record has nothing to say without them.
SPIKES: tuple[tuple[int, str, int, str, str], ...] = (
    (12, "Uniqlo Mid Valley", 21900, "shopping", SOURCE_RECEIPT),
    (33, "Apple Store — charger and case", 38900, "shopping", SOURCE_RECEIPT),
    (47, "Aida's birthday dinner", 32600, "food", SOURCE_MANUAL),
    (61, "Klinik Mediviron", 18500, "health", SOURCE_RECEIPT),
    (74, "Duit raya — family", 40000, "family", SOURCE_MANUAL),
)


def history_entries(
    start: date, end: date
) -> tuple[tuple[str, int, str, str, date], ...]:
    """Every confirmed transaction from ``start`` up to but excluding ``end``."""
    entries: list[tuple[str, int, str, str, date]] = []
    day = start
    index = 0
    while day < end:
        for merchant, sen, category, source in WEEKDAY_PATTERN[day.weekday()]:
            entries.append((merchant, sen, category, source, day))
        index += 1
        day += timedelta(days=1)

    for offset, merchant, sen, category, source in SPIKES:
        spike_day = start + timedelta(days=offset)
        if start <= spike_day < end:
            entries.append((merchant, sen, category, source, spike_day))

    return tuple(entries)
```

- [ ] **Step 6: Backfill the advice rows with the real engine**

Create `apps/api/kira/seed/advice.py`:

```python
"""Backfills what Kira would have advised on each past day.

Every row is produced by running the real engine over that day's reconstructed
snapshot. A hand-written track record would score Kira near 100%, which is both
false and obviously false.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import ADVICE_SOURCE_SEED, DailyAdvice, User
from kira.engine import safe_to_spend
from kira.services.snapshot import load_snapshot


def snapshot_json(snapshot) -> dict:
    """The exact engine input, as plain JSON, so a past answer can be re-derived."""
    return {
        "balance": snapshot.balance.sen,
        "buffer": snapshot.buffer.sen,
        "spent_today": snapshot.spent_today.sen,
        "income": snapshot.income.sen,
        "today": snapshot.today.isoformat(),
        "next_payday": snapshot.next_payday.isoformat(),
        "cycle_start": snapshot.cycle_start.isoformat(),
        "cycle_days": snapshot.cycle_days,
        "commitments": [
            {"id": c.id, "amount": c.amount.sen, "due_date": c.due_date.isoformat()}
            for c in snapshot.commitments
        ],
        "goals": [{"id": g.id, "monthly": g.monthly.sen} for g in snapshot.goals],
    }


async def backfill_advice(
    session: AsyncSession, user: User, start: date, end: date
) -> int:
    """Write one advice row per day in [start, end). Idempotent per user."""
    await session.execute(delete(DailyAdvice).where(DailyAdvice.user_id == user.id))

    written = 0
    day = start
    while day < end:
        snapshot = await load_snapshot(session, user, day)
        result = safe_to_spend(snapshot)
        session.add(
            DailyAdvice(
                user_id=user.id,
                on_date=day,
                safe_today=result.safe_today,
                snapshot=snapshot_json(snapshot),
                source=ADVICE_SOURCE_SEED,
            )
        )
        written += 1
        day += timedelta(days=1)
    return written
```

`snapshot.income` is referenced here and added to `Snapshot` in Task 3. Until then this module will raise `AttributeError`; Task 3's step order fixes that before any test consumes it. If you are executing tasks strictly in order, add `income` to `Snapshot` now — the field is specified in Task 3 Step 3 and is identical either way.

- [ ] **Step 7: Wire the history into the seed**

In `apps/api/kira/seed/demo.py`:

Add to the imports:

```python
from datetime import date, timedelta

from kira.seed.advice import backfill_advice
from kira.seed.history import history_entries
```

Add after `DEMO_CYCLE_START`:

```python
DEMO_HISTORY_START = date(2026, 6, 5)
DEMO_MONTHLY_INCOME = 650000
```

Replace the `SPENT_THIS_CYCLE` / `OPENING_BALANCE` block with:

```python
HISTORY = history_entries(DEMO_HISTORY_START, CONFIRMED[-1][4])
ALL_CONFIRMED = HISTORY + CONFIRMED

SPENT_ALL_TIME = sum(sen for _, sen, _, _, _ in ALL_CONFIRMED)
# The opening balance absorbs every confirmed row, so the derived balance — and
# therefore Today's RM52.97 — is unchanged by the history's presence.
OPENING_BALANCE = 418040 + SPENT_ALL_TIME
```

In `seed_demo_user`, set `monthly_income=Money(DEMO_MONTHLY_INCOME)` in both the create and the reset branch, iterate `ALL_CONFIRMED` where the function currently iterates `CONFIRMED`, and end the function — after the drafts are added and before the return — with:

```python
    await session.flush()
    await backfill_advice(session, user, DEMO_HISTORY_START, DEMO_TODAY)
```

Add `DailyAdvice` to the `for model in (...)` reset loop so a re-seed clears it.

- [ ] **Step 8: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/test_seed.py -v`
Expected: PASS, all six new tests. If `test_today_headline_is_unchanged_by_the_history` fails, `OPENING_BALANCE` is not absorbing the full history — check that `ALL_CONFIRMED` is what the loop iterates.

- [ ] **Step 9: Run the whole suite**

Run: `cd apps/api && .venv/bin/pytest && .venv/bin/lint-imports`
Expected: PASS. `kira.seed` imports `kira.services`, which is allowed — only `kira.engine` is forbidden from importing outward.

- [ ] **Step 10: Commit**

```bash
git add apps/api/kira/db/models.py apps/api/alembic/versions/0003_foresight.py \
        apps/api/kira/seed/ apps/api/tests/test_seed.py
git commit -m "feat: seed ninety days of history and record what Kira advised"
```

---

### Task 2: A deterministic PRNG the engine is allowed to import

`tests/engine/test_engine_purity.py` forbids `kira.engine` importing `random`. That guardrail is right and stays. The simulation gets a small integer generator instead — xorshift64*, which is reproducible across Python versions in a way `random`'s internals do not promise.

**Files:**
- Create: `apps/api/kira/engine/prng.py`
- Test: `apps/api/tests/engine/test_prng.py`

**Interfaces:**
- Produces: `Prng(seed: int)` with `.next_u64() -> int` and `.below(bound: int) -> int` returning `0 <= n < bound`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/engine/test_prng.py`:

```python
"""The simulation's randomness is a fixture, not a surprise."""

import pytest

from kira.engine.prng import Prng


def test_same_seed_gives_the_same_sequence():
    a = [Prng(42).next_u64() for _ in range(5)]
    b = [Prng(42).next_u64() for _ in range(5)]
    assert a == b


def test_different_seeds_diverge():
    assert Prng(1).next_u64() != Prng(2).next_u64()


def test_zero_seed_is_not_a_dead_generator():
    values = {Prng(0).next_u64() for _ in range(1)}
    assert values != {0}
    stream = Prng(0)
    assert len({stream.next_u64() for _ in range(20)}) == 20


def test_below_stays_in_range():
    stream = Prng(7)
    assert all(0 <= stream.below(13) < 13 for _ in range(500))


def test_below_covers_its_range():
    stream = Prng(7)
    seen = {stream.below(5) for _ in range(400)}
    assert seen == {0, 1, 2, 3, 4}


def test_below_is_roughly_uniform():
    """Rejection sampling, not modulo bias: no bucket should run away."""
    stream = Prng(99)
    counts = [0] * 10
    for _ in range(20_000):
        counts[stream.below(10)] += 1
    assert max(counts) - min(counts) < 700


def test_below_rejects_a_non_positive_bound():
    with pytest.raises(ValueError):
        Prng(1).below(0)


def test_seed_must_be_an_int():
    with pytest.raises(TypeError):
        Prng(1.5)  # noqa: F821 — a float seed is exactly what must not be accepted
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_prng.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.engine.prng'`

- [ ] **Step 3: Implement**

Create `apps/api/kira/engine/prng.py`:

```python
"""A deterministic integer generator, written here because the engine may not
import ``random``.

xorshift64* over 64-bit integers. Pure integer arithmetic, no float, no clock,
and identical on every Python version — which matters, because a golden file
records what it produced.
"""

from __future__ import annotations

_MASK = (1 << 64) - 1
_MULTIPLIER = 0x2545F4914F6CDD1D
_GOLDEN = 0x9E3779B97F4A7C15


class Prng:
    """Deterministic given its seed. Not cryptographic, and not trying to be."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an int")
        state = seed & _MASK
        # Zero is a fixed point of xorshift, so it is displaced rather than used.
        self._state = state if state else _GOLDEN

    def next_u64(self) -> int:
        x = self._state
        x ^= x >> 12
        x ^= (x << 25) & _MASK
        x ^= x >> 27
        self._state = x
        return (x * _MULTIPLIER) & _MASK

    def below(self, bound: int) -> int:
        """A uniform integer in ``[0, bound)``.

        Rejection sampling rather than a bare modulo: with a bound that does not
        divide 2**64, modulo would quietly favour the low buckets, and a biased
        simulation is worse than a slow one.
        """
        if isinstance(bound, bool) or not isinstance(bound, int):
            raise TypeError("bound must be an int")
        if bound <= 0:
            raise ValueError("bound must be positive")
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % bound
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_prng.py tests/engine/test_engine_purity.py -v`
Expected: PASS. The purity tests now also scan `prng.py` — it must contain no `/`, no float and no forbidden import.

- [ ] **Step 5: Commit**

```bash
git add apps/api/kira/engine/prng.py apps/api/tests/engine/test_prng.py
git commit -m "feat: add a deterministic integer PRNG inside the pure engine"
```

---

### Task 3: The projection's types

Plain frozen dataclasses, in the file that already holds the engine's vocabulary. Every addition to an existing type carries a default, so the six golden fixtures and `safe_to_spend` are untouched.

**Files:**
- Modify: `apps/api/kira/engine/types.py`
- Test: `apps/api/tests/engine/test_projection_types.py`

**Interfaces:**
- Produces: `DailySpendProfile`, `ProjectionDay`, `Projection`, `GoalOutlook`, `Simulation`, `Lever`, `ScenarioResult`, `Driver`; `Snapshot.income`; `GoalInput.target`, `.saved`, `.target_date`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/engine/test_projection_types.py`:

```python
"""The new vocabulary, and the promise that adding it broke nothing."""

from datetime import date

import pytest

from kira.engine.types import (
    CommitmentInput,
    DailySpendProfile,
    GoalInput,
    Lever,
    Snapshot,
)
from kira.money import Money


def test_goal_input_still_builds_from_id_and_monthly_alone():
    """Six golden fixtures construct it exactly this way."""
    goal = GoalInput("g1", Money(27000))
    assert goal.target == Money.zero()
    assert goal.saved == Money.zero()
    assert goal.target_date is None


def test_goal_input_carries_a_target_and_a_date():
    goal = GoalInput("g2", Money(52500), Money(800000), Money(329000), date(2027, 6, 1))
    assert goal.target.sen == 800000
    assert goal.target_date == date(2027, 6, 1)


def base_snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(418040),
        buffer=Money(80000),
        spent_today=Money.zero(),
        commitments=(CommitmentInput("rent", Money(120000), date(2026, 9, 5)),),
        goals=(GoalInput("g1", Money(27000)),),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_income_defaults_to_zero_so_existing_callers_are_untouched():
    assert base_snapshot().income == Money.zero()


def test_income_must_match_the_snapshot_currency():
    with pytest.raises(Exception):
        base_snapshot(income=Money(650000, "SGD"))


def test_profile_reports_whether_it_has_anything_to_say():
    empty = DailySpendProfile(by_weekday=tuple(() for _ in range(7)), lookback_days=0)
    assert empty.is_empty
    lived = DailySpendProfile(
        by_weekday=tuple((1500, 2000) for _ in range(7)), lookback_days=90
    )
    assert not lived.is_empty
    assert lived.median_for(0) == 2000


def test_profile_rejects_a_shape_that_is_not_seven_weekdays():
    with pytest.raises(ValueError):
        DailySpendProfile(by_weekday=((1500,), (1600,)), lookback_days=14)


def test_lever_kind_is_checked():
    with pytest.raises(ValueError):
        Lever(kind="sell_the_car", target_id="g1", delta=Money(1000))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_projection_types.py -v`
Expected: FAIL — `ImportError: cannot import name 'DailySpendProfile'`

- [ ] **Step 3: Extend the types**

In `apps/api/kira/engine/types.py`, replace `GoalInput` with:

```python
@dataclass(frozen=True, slots=True)
class GoalInput:
    """A savings goal. ``monthly`` is its claim on the cycle; the rest is its arc.

    ``target``, ``saved`` and ``target_date`` default to empty so that
    ``safe_to_spend`` and every golden fixture, which know only about the
    monthly claim, construct this unchanged.
    """

    id: str
    monthly: Money
    target: Money = Money(0)
    saved: Money = Money(0)
    target_date: date | None = None
```

Add `income: Money = Money(0)` as the **last** field of `Snapshot` (after `cycle_days`, so no positional caller moves), and add `self.income` to the currency check list in `__post_init__`.

Then append:

```python
@dataclass(frozen=True, slots=True)
class DailySpendProfile:
    """What this user actually spends, by weekday. Observed amounts, integer sen.

    Not a distribution fitted to the data — the data itself, resampled. A user
    with three RM200 Sundays and one RM40 Sunday should see all four futures.
    """

    by_weekday: tuple[tuple[int, ...], ...]
    lookback_days: int

    def __post_init__(self) -> None:
        if len(self.by_weekday) != 7:
            raise ValueError("by_weekday must hold one tuple per weekday")
        for amounts in self.by_weekday:
            for amount in amounts:
                if isinstance(amount, bool) or not isinstance(amount, int):
                    raise TypeError("observed amounts are integer sen")

    @property
    def is_empty(self) -> bool:
        return all(len(amounts) == 0 for amounts in self.by_weekday)

    def median_for(self, weekday: int) -> int:
        """The middle observation, upper of the two when the count is even."""
        amounts = sorted(self.by_weekday[weekday])
        if not amounts:
            return 0
        return amounts[len(amounts) // 2]


@dataclass(frozen=True, slots=True)
class ProjectionDay:
    on: date
    opening: Money
    income: Money
    commitments_due: Money
    expected_spend: Money
    goal_accrual: Money
    closing: Money


@dataclass(frozen=True, slots=True)
class Projection:
    """A path, and the band around it. ``p50`` is empty for a median-only walk."""

    days: tuple[ProjectionDay, ...]
    p10: tuple[Money, ...] = ()
    p50: tuple[Money, ...] = ()
    p90: tuple[Money, ...] = ()


@dataclass(frozen=True, slots=True)
class GoalOutlook:
    goal_id: str
    target_date: date
    probability_bp: int
    median_shortfall: Money

    def __post_init__(self) -> None:
        if not 0 <= self.probability_bp <= 10000:
            raise ValueError("probability_bp is basis points, 0..10000")


@dataclass(frozen=True, slots=True)
class Simulation:
    bands: Projection
    outlooks: tuple[GoalOutlook, ...]
    trials: int
    seed: int


LEVER_KINDS = ("goal_monthly", "commitment_amount", "daily_spend")


@dataclass(frozen=True, slots=True)
class Lever:
    """One change to the plan, expressed as a delta. Negative means less."""

    kind: str
    target_id: str
    delta: Money

    def __post_init__(self) -> None:
        if self.kind not in LEVER_KINDS:
            raise ValueError(f"lever kind must be one of {LEVER_KINDS}, got {self.kind!r}")


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    lever: Lever
    outlooks: tuple[GoalOutlook, ...]
    safe_today_after: Money


@dataclass(frozen=True, slots=True)
class Driver:
    """A ranked change: what it costs, and what it buys, in basis points."""

    lever: Lever
    probability_bp_before: int
    probability_bp_after: int
    bp_per_ringgit: int
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/engine -v`
Expected: PASS — including all six golden fixtures, unchanged.

- [ ] **Step 5: Commit**

```bash
git add apps/api/kira/engine/types.py apps/api/tests/engine/test_projection_types.py
git commit -m "feat: extend the engine's vocabulary with projections, levers and outlooks"
```

---

### Task 4: `project()` — the deterministic median path

The forecast's spine: no randomness, no probability. Walk each day forward, land the commitments on their due dates and the income on the paydays, and accrue the goals.

**Files:**
- Create: `apps/api/kira/engine/projection.py`
- Test: `apps/api/tests/engine/test_projection.py`

**Interfaces:**
- Consumes: `Snapshot`, `DailySpendProfile`, `Projection`, `ProjectionDay`, `Money`, `round_half_up`
- Produces: `project(snapshot: Snapshot, profile: DailySpendProfile, days: int) -> Projection`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/engine/test_projection.py`:

```python
"""The median walk: where the money goes if nothing surprising happens."""

from datetime import date, timedelta

import pytest

from kira.engine.projection import project
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Snapshot
from kira.money import Money

FLAT = DailySpendProfile(by_weekday=tuple((1000,) for _ in range(7)), lookback_days=90)
NOTHING = DailySpendProfile(by_weekday=tuple(() for _ in range(7)), lookback_days=0)


def snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(100000),
        buffer=Money(0),
        spent_today=Money.zero(),
        commitments=(),
        goals=(),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
        income=Money.zero(),
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_walks_one_day_per_horizon_day():
    result = project(snapshot(), FLAT, 30)
    assert len(result.days) == 30
    assert result.days[0].on == date(2026, 9, 4)
    assert result.days[-1].on == date(2026, 9, 3) + timedelta(days=30)


def test_spend_comes_off_the_balance_each_day():
    result = project(snapshot(), FLAT, 3)
    assert [d.closing.sen for d in result.days] == [99000, 98000, 97000]


def test_an_empty_profile_spends_nothing_rather_than_guessing():
    result = project(snapshot(), NOTHING, 3)
    assert [d.closing.sen for d in result.days] == [100000, 100000, 100000]


def test_a_commitment_lands_on_its_due_date_and_only_then():
    result = project(
        snapshot(commitments=(CommitmentInput("rent", Money(50000), date(2026, 9, 5)),)),
        FLAT,
        3,
    )
    assert [d.commitments_due.sen for d in result.days] == [0, 50000, 0]
    assert [d.closing.sen for d in result.days] == [99000, 48000, 47000]


def test_income_arrives_on_payday_and_every_cycle_after():
    result = project(
        snapshot(income=Money(650000), next_payday=date(2026, 9, 5)), NOTHING, 40
    )
    paid = [d.on for d in result.days if d.income.sen > 0]
    assert paid == [date(2026, 9, 5), date(2026, 10, 5)]


def test_a_commitment_before_today_is_already_paid_and_does_not_land_again():
    result = project(
        snapshot(commitments=(CommitmentInput("old", Money(50000), date(2026, 8, 30)),)),
        NOTHING,
        3,
    )
    assert all(d.commitments_due.sen == 0 for d in result.days)


def test_goals_accrue_daily_at_their_monthly_rate():
    result = project(snapshot(goals=(GoalInput("g1", Money(30000)),)), NOTHING, 3)
    assert [d.goal_accrual.sen for d in result.days] == [1000, 1000, 1000]


def test_the_walk_is_a_pure_function_of_its_inputs():
    args = (snapshot(income=Money(650000)), FLAT, 45)
    assert project(*args) == project(*args)


def test_a_horizon_must_be_positive():
    with pytest.raises(ValueError):
        project(snapshot(), FLAT, 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_projection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.engine.projection'`

- [ ] **Step 3: Implement**

Create `apps/api/kira/engine/projection.py`:

```python
"""Where the money goes next. Pure: no I/O, no clock, no float.

``project`` walks the median path. ``simulate`` (Task 5) walks it many times
with the user's own observed variation, and reports a band and a probability.
"""

from __future__ import annotations

from datetime import date, timedelta

from kira.engine.types import (
    DailySpendProfile,
    Projection,
    ProjectionDay,
    Snapshot,
)
from kira.money import Money, round_half_up


def _payday_dates(snapshot: Snapshot, days: int) -> frozenset[date]:
    """Payday, and every cycle length after it, within the horizon."""
    last = snapshot.today + timedelta(days=days)
    paydays: set[date] = set()
    when = snapshot.next_payday
    while when <= last:
        if when > snapshot.today:
            paydays.add(when)
        when += timedelta(days=snapshot.cycle_days)
    return frozenset(paydays)


def _daily_goal_accrual(snapshot: Snapshot) -> Money:
    """Each goal's monthly contribution, spread over the cycle and rounded once."""
    currency = snapshot.currency
    return Money.sum(
        (
            Money(round_half_up(goal.monthly.sen, snapshot.cycle_days), currency)
            for goal in snapshot.goals
        ),
        currency,
    )


def project(snapshot: Snapshot, profile: DailySpendProfile, days: int) -> Projection:
    """The median path over ``days`` days, starting the day after ``snapshot.today``."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError("days must be an int")
    if days <= 0:
        raise ValueError("days must be positive")

    currency = snapshot.currency
    paydays = _payday_dates(snapshot, days)
    accrual = _daily_goal_accrual(snapshot)
    due: dict[date, Money] = {}
    for commitment in snapshot.commitments:
        if commitment.due_date > snapshot.today:
            due[commitment.due_date] = due.get(
                commitment.due_date, Money.zero(currency)
            ) + commitment.amount

    walked: list[ProjectionDay] = []
    balance = snapshot.balance
    for step in range(1, days + 1):
        on = snapshot.today + timedelta(days=step)
        income = snapshot.income if on in paydays else Money.zero(currency)
        commitments_due = due.get(on, Money.zero(currency))
        spend = Money(profile.median_for(on.weekday()), currency)
        opening = balance
        balance = opening + income - commitments_due - spend
        walked.append(
            ProjectionDay(
                on=on,
                opening=opening,
                income=income,
                commitments_due=commitments_due,
                expected_spend=spend,
                goal_accrual=accrual,
                closing=balance,
            )
        )

    return Projection(days=tuple(walked))
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/engine -v`
Expected: PASS, including the purity suite over the new file.

- [ ] **Step 5: Commit**

```bash
git add apps/api/kira/engine/projection.py apps/api/tests/engine/test_projection.py
git commit -m "feat: walk the median financial path forward day by day"
```

---

### Task 5: `simulate()` — bands and a probability

Many walks, each drawing the day's spend from what this user actually spent on that weekday. The percentile bands and the per-goal probability both fall out of sorted integers.

**Files:**
- Modify: `apps/api/kira/engine/projection.py`
- Test: `apps/api/tests/engine/test_simulation.py`

**Interfaces:**
- Consumes: `Prng`, `project`, `Simulation`, `GoalOutlook`
- Produces: `simulate(snapshot, profile, days, trials=2000, seed=20260828) -> Simulation`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/engine/test_simulation.py`:

```python
"""Many futures, honestly summarised."""

from datetime import date

import pytest

from kira.engine.projection import simulate
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Snapshot
from kira.money import Money

VARIED = DailySpendProfile(
    by_weekday=tuple((500, 1500, 2500) for _ in range(7)), lookback_days=90
)
NOTHING = DailySpendProfile(by_weekday=tuple(() for _ in range(7)), lookback_days=0)


def snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(500000),
        buffer=Money(0),
        spent_today=Money.zero(),
        commitments=(),
        goals=(),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
        income=Money(650000),
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_the_same_seed_reproduces_the_run_exactly():
    a = simulate(snapshot(), VARIED, 60, trials=200, seed=7)
    b = simulate(snapshot(), VARIED, 60, trials=200, seed=7)
    assert a == b


def test_a_different_seed_gives_a_different_run():
    a = simulate(snapshot(), VARIED, 60, trials=200, seed=7)
    b = simulate(snapshot(), VARIED, 60, trials=200, seed=8)
    assert a.bands.p50 != b.bands.p50


def test_the_bands_are_ordered():
    result = simulate(snapshot(), VARIED, 60, trials=300, seed=11)
    for low, mid, high in zip(result.bands.p10, result.bands.p50, result.bands.p90):
        assert low <= mid <= high


def test_a_profile_with_no_variation_collapses_the_band_onto_the_median():
    flat = DailySpendProfile(by_weekday=tuple((1000,) for _ in range(7)), lookback_days=90)
    result = simulate(snapshot(), flat, 30, trials=100, seed=3)
    assert result.bands.p10 == result.bands.p90


def test_a_reachable_goal_is_near_certain():
    goal = GoalInput("g1", Money(50000), Money(60000), Money(50000), date(2026, 11, 1))
    result = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=200, seed=5)
    assert result.outlooks[0].probability_bp >= 9500
    assert result.outlooks[0].median_shortfall.sen == 0


def test_an_unreachable_goal_is_near_impossible():
    goal = GoalInput("g2", Money(10000), Money(900000), Money(0), date(2026, 11, 1))
    result = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=200, seed=5)
    assert result.outlooks[0].probability_bp <= 500
    assert result.outlooks[0].median_shortfall.sen > 0


def test_a_goal_without_a_target_date_gets_no_outlook():
    result = simulate(snapshot(goals=(GoalInput("g3", Money(10000)),)), NOTHING, 90,
                      trials=50, seed=5)
    assert result.outlooks == ()


def test_a_goal_beyond_the_horizon_gets_no_outlook():
    goal = GoalInput("g4", Money(10000), Money(20000), Money(0), date(2030, 1, 1))
    result = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=50, seed=5)
    assert result.outlooks == ()


def test_a_commitment_that_outruns_income_hurts_the_probability():
    goal = GoalInput("g5", Money(50000), Money(200000), Money(0), date(2026, 12, 1))
    easy = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=300, seed=13)
    squeezed = simulate(
        snapshot(
            goals=(goal,),
            commitments=(CommitmentInput("loan", Money(600000), date(2026, 9, 20)),),
        ),
        NOTHING,
        90,
        trials=300,
        seed=13,
    )
    assert squeezed.outlooks[0].probability_bp < easy.outlooks[0].probability_bp


def test_trials_must_be_positive():
    with pytest.raises(ValueError):
        simulate(snapshot(), VARIED, 30, trials=0, seed=1)


@pytest.mark.slow
def test_a_full_run_is_fast_enough_to_serve_in_a_request():
    """Spec §5.3: the one number nobody could predict from the armchair."""
    import time

    started = time.perf_counter()
    simulate(snapshot(), VARIED, 90, trials=2000, seed=1)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"2000 x 90 took {elapsed:.2f}s — see spec §5.3 fallbacks"
```

Register the marker: in `apps/api/pyproject.toml` under `[tool.pytest.ini_options]`, add

```toml
markers = ["slow: measured rather than asserted; kept in the default run deliberately"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_simulation.py -v`
Expected: FAIL — `ImportError: cannot import name 'simulate'`

- [ ] **Step 3: Implement**

Append to `apps/api/kira/engine/projection.py` — and extend the imports at the top with `GoalOutlook`, `Simulation`, `GoalInput` and `from kira.engine.prng import Prng`:

```python
DEFAULT_TRIALS = 2000
DEFAULT_SEED = 20260828

_P10, _P50, _P90 = 10, 50, 90


def _percentile(sorted_values: list[int], percentile: int) -> int:
    """The value at ``percentile`` of an ascending list, by nearest rank.

    Integer arithmetic throughout: the index is rounded half-up, never divided.
    """
    if not sorted_values:
        return 0
    last = len(sorted_values) - 1
    return sorted_values[round_half_up(percentile * last, 100)]


def _fundable_goals(snapshot: Snapshot, days: int) -> tuple[GoalInput, ...]:
    """Goals with a target date inside the horizon. Others get no probability."""
    horizon_end = snapshot.today + timedelta(days=days)
    return tuple(
        goal
        for goal in snapshot.goals
        if goal.target_date is not None and snapshot.today < goal.target_date <= horizon_end
    )


def simulate(
    snapshot: Snapshot,
    profile: DailySpendProfile,
    days: int,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
) -> Simulation:
    """Walk the horizon ``trials`` times, resampling this user's own spending.

    Each day's discretionary spend is drawn by integer index from what the user
    actually spent on that weekday — no fitted distribution, no assumption of
    symmetry, and no float anywhere in the arithmetic.
    """
    if isinstance(trials, bool) or not isinstance(trials, int):
        raise TypeError("trials must be an int")
    if trials <= 0:
        raise ValueError("trials must be positive")

    median = project(snapshot, profile, days)
    currency = snapshot.currency
    goals = _fundable_goals(snapshot, days)
    accrual_by_goal = {
        goal.id: round_half_up(goal.monthly.sen, snapshot.cycle_days) for goal in goals
    }

    closings: list[list[int]] = [[] for _ in range(days)]
    shortfalls: dict[str, list[int]] = {goal.id: [] for goal in goals}
    met: dict[str, int] = {goal.id: 0 for goal in goals}

    stream = Prng(seed)
    for _ in range(trials):
        balance = snapshot.balance.sen
        saved = {goal.id: goal.saved.sen for goal in goals}
        for index, day in enumerate(median.days):
            observed = profile.by_weekday[day.on.weekday()]
            spend = observed[stream.below(len(observed))] if observed else 0
            balance += day.income.sen - day.commitments_due.sen - spend
            for goal in goals:
                if day.on <= goal.target_date:
                    saved[goal.id] += accrual_by_goal[goal.id]
            closings[index].append(balance)

        for goal in goals:
            gap = goal.target.sen - saved[goal.id]
            if gap <= 0:
                met[goal.id] += 1
                shortfalls[goal.id].append(0)
            else:
                shortfalls[goal.id].append(gap)

    for column in closings:
        column.sort()
    for values in shortfalls.values():
        values.sort()

    bands = Projection(
        days=median.days,
        p10=tuple(Money(_percentile(c, _P10), currency) for c in closings),
        p50=tuple(Money(_percentile(c, _P50), currency) for c in closings),
        p90=tuple(Money(_percentile(c, _P90), currency) for c in closings),
    )

    outlooks = tuple(
        GoalOutlook(
            goal_id=goal.id,
            target_date=goal.target_date,
            probability_bp=round_half_up(met[goal.id] * 10000, trials),
            median_shortfall=Money(_percentile(shortfalls[goal.id], _P50), currency),
        )
        for goal in goals
    )

    return Simulation(bands=bands, outlooks=outlooks, trials=trials, seed=seed)
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/engine -v`
Expected: PASS.

- [ ] **Step 5: Record the measured latency**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_simulation.py -k fast_enough -v -s`

Write the measured number into the spec's §5.3 as a sentence — "measured at N ms on the development machine" — and commit that edit with this task. **If it exceeds 400 ms**, apply the spec's first fallback (drop `DEFAULT_TRIALS` to 500), re-measure, and record both numbers. Do not proceed to Task 6 with an unmeasured simulation.

- [ ] **Step 6: Commit**

```bash
git add apps/api/kira/engine/projection.py apps/api/tests/engine/test_simulation.py \
        apps/api/pyproject.toml docs/superpowers/specs/2026-08-28-kira-foresight-hindsight-design.md
git commit -m "feat: simulate the horizon and report bands and goal probabilities"
```

---

### Task 6: Golden files for the projection

The finance math is locked by golden files. The forecast joins it, so drift fails CI rather than a demo.

**Files:**
- Create: `apps/api/tests/engine/projection_cases/demo_90day.json`
- Create: `apps/api/tests/engine/projection_cases/tight_month.json`
- Create: `apps/api/tests/engine/test_projection_golden.py`

**Interfaces:**
- Consumes: `simulate`, `Snapshot`, `DailySpendProfile`
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write the loader and the failing test**

Create `apps/api/tests/engine/test_projection_golden.py`:

```python
"""Locks the forecast. A change to any number here must be deliberate."""

import json
from datetime import date
from pathlib import Path

import pytest

from kira.engine.projection import simulate
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Snapshot
from kira.money import Money

CASES_DIR = Path(__file__).parent / "projection_cases"
CASES = [(p.stem, json.loads(p.read_text())) for p in sorted(CASES_DIR.glob("*.json"))]


def build(spec: dict) -> tuple[Snapshot, DailySpendProfile]:
    currency = spec.get("currency", "MYR")
    snapshot = Snapshot(
        balance=Money(spec["balance"], currency),
        buffer=Money(spec["buffer"], currency),
        spent_today=Money(spec["spent_today"], currency),
        commitments=tuple(
            CommitmentInput(c["id"], Money(c["amount"], currency), date.fromisoformat(c["due_date"]))
            for c in spec["commitments"]
        ),
        goals=tuple(
            GoalInput(
                g["id"],
                Money(g["monthly"], currency),
                Money(g.get("target", 0), currency),
                Money(g.get("saved", 0), currency),
                date.fromisoformat(g["target_date"]) if g.get("target_date") else None,
            )
            for g in spec["goals"]
        ),
        today=date.fromisoformat(spec["today"]),
        next_payday=date.fromisoformat(spec["next_payday"]),
        cycle_start=date.fromisoformat(spec["cycle_start"]),
        cycle_days=spec["cycle_days"],
        income=Money(spec.get("income", 0), currency),
    )
    profile = DailySpendProfile(
        by_weekday=tuple(tuple(day) for day in spec["profile"]),
        lookback_days=spec["lookback_days"],
    )
    return snapshot, profile


def test_cases_exist():
    assert CASES, "no projection cases found — the forecast is unprotected"


@pytest.mark.parametrize("name,case", CASES, ids=[n for n, _ in CASES])
def test_projection_golden_case(name, case):
    snapshot, profile = build(case["input"])
    result = simulate(
        snapshot,
        profile,
        case["horizon_days"],
        trials=case["trials"],
        seed=case["seed"],
    )
    actual = {
        "final_p10": result.bands.p10[-1].sen,
        "final_p50": result.bands.p50[-1].sen,
        "final_p90": result.bands.p90[-1].sen,
        "outlooks": [
            {"goal_id": o.goal_id, "probability_bp": o.probability_bp,
             "median_shortfall": o.median_shortfall.sen}
            for o in result.outlooks
        ],
    }
    assert actual == case["expected"], case["name"]
```

- [ ] **Step 2: Write the case inputs with a deliberately wrong expectation**

Create `apps/api/tests/engine/projection_cases/demo_90day.json`:

```json
{
  "name": "The demo user, ninety days out, both goals dated",
  "horizon_days": 90,
  "trials": 500,
  "seed": 20260828,
  "input": {
    "currency": "MYR",
    "balance": 418040,
    "buffer": 80000,
    "spent_today": 0,
    "income": 650000,
    "today": "2026-09-03",
    "next_payday": "2026-09-25",
    "cycle_start": "2026-08-26",
    "cycle_days": 30,
    "lookback_days": 90,
    "profile": [
      [1380, 1150, 2530],
      [3000, 1090, 4090],
      [1690, 1420, 3110],
      [1250, 890, 2140],
      [2350, 4200, 1980],
      [9000, 3560, 12560],
      [18040, 18040, 9020]
    ],
    "commitments": [
      {"id": "rent", "amount": 120000, "due_date": "2026-09-05"},
      {"id": "phone", "amount": 8900, "due_date": "2026-09-08"},
      {"id": "loan", "amount": 52000, "due_date": "2026-09-10"},
      {"id": "sub", "amount": 5500, "due_date": "2026-09-14"},
      {"id": "net", "amount": 13900, "due_date": "2026-09-18"}
    ],
    "goals": [
      {"id": "g1", "monthly": 27000, "target": 250000, "saved": 115000,
       "target_date": "2026-11-30"},
      {"id": "g2", "monthly": 52500, "target": 800000, "saved": 329000,
       "target_date": "2026-11-30"}
    ]
  },
  "expected": {"final_p10": 0, "final_p50": 0, "final_p90": 0, "outlooks": []}
}
```

Create `apps/api/tests/engine/projection_cases/tight_month.json`:

```json
{
  "name": "A month with no income and a large bill: the band must go negative",
  "horizon_days": 30,
  "trials": 500,
  "seed": 7,
  "input": {
    "currency": "MYR",
    "balance": 60000,
    "buffer": 0,
    "spent_today": 0,
    "income": 0,
    "today": "2026-09-03",
    "next_payday": "2026-12-25",
    "cycle_start": "2026-08-26",
    "cycle_days": 30,
    "lookback_days": 90,
    "profile": [
      [1000, 2000], [1000, 2000], [1000, 2000], [1000, 2000],
      [1000, 2000], [1000, 2000], [1000, 2000]
    ],
    "commitments": [{"id": "rent", "amount": 120000, "due_date": "2026-09-05"}],
    "goals": []
  },
  "expected": {"final_p10": 0, "final_p50": 0, "final_p90": 0, "outlooks": []}
}
```

- [ ] **Step 3: Run to see the real numbers**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_projection_golden.py -v`
Expected: FAIL, with the assertion diff printing the actual values.

- [ ] **Step 4: Verify each number by hand before recording it**

**Do not paste the actuals in.** For `tight_month`, check by arithmetic that `final_p50 ≈ 60000 − 120000 − 30 × 1500 = −105000`, and that `p10 < p50 < p90` with the spread near `30 × 500`. For `demo_90day`, check that `final_p50` is within a few thousand sen of `418040 + 3 × 650000 − (commitments) − (90 × the weekday medians)`, and that the two probabilities are not 0 and not 10000 — a fixture that reads 0% or 100% is a fixture that tests nothing.

If a number disagrees with the hand calculation, the bug is in Task 4 or 5, not in the fixture. Fix the engine.

- [ ] **Step 5: Record the verified numbers and re-run**

Replace each `expected` block with the verified values.

Run: `cd apps/api && .venv/bin/pytest tests/engine -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/tests/engine/projection_cases apps/api/tests/engine/test_projection_golden.py
git commit -m "test: lock the forecast with golden projection cases"
```

---

### Task 7: `run_scenarios()` and `drivers()`

What changes if the user does one thing differently — and which one thing is worth the most. Every lever is re-simulated under the **same seed**, so two results differ by the lever rather than by noise.

**Files:**
- Modify: `apps/api/kira/engine/projection.py`
- Test: `apps/api/tests/engine/test_scenarios.py`

**Interfaces:**
- Consumes: `simulate`, `Lever`, `ScenarioResult`, `Driver`, `safe_to_spend`
- Produces:
  - `apply_lever(snapshot, profile, lever) -> tuple[Snapshot, DailySpendProfile]`
  - `run_scenarios(snapshot, profile, levers, days, trials=..., seed=...) -> tuple[ScenarioResult, ...]`
  - `drivers(snapshot, profile, goal_id, candidates, days, trials=..., seed=...) -> tuple[Driver, ...]`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/engine/test_scenarios.py`:

```python
"""What one change is worth, measured against the same futures."""

from datetime import date

import pytest

from kira.engine.projection import apply_lever, drivers, run_scenarios
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Lever, Snapshot
from kira.money import Money

VARIED = DailySpendProfile(
    by_weekday=tuple((500, 1500, 2500) for _ in range(7)), lookback_days=90
)

GOAL = GoalInput("g1", Money(50000), Money(400000), Money(100000), date(2026, 12, 1))


def snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(300000),
        buffer=Money(0),
        spent_today=Money.zero(),
        commitments=(CommitmentInput("sub", Money(5500), date(2026, 9, 14)),),
        goals=(GOAL,),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
        income=Money(650000),
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_a_goal_lever_changes_the_monthly_contribution():
    moved, _ = apply_lever(
        snapshot(), VARIED, Lever("goal_monthly", "g1", Money(4000))
    )
    assert moved.goals[0].monthly.sen == 54000


def test_a_commitment_lever_changes_that_commitment_only():
    moved, _ = apply_lever(
        snapshot(), VARIED, Lever("commitment_amount", "sub", Money(-5500))
    )
    assert moved.commitments[0].amount.sen == 0


def test_a_daily_spend_lever_shifts_every_observation():
    _, profile = apply_lever(
        snapshot(), VARIED, Lever("daily_spend", "all", Money(-500))
    )
    assert profile.by_weekday[0] == (0, 1000, 2000)


def test_a_daily_spend_lever_never_pushes_an_observation_below_zero():
    _, profile = apply_lever(
        snapshot(), VARIED, Lever("daily_spend", "all", Money(-9999))
    )
    assert profile.by_weekday[0] == (0, 0, 0)


def test_an_unknown_target_is_an_error_rather_than_a_silent_no_op():
    with pytest.raises(KeyError):
        apply_lever(snapshot(), VARIED, Lever("goal_monthly", "nope", Money(1000)))


def test_paying_more_into_a_goal_raises_its_probability():
    results = run_scenarios(
        snapshot(),
        VARIED,
        (Lever("goal_monthly", "g1", Money(20000)),),
        days=90,
        trials=300,
        seed=5,
    )
    baseline = run_scenarios(snapshot(), VARIED, (), days=90, trials=300, seed=5)
    assert results[0].outlooks[0].probability_bp > 0
    assert baseline == ()


def test_scenarios_are_compared_under_one_set_of_futures():
    """Same seed, so the difference is the lever and not the noise."""
    levers = (
        Lever("goal_monthly", "g1", Money(10000)),
        Lever("goal_monthly", "g1", Money(10000)),
    )
    first, second = run_scenarios(snapshot(), VARIED, levers, days=90, trials=200, seed=9)
    assert first.outlooks == second.outlooks


def test_scenario_reports_what_today_would_become():
    result = run_scenarios(
        snapshot(), VARIED, (Lever("goal_monthly", "g1", Money(30000)),),
        days=90, trials=100, seed=9,
    )[0]
    plain = run_scenarios(
        snapshot(), VARIED, (Lever("goal_monthly", "g1", Money(0)),),
        days=90, trials=100, seed=9,
    )[0]
    assert result.safe_today_after < plain.safe_today_after


def test_drivers_rank_by_probability_bought_per_ringgit():
    candidates = (
        Lever("goal_monthly", "g1", Money(20000)),
        Lever("commitment_amount", "sub", Money(-5500)),
    )
    ranked = drivers(snapshot(), VARIED, "g1", candidates, days=90, trials=300, seed=4)
    assert len(ranked) == 2
    assert ranked[0].bp_per_ringgit >= ranked[1].bp_per_ringgit
    assert all(d.probability_bp_before == ranked[0].probability_bp_before for d in ranked)


def test_a_driver_that_buys_nothing_is_still_reported_honestly():
    ranked = drivers(
        snapshot(), VARIED, "g1", (Lever("goal_monthly", "g1", Money(0)),),
        days=90, trials=100, seed=4,
    )
    assert ranked[0].bp_per_ringgit == 0


def test_drivers_for_an_unknown_goal_is_empty():
    ranked = drivers(
        snapshot(), VARIED, "missing", (Lever("goal_monthly", "g1", Money(1000)),),
        days=90, trials=50, seed=4,
    )
    assert ranked == ()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_scenarios.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_lever'`

- [ ] **Step 3: Implement**

Append to `apps/api/kira/engine/projection.py`, adding `Driver`, `Lever`, `ScenarioResult`, `CommitmentInput` and `from kira.engine.safe_to_spend import safe_to_spend` to the imports:

```python
def apply_lever(
    snapshot: Snapshot, profile: DailySpendProfile, lever: Lever
) -> tuple[Snapshot, DailySpendProfile]:
    """One change to the plan, returned as new inputs. Neither argument is mutated."""
    if lever.kind == "goal_monthly":
        if not any(goal.id == lever.target_id for goal in snapshot.goals):
            raise KeyError(f"no goal {lever.target_id!r}")
        goals = tuple(
            replace(goal, monthly=goal.monthly + lever.delta)
            if goal.id == lever.target_id
            else goal
            for goal in snapshot.goals
        )
        return replace(snapshot, goals=goals), profile

    if lever.kind == "commitment_amount":
        if not any(c.id == lever.target_id for c in snapshot.commitments):
            raise KeyError(f"no commitment {lever.target_id!r}")
        commitments = tuple(
            replace(c, amount=c.amount + lever.delta) if c.id == lever.target_id else c
            for c in snapshot.commitments
        )
        return replace(snapshot, commitments=commitments), profile

    # daily_spend: shift every observation, floored at zero. Spending less than
    # nothing is not a plan.
    shifted = tuple(
        tuple(max(0, amount + lever.delta.sen) for amount in day)
        for day in profile.by_weekday
    )
    return snapshot, replace(profile, by_weekday=shifted)


def run_scenarios(
    snapshot: Snapshot,
    profile: DailySpendProfile,
    levers: tuple[Lever, ...],
    days: int,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
) -> tuple[ScenarioResult, ...]:
    """Each lever, simulated under the same seed so only the lever differs."""
    results: list[ScenarioResult] = []
    for lever in levers:
        moved_snapshot, moved_profile = apply_lever(snapshot, profile, lever)
        simulation = simulate(moved_snapshot, moved_profile, days, trials=trials, seed=seed)
        results.append(
            ScenarioResult(
                lever=lever,
                outlooks=simulation.outlooks,
                safe_today_after=safe_to_spend(moved_snapshot).safe_today,
            )
        )
    return tuple(results)


def _probability_for(outlooks: tuple[GoalOutlook, ...], goal_id: str) -> int | None:
    for outlook in outlooks:
        if outlook.goal_id == goal_id:
            return outlook.probability_bp
    return None


def drivers(
    snapshot: Snapshot,
    profile: DailySpendProfile,
    goal_id: str,
    candidates: tuple[Lever, ...],
    days: int,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
) -> tuple[Driver, ...]:
    """Rank candidate changes by basis points of probability bought per ringgit.

    The ranking key is deliberately per-ringgit rather than absolute: an answer
    of "put another RM500 a month in" is true and useless.
    """
    baseline = simulate(snapshot, profile, days, trials=trials, seed=seed)
    before = _probability_for(baseline.outlooks, goal_id)
    if before is None:
        return ()

    ranked: list[Driver] = []
    for lever in candidates:
        moved_snapshot, moved_profile = apply_lever(snapshot, profile, lever)
        after = _probability_for(
            simulate(moved_snapshot, moved_profile, days, trials=trials, seed=seed).outlooks,
            goal_id,
        )
        if after is None:
            continue
        ringgit = abs(lever.delta.sen) // 100
        gained = after - before
        ranked.append(
            Driver(
                lever=lever,
                probability_bp_before=before,
                probability_bp_after=after,
                bp_per_ringgit=gained // ringgit if ringgit else 0,
            )
        )

    return tuple(sorted(ranked, key=lambda d: d.bp_per_ringgit, reverse=True))
```

Add `from dataclasses import replace` to the imports.

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/engine -v && cd apps/api && .venv/bin/lint-imports`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/kira/engine/projection.py apps/api/tests/engine/test_scenarios.py
git commit -m "feat: compare plan changes under one set of futures and rank them"
```

---

### Task 8: `score_advice()` — the scorer, built before its screen

Hindsight's arithmetic, written here because it is pure and can be proven now. Its consumer arrives in the next plan; a scorer with no UI still has a golden file.

**Files:**
- Create: `apps/api/kira/engine/advice.py`
- Modify: `apps/api/kira/engine/types.py` (add `AdviceRecord`, `TrackRecord`)
- Test: `apps/api/tests/engine/test_advice.py`

**Interfaces:**
- Produces:
  - `AdviceRecord(on: date, advised: Money, actual: Money)`
  - `TrackRecord(days: int, followed: int, follow_rate_bp: int, mean_abs_deviation: Money, counterfactual_gain: Money)`
  - `score_advice(records: tuple[AdviceRecord, ...]) -> TrackRecord`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/engine/test_advice.py`:

```python
"""Kira grading her own past advice. The arithmetic, not the wording."""

from datetime import date, timedelta

from kira.engine.advice import score_advice
from kira.engine.types import AdviceRecord
from kira.money import Money


def records(*pairs: tuple[int, int]) -> tuple[AdviceRecord, ...]:
    start = date(2026, 6, 5)
    return tuple(
        AdviceRecord(start + timedelta(days=i), Money(advised), Money(actual))
        for i, (advised, actual) in enumerate(pairs)
    )


def test_no_records_is_an_empty_record_rather_than_a_crash():
    result = score_advice(())
    assert result.days == 0
    assert result.follow_rate_bp == 0
    assert result.counterfactual_gain == Money.zero()


def test_spending_at_or_under_the_number_counts_as_following_it():
    result = score_advice(records((5000, 5000), (5000, 4000), (5000, 6000)))
    assert result.days == 3
    assert result.followed == 2
    assert result.follow_rate_bp == 6667


def test_deviation_is_absolute_so_underspending_is_not_free_credit():
    result = score_advice(records((5000, 3000), (5000, 7000)))
    assert result.mean_abs_deviation.sen == 2000


def test_the_counterfactual_counts_only_the_overspend():
    """Following the advice would have saved the excess, not the underspend."""
    result = score_advice(records((5000, 8000), (5000, 2000), (5000, 5500)))
    assert result.counterfactual_gain.sen == 3500


def test_a_perfect_record_gains_nothing_and_says_so():
    result = score_advice(records((5000, 5000), (4000, 3000)))
    assert result.follow_rate_bp == 10000
    assert result.counterfactual_gain.sen == 0


def test_currency_travels_with_the_record():
    result = score_advice(
        (AdviceRecord(date(2026, 6, 5), Money(5000, "MYR"), Money(6000, "MYR")),)
    )
    assert result.counterfactual_gain.currency == "MYR"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/engine/test_advice.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.engine.advice'`

- [ ] **Step 3: Add the types**

Append to `apps/api/kira/engine/types.py`:

```python
@dataclass(frozen=True, slots=True)
class AdviceRecord:
    """What Kira said on a day, and what actually happened."""

    on: date
    advised: Money
    actual: Money


@dataclass(frozen=True, slots=True)
class TrackRecord:
    days: int
    followed: int
    follow_rate_bp: int
    mean_abs_deviation: Money
    counterfactual_gain: Money
```

- [ ] **Step 4: Implement**

Create `apps/api/kira/engine/advice.py`:

```python
"""Scores Kira's past advice against what the user actually did.

Pure, and deliberately unflattering by construction: the counterfactual counts
only the days the number was exceeded, so underspending never earns credit.
"""

from __future__ import annotations

from kira.engine.types import AdviceRecord, TrackRecord
from kira.money import Money, round_half_up


def score_advice(records: tuple[AdviceRecord, ...]) -> TrackRecord:
    if not records:
        return TrackRecord(
            days=0,
            followed=0,
            follow_rate_bp=0,
            mean_abs_deviation=Money.zero(),
            counterfactual_gain=Money.zero(),
        )

    currency = records[0].advised.currency
    days = len(records)
    followed = sum(1 for r in records if r.actual <= r.advised)
    deviation = sum(abs(r.actual.sen - r.advised.sen) for r in records)
    excess = sum(max(0, r.actual.sen - r.advised.sen) for r in records)

    return TrackRecord(
        days=days,
        followed=followed,
        follow_rate_bp=round_half_up(followed * 10000, days),
        mean_abs_deviation=Money(round_half_up(deviation, days), currency),
        counterfactual_gain=Money(excess, currency),
    )
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/engine -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/kira/engine/advice.py apps/api/kira/engine/types.py \
        apps/api/tests/engine/test_advice.py
git commit -m "feat: score Kira's past advice as a pure function"
```

---

### Task 9: The behaviour profile

The one place the ledger becomes a forecast input. Confirmed rows only, and commitments excluded — they are modelled explicitly, and counting them twice is the obvious bug here.

**Files:**
- Create: `apps/api/kira/services/behaviour.py`
- Modify: `apps/api/kira/db/models.py` (map `Goal.target_date`)
- Modify: `apps/api/kira/services/snapshot.py` (carry income, goal target and saved)
- Test: `apps/api/tests/services/test_behaviour.py`

**Interfaces:**
- Consumes: `Transaction`, `TXN_CONFIRMED`, `Commitment`, `DailySpendProfile`
- Produces: `build_profile(session, user, today: date, lookback_days: int = 90) -> DailySpendProfile`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/services/test_behaviour.py`:

```python
"""What the forecast learns from the ledger, and what it must ignore."""

from datetime import date, timedelta

from kira.db.models import TXN_CONFIRMED, TXN_DRAFT, Commitment, Transaction
from kira.money import Money
from kira.services.behaviour import build_profile

TODAY = date(2026, 9, 3)


async def add_txn(session, user, sen: int, on: date, status=TXN_CONFIRMED, merchant="Kedai"):
    session.add(
        Transaction(
            user_id=user.id, merchant=merchant, amount=Money(sen),
            category="food", occurred_on=on, status=status,
        )
    )
    await session.flush()


async def test_a_confirmed_row_lands_on_its_weekday(session, user):
    monday = date(2026, 8, 31)
    assert monday.weekday() == 0
    await add_txn(session, user, 1500, monday)

    profile = await build_profile(session, user, TODAY)
    assert profile.by_weekday[0] == (1500,)


async def test_two_rows_on_one_day_become_one_observation(session, user):
    monday = date(2026, 8, 31)
    await add_txn(session, user, 1500, monday)
    await add_txn(session, user, 900, monday, merchant="Kopitiam")

    profile = await build_profile(session, user, TODAY)
    assert profile.by_weekday[0] == (2400,), "a day is one observation, not two"


async def test_a_draft_is_invisible_to_the_forecast(session, user):
    await add_txn(session, user, 5000, date(2026, 8, 31), status=TXN_DRAFT)
    profile = await build_profile(session, user, TODAY)
    assert profile.is_empty


async def test_a_transaction_matching_a_commitment_is_not_counted_twice(session, user):
    session.add(
        Commitment(
            user_id=user.id, name="Streaming bundle", amount=Money(5500),
            due_date=date(2026, 9, 14),
        )
    )
    await session.flush()
    await add_txn(session, user, 5500, date(2026, 8, 31), merchant="Streaming bundle")

    profile = await build_profile(session, user, TODAY)
    assert profile.is_empty, "the projection lands commitments itself"


async def test_the_window_ends_at_today_and_excludes_it(session, user):
    await add_txn(session, user, 1500, TODAY)
    profile = await build_profile(session, user, TODAY)
    assert profile.is_empty, "today is still being spent; it is not an observation"


async def test_the_window_starts_at_the_lookback(session, user):
    await add_txn(session, user, 1500, TODAY - timedelta(days=200))
    profile = await build_profile(session, user, TODAY, lookback_days=90)
    assert profile.is_empty


async def test_the_lookback_is_reported(session, user):
    profile = await build_profile(session, user, TODAY, lookback_days=45)
    assert profile.lookback_days == 45


async def test_a_day_with_no_spending_is_a_zero_observation(session, user):
    """Days off are part of the pattern; dropping them would inflate the forecast."""
    monday = date(2026, 8, 31)
    await add_txn(session, user, 1500, monday)
    profile = await build_profile(session, user, TODAY, lookback_days=14)
    assert 0 in profile.by_weekday[1], "Tuesday had no spending and must say so"
```

If `apps/api/tests/services/` has no `user` fixture, add one to `apps/api/tests/conftest.py` following the pattern the existing service tests use.

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/services/test_behaviour.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.services.behaviour'`

- [ ] **Step 3: Map the goal's target date and carry it into the snapshot**

In `apps/api/kira/db/models.py`, add to `Goal`:

```python
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
```

In `apps/api/kira/services/snapshot.py`, extend the `GoalInput` construction and add income:

```python
        goals=tuple(
            GoalInput(
                str(goal.id),
                goal.monthly,
                goal.target,
                goal.saved,
                goal.target_date,
            )
            for goal in goals
        ),
```

and add `income=user.monthly_income,` to the `Snapshot(...)` call.

- [ ] **Step 4: Implement the profile builder**

Create `apps/api/kira/services/behaviour.py`:

```python
"""Turns the confirmed ledger into the shape the forecast resamples.

A day is one observation, including the days nothing was spent — dropping the
quiet days would forecast a life the user does not live.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import TXN_CONFIRMED, Commitment, Transaction, User
from kira.engine.types import DailySpendProfile

DEFAULT_LOOKBACK_DAYS = 90


async def build_profile(
    session: AsyncSession,
    user: User,
    today: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> DailySpendProfile:
    start = today - timedelta(days=lookback_days)

    commitment_names = {
        name.strip().lower()
        for name in (
            await session.execute(
                select(Commitment.name).where(Commitment.user_id == user.id)
            )
        ).scalars().all()
    }

    rows = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.status == TXN_CONFIRMED,
                Transaction.occurred_on >= start,
                Transaction.occurred_on < today,
            )
        )
    ).scalars().all()

    totals: dict[date, int] = {}
    day = start
    while day < today:
        totals[day] = 0
        day += timedelta(days=1)

    for row in rows:
        # The projection lands commitments on their due dates itself; a matching
        # ledger row would otherwise be spent twice.
        if row.merchant.strip().lower() in commitment_names:
            continue
        totals[row.occurred_on] = totals.get(row.occurred_on, 0) + row.amount.sen

    buckets: list[list[int]] = [[] for _ in range(7)]
    for on, total in sorted(totals.items()):
        buckets[on.weekday()].append(total)

    return DailySpendProfile(
        by_weekday=tuple(tuple(bucket) for bucket in buckets),
        lookback_days=lookback_days,
    )
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && .venv/bin/pytest -v`
Expected: PASS across the whole suite, including the seed tests from Task 1.

- [ ] **Step 6: Commit**

```bash
git add apps/api/kira/services/behaviour.py apps/api/kira/services/snapshot.py \
        apps/api/kira/db/models.py apps/api/tests/services/test_behaviour.py
git commit -m "feat: derive a spending profile from the confirmed ledger"
```

---

### Task 10: The Foresight service

Assembles the inputs, calls the engine, proposes the candidate levers. Computes on read and caches nothing — the same discipline as `safe_to_spend`, and the same absence of an entire class of stale-value bugs.

**Files:**
- Create: `apps/api/kira/services/foresight.py`
- Test: `apps/api/tests/services/test_foresight.py`

**Interfaces:**
- Consumes: `load_snapshot`, `build_profile`, `simulate`, `drivers`, `run_scenarios`
- Produces:
  - `ForesightResult` dataclass: `horizon_days`, `bands` (`Simulation`), `drivers` (`tuple[Driver, ...]`), `profile_days: int`, `assumption: str`
  - `async foresight(session, user, today, horizon_days=90) -> ForesightResult`
  - `async compare(session, user, today, levers, horizon_days=90) -> tuple[ScenarioResult, ...]`
  - `candidate_levers(snapshot) -> tuple[Lever, ...]`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/services/test_foresight.py`:

```python
"""The forecast, assembled from real rows."""

from datetime import date

import pytest

from kira.engine.types import Lever
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.foresight import candidate_levers, compare, foresight
from kira.services.snapshot import load_snapshot


async def test_the_demo_user_gets_a_band_over_the_horizon(session):
    user = await seed_demo_user(session)
    await session.flush()

    result = await foresight(session, user, DEMO_TODAY, horizon_days=90)
    assert len(result.bands.bands.p50) == 90
    assert result.profile_days == 90


async def test_the_assumption_travels_with_the_number(session):
    """A probability read as a promise is a trust failure, so it is labelled."""
    user = await seed_demo_user(session)
    await session.flush()

    result = await foresight(session, user, DEMO_TODAY)
    assert "90 days" in result.assumption


async def test_candidate_levers_cover_the_goals_and_the_unprotected_commitments(session):
    user = await seed_demo_user(session)
    await session.flush()
    snapshot = await load_snapshot(session, user, DEMO_TODAY)

    levers = candidate_levers(snapshot)
    kinds = {lever.kind for lever in levers}
    assert "goal_monthly" in kinds
    assert "daily_spend" in kinds
    assert levers, "a forecast with no proposed change is a diagnosis with no treatment"


async def test_a_protected_commitment_is_never_a_candidate(session):
    """Rent is protected in the seed. Kira does not propose skipping it."""
    user = await seed_demo_user(session)
    await session.flush()
    snapshot = await load_snapshot(session, user, DEMO_TODAY)

    targets = {lever.target_id for lever in candidate_levers(snapshot)}
    rent = next(c for c in snapshot.commitments if c.amount.sen == 120000)
    assert rent.id not in targets


async def test_compare_returns_one_result_per_lever(session):
    user = await seed_demo_user(session)
    await session.flush()
    snapshot = await load_snapshot(session, user, DEMO_TODAY)
    goal_id = snapshot.goals[0].id

    results = await compare(
        session, user, DEMO_TODAY,
        (Lever("goal_monthly", goal_id, Money(5000)),),
        horizon_days=60,
    )
    assert len(results) == 1
    assert results[0].lever.target_id == goal_id


async def test_a_horizon_beyond_a_year_is_refused(session):
    user = await seed_demo_user(session)
    await session.flush()
    with pytest.raises(ValueError):
        await foresight(session, user, DEMO_TODAY, horizon_days=400)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/services/test_foresight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.services.foresight'`

- [ ] **Step 3: Implement**

Create `apps/api/kira/services/foresight.py`:

```python
"""The forecast, assembled. Computed on read; nothing here is cached.

``safe_to_spend`` is a pure function of a snapshot and so is this. There is no
materialised column and no invalidation logic, which is why the entire class of
stale-derived-value bugs does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import Commitment, User
from kira.engine.projection import drivers as rank_drivers
from kira.engine.projection import run_scenarios, simulate
from kira.engine.types import Driver, Lever, ScenarioResult, Simulation, Snapshot
from kira.money import Money
from kira.services.behaviour import DEFAULT_LOOKBACK_DAYS, build_profile
from kira.services.snapshot import load_snapshot

MAX_HORIZON_DAYS = 365
DEFAULT_HORIZON_DAYS = 90

# The changes Kira is willing to propose, as deltas. Deliberately modest: a
# driver reading "put in another RM500 a month" is true and useless.
GOAL_STEPS = (4000, 10000, 20000)
SPEND_STEPS = (-500, -1500)


@dataclass(frozen=True, slots=True)
class ForesightResult:
    horizon_days: int
    bands: Simulation
    drivers: tuple[Driver, ...]
    profile_days: int
    assumption: str


def candidate_levers(snapshot: Snapshot, protected_ids: frozenset[str] = frozenset()) -> tuple[Lever, ...]:
    """Every change worth simulating, and nothing the user has ruled out."""
    currency = snapshot.currency
    levers: list[Lever] = []
    for goal in snapshot.goals:
        for step in GOAL_STEPS:
            levers.append(Lever("goal_monthly", goal.id, Money(step, currency)))
    for commitment in snapshot.commitments:
        if commitment.id in protected_ids:
            continue
        levers.append(
            Lever("commitment_amount", commitment.id, -commitment.amount)
        )
    for step in SPEND_STEPS:
        levers.append(Lever("daily_spend", "all", Money(step, currency)))
    return tuple(levers)


async def _protected_ids(session: AsyncSession, user: User) -> frozenset[str]:
    rows = (
        await session.execute(
            select(Commitment.id).where(
                Commitment.user_id == user.id, Commitment.protected.is_(True)
            )
        )
    ).scalars().all()
    return frozenset(str(row) for row in rows)


def _check_horizon(horizon_days: int) -> None:
    if horizon_days <= 0 or horizon_days > MAX_HORIZON_DAYS:
        raise ValueError(f"horizon_days must be in 1..{MAX_HORIZON_DAYS}")


async def foresight(
    session: AsyncSession,
    user: User,
    today: date,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> ForesightResult:
    _check_horizon(horizon_days)
    snapshot = await load_snapshot(session, user, today)
    profile = await build_profile(session, user, today)
    simulation = simulate(snapshot, profile, horizon_days)

    protected = await _protected_ids(session, user)
    candidates = candidate_levers(snapshot, protected)
    ranked: tuple[Driver, ...] = ()
    if simulation.outlooks:
        ranked = rank_drivers(
            snapshot, profile, simulation.outlooks[0].goal_id, candidates, horizon_days
        )

    return ForesightResult(
        horizon_days=horizon_days,
        bands=simulation,
        drivers=ranked,
        profile_days=profile.lookback_days,
        assumption=(
            f"Based on your last {DEFAULT_LOOKBACK_DAYS} days of confirmed spending. "
            "It is a projection, not a promise."
        ),
    )


async def compare(
    session: AsyncSession,
    user: User,
    today: date,
    levers: tuple[Lever, ...],
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> tuple[ScenarioResult, ...]:
    _check_horizon(horizon_days)
    snapshot = await load_snapshot(session, user, today)
    profile = await build_profile(session, user, today)
    return run_scenarios(snapshot, profile, levers, horizon_days)
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/services -v`
Expected: PASS. If `test_the_demo_user_gets_a_band_over_the_horizon` is slow, the seeded profile is larger than the synthetic ones — check the Task 5 latency measurement still holds.

- [ ] **Step 5: Give the demo goals target dates**

The seed's goals have none, so `outlooks` would be empty and the demo would show no probability. In `apps/api/kira/seed/demo.py`, extend the `GOALS` tuples with a target date each — `date(2026, 11, 30)` for the emergency top-up and `date(2027, 6, 30)` for the wedding — and pass `target_date=` when constructing each `Goal`.

Add to `apps/api/tests/services/test_foresight.py`:

```python
async def test_the_demo_user_has_a_probability_to_show(session):
    user = await seed_demo_user(session)
    await session.flush()
    result = await foresight(session, user, DEMO_TODAY, horizon_days=90)
    assert result.bands.outlooks, "the demo must show a probability, not an empty panel"
    assert result.drivers, "and a change that moves it"
```

Run: `cd apps/api && .venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/kira/services/foresight.py apps/api/kira/seed/demo.py \
        apps/api/tests/services/test_foresight.py
git commit -m "feat: assemble the forecast and rank the changes that move it"
```

---

### Task 11: The Foresight API

**Files:**
- Create: `apps/api/kira/api/routers/foresight.py`
- Modify: `apps/api/kira/api/schemas.py`
- Modify: `apps/api/kira/api/app.py`
- Test: `apps/api/tests/api/test_foresight_endpoint.py`

**Interfaces:**
- Consumes: `CurrentUser`, `SessionDep`, `today_for`, `foresight`, `compare`
- Produces: `GET /v1/foresight?horizon=90`, `POST /v1/foresight/scenarios`; response models `ForesightResponse`, `ScenarioComparisonResponse`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/api/test_foresight_endpoint.py`:

```python
"""The forecast over HTTP."""

from kira.seed.demo import seed_demo_user


async def test_foresight_requires_a_token(client):
    response = await client.get("/v1/foresight")
    assert response.status_code == 401


async def test_foresight_returns_bands_and_drivers(client, auth_headers, session):
    await seed_demo_user(session)
    await session.commit()

    response = await client.get("/v1/foresight?horizon=90", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()

    assert body["horizon_days"] == 90
    assert len(body["p50"]) == 90
    assert body["p10"][0]["sen"] <= body["p90"][0]["sen"]
    assert body["assumption"]
    assert all(0 <= o["probability_bp"] <= 10000 for o in body["outlooks"])


async def test_the_horizon_is_validated_at_the_edge(client, auth_headers):
    assert (await client.get("/v1/foresight?horizon=0", headers=auth_headers)).status_code == 422
    assert (await client.get("/v1/foresight?horizon=999", headers=auth_headers)).status_code == 422


async def test_scenarios_compare_the_levers_posted(client, auth_headers, session):
    user = await seed_demo_user(session)
    await session.commit()

    listing = (await client.get("/v1/foresight", headers=auth_headers)).json()
    goal_id = listing["outlooks"][0]["goal_id"]

    response = await client.post(
        "/v1/foresight/scenarios",
        headers=auth_headers,
        json={
            "horizon_days": 60,
            "levers": [{"kind": "goal_monthly", "target_id": goal_id, "delta_sen": 5000}],
        },
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["lever"]["target_id"] == goal_id


async def test_an_unknown_lever_kind_is_rejected_before_the_engine(client, auth_headers, session):
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/foresight/scenarios",
        headers=auth_headers,
        json={"horizon_days": 60,
              "levers": [{"kind": "sell_the_car", "target_id": "x", "delta_sen": 1}]},
    )
    assert response.status_code == 422


async def test_the_forecast_writes_nothing(client, auth_headers, session):
    """A read is a read. This endpoint touches no financial table."""
    from sqlalchemy import func, select

    from kira.db.models import Transaction

    await seed_demo_user(session)
    await session.commit()
    before = (await session.execute(select(func.count()).select_from(Transaction))).scalar_one()

    await client.get("/v1/foresight", headers=auth_headers)

    after = (await session.execute(select(func.count()).select_from(Transaction))).scalar_one()
    assert before == after
```

Follow the fixture names the existing `apps/api/tests/api/` tests use for `client` and `auth_headers`; if the demo user's credentials differ from the fixture's user, seed against the fixture's user instead.

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/api/test_foresight_endpoint.py -v`
Expected: FAIL — 404 on `/v1/foresight`

- [ ] **Step 3: Add the schemas**

In `apps/api/kira/api/schemas.py`, following the file's existing style:

```python
class MoneyOut(BaseModel):
    sen: int
    currency: str


class GoalOutlookOut(BaseModel):
    goal_id: str
    target_date: date
    probability_bp: int
    median_shortfall: MoneyOut


class LeverIn(BaseModel):
    kind: Literal["goal_monthly", "commitment_amount", "daily_spend"]
    target_id: str
    delta_sen: int


class LeverOut(BaseModel):
    kind: str
    target_id: str
    delta: MoneyOut


class DriverOut(BaseModel):
    lever: LeverOut
    probability_bp_before: int
    probability_bp_after: int
    bp_per_ringgit: int


class ForesightResponse(BaseModel):
    horizon_days: int
    dates: list[date]
    p10: list[MoneyOut]
    p50: list[MoneyOut]
    p90: list[MoneyOut]
    outlooks: list[GoalOutlookOut]
    drivers: list[DriverOut]
    profile_days: int
    assumption: str


class ScenarioRequest(BaseModel):
    horizon_days: int = Field(default=90, ge=1, le=365)
    levers: list[LeverIn]


class ScenarioResultOut(BaseModel):
    lever: LeverOut
    outlooks: list[GoalOutlookOut]
    safe_today_after: MoneyOut


class ScenarioComparisonResponse(BaseModel):
    results: list[ScenarioResultOut]
```

- [ ] **Step 4: Add the router**

Create `apps/api/kira/api/routers/foresight.py`:

```python
"""The forecast over HTTP. Reads only; the transport layer does no arithmetic."""

from __future__ import annotations

from fastapi import APIRouter, Query

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import (
    DriverOut,
    ForesightResponse,
    GoalOutlookOut,
    LeverOut,
    MoneyOut,
    ScenarioComparisonResponse,
    ScenarioRequest,
    ScenarioResultOut,
)
from kira.engine.types import Lever
from kira.money import Money
from kira.services.clock import today_for
from kira.services.foresight import compare, foresight

router = APIRouter(prefix="/v1/foresight", tags=["foresight"])


def _money(amount: Money) -> MoneyOut:
    return MoneyOut(sen=amount.sen, currency=amount.currency)


def _outlook(outlook) -> GoalOutlookOut:
    return GoalOutlookOut(
        goal_id=outlook.goal_id,
        target_date=outlook.target_date,
        probability_bp=outlook.probability_bp,
        median_shortfall=_money(outlook.median_shortfall),
    )


def _lever(lever: Lever) -> LeverOut:
    return LeverOut(kind=lever.kind, target_id=lever.target_id, delta=_money(lever.delta))


@router.get("", response_model=ForesightResponse)
async def get_foresight(
    user: CurrentUser,
    session: SessionDep,
    horizon: int = Query(default=90, ge=1, le=365),
) -> ForesightResponse:
    result = await foresight(session, user, today_for(), horizon_days=horizon)
    return ForesightResponse(
        horizon_days=result.horizon_days,
        dates=[day.on for day in result.bands.bands.days],
        p10=[_money(m) for m in result.bands.bands.p10],
        p50=[_money(m) for m in result.bands.bands.p50],
        p90=[_money(m) for m in result.bands.bands.p90],
        outlooks=[_outlook(o) for o in result.bands.outlooks],
        drivers=[
            DriverOut(
                lever=_lever(d.lever),
                probability_bp_before=d.probability_bp_before,
                probability_bp_after=d.probability_bp_after,
                bp_per_ringgit=d.bp_per_ringgit,
            )
            for d in result.drivers
        ],
        profile_days=result.profile_days,
        assumption=result.assumption,
    )


@router.post("/scenarios", response_model=ScenarioComparisonResponse)
async def post_scenarios(
    user: CurrentUser, session: SessionDep, request: ScenarioRequest
) -> ScenarioComparisonResponse:
    levers = tuple(
        Lever(kind=item.kind, target_id=item.target_id, delta=Money(item.delta_sen, user.currency))
        for item in request.levers
    )
    results = await compare(
        session, user, today_for(), levers, horizon_days=request.horizon_days
    )
    return ScenarioComparisonResponse(
        results=[
            ScenarioResultOut(
                lever=_lever(r.lever),
                outlooks=[_outlook(o) for o in r.outlooks],
                safe_today_after=_money(r.safe_today_after),
            )
            for r in results
        ]
    )
```

In `apps/api/kira/api/app.py`, add `foresight` to the router import and `app.include_router(foresight.router)` alongside the others.

- [ ] **Step 5: Run the tests and regenerate the contracts**

Run: `cd apps/api && .venv/bin/pytest tests/api -v && .venv/bin/lint-imports`
Expected: PASS.

Run: `npm run gen:contracts`
Expected: `packages/contracts/src/schema.d.ts` gains the foresight paths.

- [ ] **Step 6: Commit**

```bash
git add apps/api/kira/api packages/contracts apps/api/tests/api/test_foresight_endpoint.py
git commit -m "feat: expose the forecast and scenario comparison over HTTP"
```

---

### Task 12: Three read tools for the Butler

The agent reaches the forecast the same way it reaches every other module: one file, one `register()` call each, no change to the graph.

**Files:**
- Create: `apps/api/kira/agent/tools/foresight.py`
- Modify: `apps/api/kira/agent/tools/__init__.py` (registration, following the existing pattern)
- Test: `apps/api/tests/agent/test_foresight_tools.py`

**Interfaces:**
- Consumes: `ToolSpec`, `ToolContext`, `ToolResult`, the registry, `foresight`, `compare`
- Produces: read tools `project_future`, `compare_scenarios`, `explain_probability`

- [ ] **Step 1: Read the existing pattern**

Open `apps/api/kira/agent/tools/dashboard.py` and `apps/api/kira/agent/tools/spec.py`. The new tools follow them exactly: an args model, a handler returning a `ToolResult` with evidence rows, `kind="read"`. Do not invent a new shape.

- [ ] **Step 2: Write the failing test**

Create `apps/api/tests/agent/test_foresight_tools.py`, following the fixtures and assertions in the existing `apps/api/tests/agent/test_registry.py`:

```python
"""The forecast, reachable by the agent — and only readable."""

import pytest

from kira.agent.tools import registry
from kira.seed.demo import DEMO_TODAY, seed_demo_user

TOOL_NAMES = ("project_future", "compare_scenarios", "explain_probability")


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_the_tool_is_registered(name):
    assert registry.get(name) is not None


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_the_tool_is_a_read(name):
    assert registry.get(name).kind == "read"


async def test_project_future_returns_evidence_a_person_can_check(session, tool_context):
    await seed_demo_user(session)
    await session.flush()

    result = await registry.get("project_future").handler(
        tool_context, {"horizon_days": 90}
    )
    assert result.evidence, "an answer without evidence is a guess"
    labels = " ".join(row["label"] for row in result.evidence).lower()
    assert "90" in labels or "probability" in labels


async def test_explain_probability_states_its_assumption(session, tool_context):
    await seed_demo_user(session)
    await session.flush()

    result = await registry.get("explain_probability").handler(tool_context, {})
    assert "not a promise" in result.summary.lower() or "projection" in result.summary.lower()
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd apps/api && .venv/bin/pytest tests/agent/test_foresight_tools.py -v`
Expected: FAIL — the registry has no `project_future`.

- [ ] **Step 4: Implement the tools**

Create `apps/api/kira/agent/tools/foresight.py` with three `ToolSpec`s, all `kind="read"`, mirroring `dashboard.py`'s structure:

- `project_future(horizon_days: int = 90)` — calls `services.foresight.foresight`; evidence rows: the closing p50 at the horizon, each goal's probability as a percentage rendered from basis points (`bp // 100`), and the assumption line.
- `compare_scenarios(levers: list[LeverArgs], horizon_days: int = 90)` — calls `services.foresight.compare`; one evidence row per lever with its before and after probability.
- `explain_probability(goal_id: str | None = None)` — returns the drivers for that goal, or the first goal with an outlook, with the assumption in the summary.

Register all three in `apps/api/kira/agent/tools/__init__.py` beside the existing registrations.

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && .venv/bin/pytest tests/agent -v && .venv/bin/lint-imports`
Expected: PASS, including the existing registry contract tests — which assert that every registered write tool has a `summarise`, and these are reads.

- [ ] **Step 6: Commit**

```bash
git add apps/api/kira/agent/tools apps/api/tests/agent/test_foresight_tools.py
git commit -m "feat: let the Butler read the forecast"
```

---

### Task 13: The Plan screen

The tab currently renders `Placeholder`. It becomes the forecast: a band, a probability per goal, and the ranked changes — each of which hands off to the Butler's existing approval card rather than writing anything itself.

**Files:**
- Create: `apps/web/src/screens/Plan.tsx`
- Create: `apps/web/src/screens/Plan.test.tsx`
- Create: `apps/web/src/components/FanChart.tsx`
- Modify: `apps/web/src/api/hooks.ts` (add `useForesight`)
- Modify: `apps/web/src/App.tsx` (route `plan` to the new screen)
- Modify: `apps/web/src/styles/kira.css`

**Interfaces:**
- Consumes: the generated `@kira/contracts` types, the existing `api` client and query-hook pattern in `apps/web/src/api/hooks.ts`, the `fmt` money helper
- Produces: `useForesight(horizon?: number)`, `<Plan />`, `<FanChart />`

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/screens/Plan.test.tsx`, following the structure of the existing `Today.test.tsx` (same render helper, same query-client wrapper, same fetch mocking):

```tsx
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

// renderWithProviders and mockApi come from the existing test setup used by
// Today.test.tsx — reuse them rather than writing new ones.

describe('Plan', () => {
  it('shows a probability for each dated goal', async () => {
    mockApi('/v1/foresight', foresightFixture)
    renderWithProviders(<Plan />)
    expect(await screen.findByText(/62%/)).toBeInTheDocument()
  })

  it('states the assumption next to the number, not in a tooltip', async () => {
    mockApi('/v1/foresight', foresightFixture)
    renderWithProviders(<Plan />)
    expect(await screen.findByText(/last 90 days/i)).toBeInTheDocument()
    expect(screen.getByText(/not a promise/i)).toBeInTheDocument()
  })

  it('renders one driver card per ranked change', async () => {
    mockApi('/v1/foresight', foresightFixture)
    renderWithProviders(<Plan />)
    const cards = await screen.findAllByRole('button', { name: /let kira/i })
    expect(cards).toHaveLength(foresightFixture.drivers.length)
  })

  it('shows what a driver buys, before and after', async () => {
    mockApi('/v1/foresight', foresightFixture)
    renderWithProviders(<Plan />)
    expect(await screen.findByText(/62% → 91%/)).toBeInTheDocument()
  })

  it('says so plainly when there is not enough history to forecast', async () => {
    mockApi('/v1/foresight', { ...foresightFixture, outlooks: [], drivers: [], profileDays: 3 })
    renderWithProviders(<Plan />)
    expect(await screen.findByText(/not enough history/i)).toBeInTheDocument()
  })
})
```

Build `foresightFixture` from the real shape — copy a response body out of `curl localhost:8000/v1/foresight` rather than inventing field names.

- [ ] **Step 2: Run to verify it fails**

Run: `npm --workspace apps/web run test -- Plan`
Expected: FAIL — `Plan` cannot be resolved.

- [ ] **Step 3: Add the query hook**

In `apps/web/src/api/hooks.ts`, add `useForesight` following the exact shape of the existing `useDashboardToday`.

- [ ] **Step 4: Build the fan chart**

Create `apps/web/src/components/FanChart.tsx`: an inline SVG taking `p10`, `p50`, `p90` and `dates`. Two filled paths for the bands and a stroked path for the median. No charting library — the app ships no chart dependency today and one band does not justify adding one. Give the `<svg>` a `role="img"` and an `aria-label` naming the horizon and the final median.

- [ ] **Step 5: Build the screen**

Create `apps/web/src/screens/Plan.tsx`:

- the fan chart across the horizon;
- a probability ring per goal, rendered from basis points as `Math.round(bp / 100)` — the only place a percentage exists;
- **the assumption line under the rings, in body text, not a tooltip** — spec §6.4;
- a driver card per ranked change: what it costs, `before% → after%`, and a "Let Kira do it" button that posts the driver into the Butler thread, where the existing approval card handles it. **The button must not call any write endpoint directly.**
- an honest empty state when `outlooks` is empty or `profileDays` is small: "Not enough history to forecast yet."

Route `plan` to it in `App.tsx`, replacing the `Placeholder`.

- [ ] **Step 6: Run the tests**

Run: `npm --workspace apps/web run test`
Expected: PASS, all suites.

- [ ] **Step 7: Verify against the running app**

Run the API and the web dev server, sign in as the demo user, open the Plan tab. Confirm: the band widens with the horizon, both goals show a probability that is neither 0% nor 100%, the assumption line is visible without hovering, and a driver card's button opens the Butler with an approval rather than changing a number on the spot.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src
git commit -m "feat: build the Plan screen with the forecast band and ranked changes"
```

---

## Self-review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §4 M0 seed depth, engine-generated advice rows | 1 |
| §5.1 types, income, goal funding | 3, 9 |
| §5.2 `project`, `simulate`, `run_scenarios`, `drivers`, `score_advice` | 4, 5, 7, 8 |
| §5.3 latency measured before anything builds on it | 5 (Step 5) |
| §6.1 behaviour service, confirmed-only, no double-count | 9 |
| §6.2 API | 11 |
| §6.3 three read tools, fixes via existing write tools | 12, 13 (Step 5) |
| §6.4 Plan screen, assumption on the surface | 13 |
| §7.1 `daily_advice` table | 1 |
| §9 data model changes | 1, 9 |
| §10 testing: golden, determinism, no-float, draft invariant, double-count | 2, 5, 6, 9, 11 |
| §12 demo script document | **next plan** — it belongs with the rehearsal step, after M4 and M3 |
| §7.2–7.3 Hindsight service and surface, §8 the worker | **next plan**, as stated in "Scope of this plan" |

**Type consistency:** `DailySpendProfile.by_weekday` / `.median_for` / `.is_empty` are defined in Task 3 and used unchanged in 4, 5, 7, 9. `Simulation.bands` is a `Projection`, so the service reaches bands as `result.bands.bands.p50` — awkward but consistent, and the router spells it out. `probability_bp` is basis points at every layer; the single conversion to a percentage lives in Task 13's ring.

**Known ordering wrinkle:** Task 1's `kira/seed/advice.py` references `snapshot.income`, which Task 3 adds. Task 1 Step 6 says so explicitly and gives the one-line fix. Executors running tasks in order should add the `Snapshot.income` field when they reach it.
