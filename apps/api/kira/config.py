"""Runtime configuration. Everything is overridable by environment variable."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    butler_model: str = "qwen-plus"
    # Forced offline; the Butler also falls back on a missing key or a failed call.
    butler_offline: bool = False
    butler_max_tool_iterations: int = 6
    butler_request_timeout_seconds: float = 30.0
    butler_memory_limit: int = 40
    # The Plan screen's ask box. Far shorter than the Butler's own timeout above,
    # because the two are waited on differently: a conversation may take its time
    # and shows tokens arriving, where this one holds a screen of live figures
    # still and has nothing to show while it does.
    day_plan_interpret_timeout_seconds: float = 6.0
    # ── The day planner's relevance pass ──────────────────────────────────────
    # Off, and off is the whole product as it stands: the planner narrows a
    # search by matching a word against the cuisines OpenStreetMap recorded,
    # which is two dozen words for the whole city. "satay", "nasi lemak", "bak
    # kut teh" and "beef" are none of them, and every one of those searches
    # hands back nothing. On, the model reads the request against the places
    # actually in range and says which of them answer it — a call per search,
    # which is why this is a decision somebody makes rather than a default.
    #
    # Off must be indistinguishable from this feature not existing: the same
    # filter, the same latency, no call, no quota. See ``find_places``.
    plan_search_llm_enabled: bool = False
    # Shorter than the ask box's, and for the reason ``routing_timeout_seconds``
    # is short: this one sits on the critical path of a list the user is waiting
    # to read, and the fallback below it is a filter that costs nothing.
    plan_search_llm_timeout_seconds: float = 4.0

    # Voice and camera capture. Off means the affordances stay hidden rather
    # than pretending to work; the adapters behind them are chosen in the
    # adapter registry, not here.
    capture_receipt_enabled: bool = True
    capture_voice_enabled: bool = True
    capture_max_bytes: int = 8 * 1024 * 1024

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

    @property
    def checkpointer_dsn(self) -> str:
        """LangGraph's Postgres checkpointer runs on psycopg3, not asyncpg.

        Same database, second driver: the SQLAlchemy dialect suffix has to go.
        """
        return self.database_url.replace("+asyncpg", "").replace("+psycopg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
