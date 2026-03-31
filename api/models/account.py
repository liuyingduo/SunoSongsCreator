"""账号数据模型——对应 MongoDB accounts 集合。"""
from datetime import datetime

from pydantic import BaseModel, Field


class AccountBase(BaseModel):
    account_name: str
    cookie: str


class AccountCreate(AccountBase):
    pass


class AccountInDB(AccountBase):
    total_credits: int = 0
    free_songs: int = 0
    web_v4_gens: int = 0
    mobile_v4_gens: int = 0
    is_active: bool = True
    is_in_pool: bool = False
    last_checked: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def has_credit(self) -> bool:
        return self.total_credits > 0 or self.free_songs > 0


class AccountResponse(BaseModel):
    account_name: str
    total_credits: int
    free_songs: int
    web_v4_gens: int
    mobile_v4_gens: int
    is_active: bool
    is_in_pool: bool
    last_checked: datetime | None
    created_at: datetime
    updated_at: datetime


class AccountRepository:
    _collection_name = "accounts"

    def __init__(self, db) -> None:
        self._db = db

    @property
    def col(self):
        return self._db[self._collection_name]

    async def upsert(self, account: AccountInDB) -> None:
        account_name = account.account_name
        data = account.model_dump()
        data.pop("account_name")
        await self.col.update_one(
            {"account_name": account_name},
            {"$set": data},
            upsert=True,
        )

    async def find_by_name(self, account_name: str) -> AccountInDB | None:
        doc = await self.col.find_one({"account_name": account_name})
        if doc is None:
            return None
        doc.pop("_id", None)
        return AccountInDB(**doc)

    async def find_all(self) -> list[AccountInDB]:
        cursor = self.col.find({})
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(AccountInDB(**doc))
        return results

    async def find_active(self) -> list[AccountInDB]:
        cursor = self.col.find({"is_active": True})
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(AccountInDB(**doc))
        return results

    async def delete_by_name(self, account_name: str) -> bool:
        result = await self.col.delete_one({"account_name": account_name})
        return result.deleted_count > 0

    async def update_credit(self, account_name: str, credits: dict) -> None:
        await self.col.update_one(
            {"account_name": account_name},
            {
                "$set": {
                    "total_credits": credits.get("total_credits", 0),
                    "free_songs": credits.get("free_songs", 0),
                    "web_v4_gens": credits.get("web_v4_gens", 0),
                    "mobile_v4_gens": credits.get("mobile_v4_gens", 0),
                    "updated_at": datetime.utcnow(),
                }
            },
        )

    async def update_cookie(self, account_name: str, cookie: str) -> None:
        await self.col.update_one(
            {"account_name": account_name},
            {"$set": {"cookie": cookie, "updated_at": datetime.utcnow()}},
        )

    async def set_in_pool(self, account_name: str, in_pool: bool) -> None:
        await self.col.update_one(
            {"account_name": account_name},
            {"$set": {"is_in_pool": in_pool, "updated_at": datetime.utcnow()}},
        )

    async def set_active(self, account_name: str, active: bool) -> None:
        await self.col.update_one(
            {"account_name": account_name},
            {"$set": {"is_active": active, "updated_at": datetime.utcnow()}},
        )

    async def clear_all_pool_flags(self) -> None:
        await self.col.update_many({}, {"$set": {"is_in_pool": False}})
