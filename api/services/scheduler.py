"""每日调度服务——每天定时刷新所有账号余额。"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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

        trigger = CronTrigger(
            hour=settings.scheduler_hour,
            minute=settings.scheduler_minute,
        )
        self._scheduler.add_job(
            self._refresh_all_accounts,
            trigger,
            id="daily_credit_refresh",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        logger.info(
            f"Scheduler started. Daily refresh scheduled at "
            f"{settings.scheduler_hour:02d}:{settings.scheduler_minute:02d}."
        )

    def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler stopped.")

    async def _refresh_all_accounts(self) -> None:
        """每天定时刷新所有账号余额并同步数据库。"""
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

    async def _refresh_single(self, repo: AccountRepository, acc: AccountInDB) -> None:
        try:
            import threading
            from suno import SongsGen

            def _sync_check() -> dict:
                gen = SongsGen(acc.cookie)
                return gen.get_limit_left()

            credits = await asyncio.get_running_loop().run_in_executor(
                None, _sync_check
            )
            await repo.update_credit(acc.email, credits)
            logger.info(f"Refreshed {acc.email}: credits={credits.get('total_credits', 0)}")
        except Exception as exc:
            logger.warning(f"Failed to refresh {acc.email}: {exc}")
            await repo.set_active(acc.email, False)


scheduler_service = SchedulerService()
