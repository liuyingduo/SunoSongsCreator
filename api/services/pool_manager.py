"""账号池管理服务——核心调度逻辑，维护可用账号队列。"""
import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass

from suno import SongsGen

from api.config import get_settings
from api.db.mongodb import mongodb
from api.models.account import AccountInDB, AccountRepository

logger = logging.getLogger(__name__)


@dataclass
class PoolAccount:
    email: str
    cookie: str
    total_credits: int = 0
    free_songs: int = 0
    in_use: bool = False

    @property
    def has_credit(self) -> bool:
        return self.total_credits > 0 or self.free_songs > 0


class PoolManager:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._pool: deque[PoolAccount] = deque()
        self._lock = asyncio.Lock()
        self.__repo: AccountRepository | None = None

    @property
    def _repo(self) -> AccountRepository:
        if self.__repo is None:
            self.__repo = AccountRepository(mongodb.db)
        return self.__repo

    async def initialize(self) -> None:
        logger.info("Initializing account pool...")
        accounts = await self._repo.find_active()
        for acc in accounts:
            if acc.has_credit and not acc.is_in_pool:
                credits = await self._refresh_account_credits(acc)
                if credits and (credits.get("total_credits", 0) > 0 or credits.get("free_songs", 0) > 0):
                    await self._add_to_pool(PoolAccount(
                        email=acc.email,
                        cookie=acc.cookie,
                        total_credits=credits.get("total_credits", 0),
                        free_songs=credits.get("free_songs", 0),
                    ))
        logger.info(f"Account pool initialized with {len(self._pool)} accounts.")

    async def shutdown(self) -> None:
        async with self._lock:
            for acc in self._pool:
                if acc.in_use:
                    logger.warning(f"Account {acc.email} still in use during shutdown.")
            self._pool.clear()
            await self._repo.find_all()  # sync pool state to db

    async def _refresh_account_credits(self, acc: AccountInDB) -> dict | None:
        try:
            loop = asyncio.get_running_loop()

            def _sync_check() -> dict:
                gen = SongsGen(acc.cookie)
                return gen.get_limit_left()

            credits = await loop.run_in_executor(None, _sync_check)
            await self._repo.update_credit(acc.email, credits)
            return credits
        except Exception as exc:
            logger.warning(f"Failed to refresh credits for {acc.email}: {exc}")
            await self._repo.set_active(acc.email, False)
            return None

    async def _add_to_pool(self, account: PoolAccount) -> None:
        if len(self._pool) >= self._settings.pool_max_size:
            return
        if any(a.email == account.email for a in self._pool):
            return
        self._pool.append(account)
        await self._repo.set_in_pool(account.email, True)
        logger.info(f"Added {account.email} to pool (credits: {account.total_credits})")

    async def _remove_from_pool(self, email: str) -> None:
        self._pool = deque(a for a in self._pool if a.email != email)
        await self._repo.set_in_pool(email, False)
        logger.info(f"Removed {email} from pool.")

    @asynccontextmanager
    async def acquire(self):
        """从池中获取一个可用账号，使用完毕后交还。"""
        account: PoolAccount | None = None
        async with self._lock:
            for acc in self._pool:
                if acc.has_credit and not acc.in_use:
                    account = acc
                    acc.in_use = True
                    break

        if account is None:
            raise PoolExhaustedError("No available accounts in the pool.")

        try:
            yield account
        finally:
            account.in_use = False

    async def return_account(self, email: str) -> None:
        async with self._lock:
            for acc in self._pool:
                if acc.email == email:
                    if not acc.has_credit:
                        await self._remove_from_pool(email)
                        await self._replenish_pool()
                    return

    async def _replenish_pool(self) -> None:
        """当池中账号少于最大容量时，从数据库补充。"""
        while len(self._pool) < self._settings.pool_max_size:
            accounts = await self._repo.find_active()
            in_pool_emails = {a.email for a in self._pool}
            candidates = [a for a in accounts if a.email not in in_pool_emails]
            if not candidates:
                break
            for acc in candidates:
                credits = await self._refresh_account_credits(acc)
                if credits and (credits.get("total_credits", 0) > 0 or credits.get("free_songs", 0) > 0):
                    await self._add_to_pool(PoolAccount(
                        email=acc.email,
                        cookie=acc.cookie,
                        total_credits=credits.get("total_credits", 0),
                        free_songs=credits.get("free_songs", 0),
                    ))
                    break

    async def check_and_update_after_request(self, email: str) -> None:
        """请求结束后检查余额并更新池。"""
        accounts = await self._repo.find_active()
        acc_in_db = next((a for a in accounts if a.email == email), None)
        if not acc_in_db:
            await self._remove_from_pool(email)
            await self._replenish_pool()
            return

        credits = await self._refresh_account_credits(acc_in_db)
        async with self._lock:
            pool_acc = next((a for a in self._pool if a.email == email), None)
            if pool_acc:
                pool_acc.total_credits = credits.get("total_credits", 0) if credits else 0
                pool_acc.free_songs = credits.get("free_songs", 0) if credits else 0
                if not pool_acc.has_credit:
                    await self._remove_from_pool(email)
                    await self._replenish_pool()

    async def register_account(self, email: str, cookie: str) -> dict:
        """注册/更新账号，写入数据库并补充池。"""
        gen = SongsGen(cookie)
        credits = gen.get_limit_left()
        account = AccountInDB(
            email=email,
            cookie=cookie,
            total_credits=credits.get("total_credits", 0),
            free_songs=credits.get("free_songs", 0),
            web_v4_gens=credits.get("web_v4_gens", 0),
            mobile_v4_gens=credits.get("mobile_v4_gens", 0),
            is_active=True,
            last_checked=None,
        )
        await self._repo.upsert(account)
        await self._replenish_pool()
        return credits

    async def get_pool_status(self) -> dict:
        async with self._lock:
            return {
                "pool_size": len(self._pool),
                "max_size": self._settings.pool_max_size,
                "accounts": [
                    {"email": a.email, "total_credits": a.total_credits,
                     "free_songs": a.free_songs, "in_use": a.in_use}
                    for a in self._pool
                ],
            }


class PoolExhaustedError(Exception):
    pass


pool_manager = PoolManager()
