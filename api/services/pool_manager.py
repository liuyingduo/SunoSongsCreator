"""Account pool management for song generation workers."""

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
    account_name: str
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
        await self._repo.clear_all_pool_flags()
        accounts = await self._repo.find_active()
        for acc in accounts:
            if acc.has_credit:
                credits = await self._refresh_account_credits(acc)
                if credits and (credits.get("total_credits", 0) > 0 or credits.get("free_songs", 0) > 0):
                    await self._add_to_pool(
                        PoolAccount(
                            account_name=acc.account_name,
                            cookie=acc.cookie,
                            total_credits=credits.get("total_credits", 0),
                            free_songs=credits.get("free_songs", 0),
                        )
                    )
        logger.info(f"Account pool initialized with {len(self._pool)} accounts.")

    async def shutdown(self) -> None:
        async with self._lock:
            for acc in self._pool:
                if acc.in_use:
                    logger.warning(f"Account {acc.account_name} still in use during shutdown.")
                await self._repo.set_in_pool(acc.account_name, False)
            self._pool.clear()

    async def _refresh_account_credits(self, acc: AccountInDB) -> dict | None:
        try:
            async with SongsGen(acc.cookie) as gen:
                credits = await gen.get_limit_left()
                await self._repo.update_credit(acc.account_name, credits)
                return credits
        except Exception as exc:
            logger.warning(f"Failed to refresh credits for {acc.account_name}: {exc}")
            await self._repo.set_active(acc.account_name, False)
            return None

    async def _add_to_pool(self, account: PoolAccount) -> None:
        if len(self._pool) >= self._settings.pool_max_size:
            return
        if any(a.account_name == account.account_name for a in self._pool):
            return
        self._pool.append(account)
        await self._repo.set_in_pool(account.account_name, True)
        logger.info(f"Added {account.account_name} to pool (credits: {account.total_credits})")

    async def _remove_from_pool(self, account_name: str) -> None:
        self._pool = deque(a for a in self._pool if a.account_name != account_name)
        await self._repo.set_in_pool(account_name, False)
        logger.info(f"Removed {account_name} from pool.")

    async def reserve_account(self) -> PoolAccount:
        """Reserve an available account so task submission can fail fast."""
        async with self._lock:
            for acc in self._pool:
                if acc.has_credit and not acc.in_use:
                    acc.in_use = True
                    return acc
        raise PoolExhaustedError("No available accounts in the pool.")

    async def get_reserved_account(self, account_name: str) -> PoolAccount:
        async with self._lock:
            for acc in self._pool:
                if acc.account_name == account_name:
                    return acc
        raise PoolExhaustedError(f"Reserved account '{account_name}' is unavailable.")

    async def release_account(self, account_name: str) -> None:
        async with self._lock:
            for acc in self._pool:
                if acc.account_name == account_name:
                    acc.in_use = False
                    return

    @asynccontextmanager
    async def acquire(self):
        """Compatibility helper for callers that want a scoped reservation."""
        account = await self.reserve_account()
        try:
            yield account
        finally:
            await self.release_account(account.account_name)

    async def return_account(self, account_name: str) -> None:
        async with self._lock:
            for acc in self._pool:
                if acc.account_name == account_name:
                    if not acc.has_credit:
                        await self._remove_from_pool(account_name)
                        await self._replenish_pool()
                    return

    async def _replenish_pool(self) -> None:
        """Fill the pool back up from active accounts when capacity allows."""
        while len(self._pool) < self._settings.pool_max_size:
            accounts = await self._repo.find_active()
            in_pool_account_names = {a.account_name for a in self._pool}
            candidates = [a for a in accounts if a.account_name not in in_pool_account_names]
            if not candidates:
                break
            for acc in candidates:
                credits = await self._refresh_account_credits(acc)
                if credits and (credits.get("total_credits", 0) > 0 or credits.get("free_songs", 0) > 0):
                    await self._add_to_pool(
                        PoolAccount(
                            account_name=acc.account_name,
                            cookie=acc.cookie,
                            total_credits=credits.get("total_credits", 0),
                            free_songs=credits.get("free_songs", 0),
                        )
                    )
                    break

    async def check_and_update_after_request(self, account_name: str) -> None:
        """Refresh credits and release the reserved account after a task ends."""
        accounts = await self._repo.find_active()
        acc_in_db = next((a for a in accounts if a.account_name == account_name), None)
        if not acc_in_db:
            await self._remove_from_pool(account_name)
            await self._replenish_pool()
            return

        credits = await self._refresh_account_credits(acc_in_db)
        async with self._lock:
            pool_acc = next((a for a in self._pool if a.account_name == account_name), None)
            if pool_acc:
                pool_acc.total_credits = credits.get("total_credits", 0) if credits else 0
                pool_acc.free_songs = credits.get("free_songs", 0) if credits else 0
                pool_acc.in_use = False
                if not pool_acc.has_credit:
                    await self._remove_from_pool(account_name)
                    await self._replenish_pool()

    async def register_account(self, account_name: str, cookie: str) -> dict:
        """Register or update an account, then attempt to replenish the pool."""
        async with SongsGen(cookie) as gen:
            credits = await gen.get_limit_left()
            account = AccountInDB(
                account_name=account_name,
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
                    {
                        "account_name": a.account_name,
                        "total_credits": a.total_credits,
                        "free_songs": a.free_songs,
                        "in_use": a.in_use,
                    }
                    for a in self._pool
                ],
            }


class PoolExhaustedError(Exception):
    pass


pool_manager = PoolManager()
