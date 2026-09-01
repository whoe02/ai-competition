"""Schedule Kira's nightly, no-financial-write briefing job."""

from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from kira.config import get_settings
from kira.db.models import User
from kira.db.session import get_sessionmaker
from kira.services.briefings import nightly_briefing
from kira.services.clock import today_for

log = logging.getLogger(__name__)
JOB_ID = "nightly-briefings"


async def run_all_briefings() -> None:
    """Brief every user independently so one malformed account cannot stop others."""
    factory = get_sessionmaker()
    async with factory() as session:
        user_ids = list((await session.execute(select(User.id))).scalars())

    for user_id in user_ids:
        async with factory() as session:
            try:
                user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
                result = await nightly_briefing(session, user, today_for())
                await session.commit()
                log.info(
                    "nightly briefing user=%s date=%s created=%s proposals=%s",
                    user.id,
                    result.on_date,
                    result.created,
                    result.proposal_count,
                )
            except Exception:
                await session.rollback()
                log.exception("nightly briefing failed for user=%s", user_id)


def build_scheduler() -> AsyncIOScheduler:
    """Build, but do not start, the durable KL-time scheduler."""
    settings = get_settings()
    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=settings.scheduler_database_url)},
        timezone=ZoneInfo(settings.worker_timezone),
    )
    scheduler.add_job(
        run_all_briefings,
        CronTrigger(
            hour=settings.worker_hour,
            minute=settings.worker_minute,
            timezone=ZoneInfo(settings.worker_timezone),
        ),
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler


async def serve() -> None:
    logging.basicConfig(level=logging.INFO)
    scheduler = build_scheduler()
    scheduler.start()
    log.info("nightly worker started")
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(serve())
