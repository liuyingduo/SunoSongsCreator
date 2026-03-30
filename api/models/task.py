"""任务数据模型——对应 MongoDB tasks 集合。"""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TaskCreate(BaseModel):
    prompt: str
    tags: str | None = None
    title: str | None = None
    make_instrumental: bool = False
    is_custom: bool = False


class TaskInDB(TaskCreate):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    account_email: str | None = None
    result: dict | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    prompt: str
    tags: str | None
    title: str | None
    make_instrumental: bool
    is_custom: bool
    account_email: str | None
    result: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskRepository:
    _collection_name = "tasks"

    def __init__(self, db) -> None:
        self._db = db

    @property
    def col(self):
        return self._db[self._collection_name]

    async def create(self, task: TaskInDB) -> None:
        await self.col.insert_one(task.model_dump())

    async def find_by_id(self, task_id: str) -> TaskInDB | None:
        doc = await self.col.find_one({"task_id": task_id})
        if doc:
            doc.pop("_id", None)
            return TaskInDB(**doc)
        return None

    async def find_all(self) -> list[TaskInDB]:
        cursor = self.col.find({}).sort("created_at", -1)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(TaskInDB(**doc))
        return results

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.utcnow()
        update: dict = {
            "status": status.value if isinstance(status, TaskStatus) else status,
            "updated_at": now,
        }
        if status == TaskStatus.SUCCESS or status == "success":
            update["completed_at"] = now
            update["result"] = result
        if error:
            update["error"] = error
        await self.col.update_one({"task_id": task_id}, {"$set": update})

    async def assign_account(self, task_id: str, email: str) -> None:
        await self.col.update_one(
            {"task_id": task_id},
            {"$set": {"account_email": email, "updated_at": datetime.utcnow()}},
        )
