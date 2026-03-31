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
        accounts = await self._repo.find_active()
        refreshed_pool: list[PoolAccount] = []

        for acc in accounts:
            refreshed = await self._refresh_account_state(acc)
            if refreshed is None:
                continue

            credits, refreshed_cookie = refreshed
            if credits.get("total_credits", 0) > 0 or credits.get("free_songs", 0) > 0:
                refreshed_pool.append(
                    PoolAccount(
                        account_name=acc.account_name,
                        cookie=refreshed_cookie,
                        total_credits=credits.get("total_credits", 0),
                        free_songs=credits.get("free_songs", 0),
                    )
                )
                if len(refreshed_pool) >= self._settings.pool_max_size:
                    break

        await self._rebuild_pool(refreshed_pool)
        logger.info(f"Account pool initialized with {len(self._pool)} accounts.")

    async def shutdown(self) -> None:
        async with self._lock:
            account_names = [acc.account_name for acc in self._pool]
            for acc in self._pool:
                if acc.in_use:
                    logger.warning(f"Account {acc.account_name} still in use during shutdown.")
            self._pool.clear()

        for account_name in account_names:
            await self._repo.set_in_pool(account_name, False)

    async def _fetch_account_state(self, cookie: str) -> tuple[dict, str]:
        async with SongsGen(cookie) as gen:
            credits = await gen.get_limit_left()
            refreshed_cookie = gen.export_cookie_string()
            return credits, refreshed_cookie

    async def _refresh_account_state(self, acc: AccountInDB) -> tuple[dict, str] | None:
        try:
            credits, refreshed_cookie = await self._fetch_account_state(acc.cookie)
            await self._repo.update_credit(acc.account_name, credits)
            await self._repo.update_cookie(acc.account_name, refreshed_cookie)
            acc.cookie = refreshed_cookie
            return credits, refreshed_cookie
        except Exception as exc:
            logger.warning(f"Failed to refresh credits for {acc.account_name}: {exc}")
            await self._repo.set_active(acc.account_name, False)
            return None

    async def _rebuild_pool(self, refreshed_accounts: list[PoolAccount]) -> None:
        await self._repo.clear_all_pool_flags()

        async with self._lock:
            current_by_name = {acc.account_name: acc for acc in self._pool}
            merged_pool: deque[PoolAccount] = deque()
            merged_names: set[str] = set()

            for fresh in refreshed_accounts:
                existing = current_by_name.get(fresh.account_name)
                if existing:
                    existing.cookie = fresh.cookie
                    existing.total_credits = fresh.total_credits
                    existing.free_songs = fresh.free_songs
                    merged_pool.append(existing)
                else:
                    merged_pool.append(fresh)
                merged_names.add(fresh.account_name)

            # Keep in-flight reservations alive even if they are temporarily absent.
            for existing in self._pool:
                if existing.in_use and existing.account_name not in merged_names:
                    merged_pool.append(existing)
                    merged_names.add(existing.account_name)

            self._pool = merged_pool
            account_names = [acc.account_name for acc in self._pool]

        for account_name in account_names:
            await self._repo.set_in_pool(account_name, True)

    async def _sync_pool_account(self, account_name: str, cookie: str, credits: dict) -> None:
        has_credit = credits.get("total_credits", 0) > 0 or credits.get("free_songs", 0) > 0
        should_mark_in_pool = False
        should_mark_out_of_pool = False

        async with self._lock:
            existing = next((acc for acc in self._pool if acc.account_name == account_name), None)

            if existing:
                existing.cookie = cookie
                existing.total_credits = credits.get("total_credits", 0)
                existing.free_songs = credits.get("free_songs", 0)

                if existing.has_credit or existing.in_use:
                    should_mark_in_pool = True
                else:
                    self._pool = deque(acc for acc in self._pool if acc.account_name != account_name)
                    should_mark_out_of_pool = True

            elif has_credit and len(self._pool) < self._settings.pool_max_size:
                self._pool.append(
                    PoolAccount(
                        account_name=account_name,
                        cookie=cookie,
                        total_credits=credits.get("total_credits", 0),
                        free_songs=credits.get("free_songs", 0),
                    )
                )
                should_mark_in_pool = True

        if should_mark_in_pool:
            await self._repo.set_in_pool(account_name, True)
        elif should_mark_out_of_pool:
            await self._repo.set_in_pool(account_name, False)

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
        should_replenish = False

        async with self._lock:
            for acc in self._pool:
                if acc.account_name == account_name:
                    if not acc.has_credit:
                        self._pool = deque(item for item in self._pool if item.account_name != account_name)
                        should_replenish = True
                    break

        if should_replenish:
            await self._repo.set_in_pool(account_name, False)
            await self._replenish_pool()

    async def _replenish_pool(self) -> None:
        """Fill the pool back up from active accounts when capacity allows."""
        while True:
            async with self._lock:
                if len(self._pool) >= self._settings.pool_max_size:
                    return
                in_pool_account_names = {a.account_name for a in self._pool}

            accounts = await self._repo.find_active()
            candidates = [a for a in accounts if a.account_name not in in_pool_account_names]
            if not candidates:
                return

            added = False
            for acc in candidates:
                refreshed = await self._refresh_account_state(acc)
                if refreshed is None:
                    continue

                credits, refreshed_cookie = refreshed
                if credits.get("total_credits", 0) > 0 or credits.get("free_songs", 0) > 0:
                    await self._sync_pool_account(acc.account_name, refreshed_cookie, credits)
                    added = True
                    break

            if not added:
                return

    async def check_and_update_after_request(self, account_name: str) -> None:
        """Refresh credits and release the reserved account after a task ends."""
        accounts = await self._repo.find_active()
        acc_in_db = next((a for a in accounts if a.account_name == account_name), None)
        if not acc_in_db:
            async with self._lock:
                self._pool = deque(acc for acc in self._pool if acc.account_name != account_name)
            await self._repo.set_in_pool(account_name, False)
            await self._replenish_pool()
            return

        refreshed = await self._refresh_account_state(acc_in_db)
        if refreshed is None:
            async with self._lock:
                self._pool = deque(acc for acc in self._pool if acc.account_name != account_name)
            await self._repo.set_in_pool(account_name, False)
            await self._replenish_pool()
            return

        credits, refreshed_cookie = refreshed
        await self._sync_pool_account(acc_in_db.account_name, refreshed_cookie, credits)

        async with self._lock:
            pool_acc = next((a for a in self._pool if a.account_name == account_name), None)
            if pool_acc:
                pool_acc.in_use = False

        await self.return_account(account_name)

    async def register_account(self, account_name: str, cookie: str) -> dict:
        """Register or update an account, then synchronize the in-memory pool."""
        credits, refreshed_cookie = await self._fetch_account_state(cookie)
        account = AccountInDB(
            account_name=account_name,
            cookie=refreshed_cookie,
            total_credits=credits.get("total_credits", 0),
            free_songs=credits.get("free_songs", 0),
            web_v4_gens=credits.get("web_v4_gens", 0),
            mobile_v4_gens=credits.get("mobile_v4_gens", 0),
            is_active=True,
            last_checked=None,
        )
        await self._repo.upsert(account)
        await self._sync_pool_account(account_name, refreshed_cookie, credits)
        await self._replenish_pool()
        return credits

    async def refresh_account_session(self, acc: AccountInDB) -> bool:
        """Refresh one account's auth cookies and sync DB plus in-memory pool."""
        refreshed = await self._refresh_account_state(acc)
        if refreshed is None:
            async with self._lock:
                self._pool = deque(item for item in self._pool if item.account_name != acc.account_name)
            await self._repo.set_in_pool(acc.account_name, False)
            return False

        credits, refreshed_cookie = refreshed
        await self._sync_pool_account(acc.account_name, refreshed_cookie, credits)
        return True

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
