"""MongoDB 异步客户端封装——所有数据库操作均通过此处代理。"""
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from api.config import get_settings


class MongoDB:
    _client: AsyncIOMotorClient | None = None
    _db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        settings = get_settings()
        self._client = AsyncIOMotorClient(settings.mongodb_url)
        self._db = self._client[settings.mongodb_db]

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("MongoDB not connected. Call connect() first.")
        return self._db

    async def ping(self) -> bool:
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False


mongodb = MongoDB()
