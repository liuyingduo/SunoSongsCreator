"""Scheduler service for periodic account maintenance."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from api.config import get_settings
from api.db.mongodb import mongodb
from api.models.account import AccountInDB, AccountRepository
from api.services.pool_manager import pool_manager

logger = logging.getLogger(__name__)


class SchedulerService:
    _scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler()

        daily_trigger = CronTrigger(
            hour=settings.scheduler_hour,
            minute=settings.scheduler_minute,
        )
        self._scheduler.add_job(
            self._refresh_all_accounts,
            daily_trigger,
            id="daily_credit_refresh",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        self._scheduler.add_job(
            self._refresh_all_account_sessions,
            IntervalTrigger(hours=1),
            id="hourly_cookie_refresh",
            replace_existing=True,
            misfire_grace_time=900,
        )
        self._scheduler.start()
        logger.info(
            f"Scheduler started. Daily refresh scheduled at "
            f"{settings.scheduler_hour:02d}:{settings.scheduler_minute:02d}; "
            f"session cookies refresh every hour."
        )

    def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler stopped.")

    async def _refresh_all_accounts(self) -> None:
        """Daily full refresh for credits and the account pool."""
        logger.info("Starting daily account credit refresh...")
        repo = AccountRepository(mongodb.db)
        accounts = await repo.find_active()

        if not accounts:
            logger.info("No active accounts to refresh.")
            return

        refresh_tasks = [self._refresh_single(repo, acc) for acc in accounts]
        await asyncio.gather(*refresh_tasks, return_exceptions=True)
        await pool_manager.initialize()
        logger.info("Daily credit refresh completed.")

    async def _refresh_all_account_sessions(self) -> None:
        """Refresh auth cookies hourly and sync them back to DB and the pool."""
        logger.info("Starting hourly account session refresh...")
        repo = AccountRepository(mongodb.db)
        accounts = await repo.find_active()

        if not accounts:
            logger.info("No active accounts to refresh.")
            return

        refresh_tasks = [pool_manager.refresh_account_session(acc) for acc in accounts]
        await asyncio.gather(*refresh_tasks, return_exceptions=True)
        logger.info("Hourly account session refresh completed.")

    async def _refresh_single(self, repo: AccountRepository, acc: AccountInDB) -> None:
        try:
            from suno import SongsGen

            async with SongsGen(acc.cookie) as gen:
                credits = await gen.get_limit_left()
                await repo.update_credit(acc.account_name, credits)
                logger.info(f"Refreshed {acc.account_name}: credits={credits.get('total_credits', 0)}")
        except Exception as exc:
            logger.warning(f"Failed to refresh {acc.account_name}: {exc}")
            await repo.set_active(acc.account_name, False)


scheduler_service = SchedulerService()
