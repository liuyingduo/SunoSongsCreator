"""账号数据模型——对应 MongoDB accounts 集合。"""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class AccountBase(BaseModel):
    email: EmailStr
    cookie: str = Field(exclude=True)


class AccountCreate(AccountBase):
    pass


class AccountInDB(AccountBase):
    email: EmailStr
    cookie: str = Field(exclude=True)
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
    email: EmailStr
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
        await self.col.update_one(
            {"email": account.email},
            {"$set": account.model_dump(exclude={"email"})},
            upsert=True,
        )

    async def find_by_email(self, email: str) -> AccountInDB | None:
        doc = await self.col.find_one({"email": email})
        if doc:
            doc.pop("_id", None)
            return AccountInDB(**doc)
        return None

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

    async def delete_by_email(self, email: str) -> bool:
        result = await self.col.delete_one({"email": email})
        return result.deleted_count > 0

    async def update_credit(self, email: str, credits: dict) -> None:
        await self.col.update_one(
            {"email": email},
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

    async def set_in_pool(self, email: str, in_pool: bool) -> None:
        await self.col.update_one(
            {"email": email},
            {"$set": {"is_in_pool": in_pool, "updated_at": datetime.utcnow()}},
        )

    async def set_active(self, email: str, active: bool) -> None:
        await self.col.update_one(
            {"email": email},
            {"$set": {"is_active": active, "updated_at": datetime.utcnow()}},
        )
