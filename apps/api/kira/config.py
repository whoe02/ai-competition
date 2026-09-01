"""Runtime configuration. Everything is overridable by environment variable."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `enable_decoding=False` stops the env sources from JSON-parsing list
    # fields before validation, so CORS_ORIGINS can be written plainly.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", enable_decoding=False
    )

    database_url: str = "postgresql+asyncpg://kira:kira@localhost:5432/kira"
    jwt_secret: str = "development-only-replace-with-a-secure-jwt-secret"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cors_origins: list[str] = ["http://localhost:5173"]

    # Pins "today" so the seeded demo produces the same numbers on any date.
    # Unset in real use, in which case the server's UTC date is used.
    demo_today: date | None = None

    # ── Butler ────────────────────────────────────────────────────────────────
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    # The model every turn is asked of first.
    butler_model: str = "qwen3.7-flash"
    # Tried with the same call when the main model errors: an id this key is
    # not served, a rate limit, a timeout. Only when both fail does a turn
    # drop to the offline stand-in. Blank disables the middle rung.
    butler_fallback_model: str = "qwen3.6-plus"
    # Forced offline; the Butler also falls back on a missing key or a failed call.
    butler_offline: bool = False
    butler_max_tool_iterations: int = 6
    butler_request_timeout_seconds: float = 30.0
    # How long a whole turn may spend looking things up before the guard stops
    # it and makes it answer. Every tool result now goes back to the model, so
    # a turn can chain — and something has to bound a chain by the thing the
    # user actually feels, which is the clock and not the number of passes.
    butler_turn_budget_seconds: float = 15.0
    # The turn that chooses tools, and the turn that writes the answer, want
    # opposite things. Choosing is a classification and wants to be the same
    # every time; writing is prose and reads as a machine when it is.
    butler_reasoning_temperature: float = 0.0
    butler_compose_temperature: float = 0.6
    butler_memory_limit: int = 40
    # The Plan screen's ask box. Far shorter than the Butler's own timeout above,
    # because the two are waited on differently: a conversation may take its time
    # and shows tokens arriving, where this one holds a screen of live figures
    # still and has nothing to show while it does.
    day_plan_interpret_timeout_seconds: float = 6.0
    # The planner's own choosing turn. Shorter than the Butler's timeout for
    # the same reason: it sits inside a turn that is already being waited on,
    # and a slow choice is one the deterministic cheapest-first ranking can
    # stand in for without the user losing an answer.
    day_plan_choose_timeout_seconds: float = 8.0
    # The optional relevance pass lets the planner match everyday food terms
    # (for example, "nasi lemak") against the places actually in range. Off,
    # the deterministic recorded-cuisine filter remains the complete path.
    plan_search_llm_enabled: bool = False
    # This call sits on the Plan screen's critical path, so it has a shorter
    # timeout and falls back to the deterministic filter when it expires.
    plan_search_llm_timeout_seconds: float = 4.0
    # Voice and camera capture. Off means the affordances stay hidden rather
    # than pretending to work; the adapters behind them are chosen in the
    # adapter registry, not here.
    capture_receipt_enabled: bool = True
    capture_voice_enabled: bool = True
    capture_max_bytes: int = 8 * 1024 * 1024

    # The scheduler is a separate process and stores its job metadata in the
    # same Postgres database. Asia/Kuala_Lumpur is explicit: daily financial
    # advice must not shift with the server's timezone.
    worker_timezone: str = "Asia/Kuala_Lumpur"
    worker_hour: int = Field(default=5, ge=0, le=23)
    worker_minute: int = Field(default=0, ge=0, le=59)

    # ── Routing ───────────────────────────────────────────────────────────────
    # A Grab fare is charged on the road, not on the great circle: Bangsar to a
    # shop 3.7 km away in a straight line is 8.1 km of driving, and quoting the
    # straight line understates that trip by about half. OSRM is asked for the
    # road figure; off, or unconfigured, or unreachable, the planner falls back
    # to the straight line and every place it returns is labelled as such.
    routing_enabled: bool = True
    osrm_base_url: str = "https://router.project-osrm.org"
    # Short on purpose. The public router is volunteer-run and owes us nothing,
    # and a page that states today's money must not hang waiting on it.
    routing_timeout_seconds: float = 2.5

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept the comma-separated list an operator would actually write.

        pydantic-settings parses a list field from the environment as JSON, so
        `CORS_ORIGINS=http://localhost:5173` — the form the example file
        documents — would otherwise fail at startup rather than at review.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @property
    def checkpointer_dsn(self) -> str:
        """LangGraph's Postgres checkpointer runs on psycopg3, not asyncpg.

        Same database, second driver: the SQLAlchemy dialect suffix has to go.
        """
        return self.database_url.replace("+asyncpg", "").replace("+psycopg", "")

    @property
    def scheduler_database_url(self) -> str:
        """A synchronous SQLAlchemy URL for APScheduler's persistent job store."""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
