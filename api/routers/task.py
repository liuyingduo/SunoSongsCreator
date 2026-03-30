"""歌曲生成任务路由——创建任务、查询任务状态。"""
import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from api.db.mongodb import mongodb
from api.models.task import TaskCreate, TaskInDB, TaskRepository, TaskResponse, TaskStatus
from api.services.pool_manager import pool_manager
from api.services.song_service import create_song_task

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(payload: TaskCreate) -> TaskResponse:
    """
    创建歌曲生成任务：
    - 生成唯一 task_id
    - 将任务写入数据库（状态 = pending）
    - 立即在后台异步执行生成逻辑
    - 返回任务信息（前端可凭 task_id 轮询状态）
    """
    repo = TaskRepository(mongodb.db)

    task_id = str(uuid.uuid4())
    task = TaskInDB(task_id=task_id, **payload.model_dump())
    await repo.create(task)
    logger.info(f"Created task {task_id} with prompt: {payload.prompt[:50]}")

    asyncio.create_task(_execute_and_sync(task))

    return TaskResponse(**task.model_dump())


async def _execute_and_sync(task: TaskInDB) -> None:
    """内部执行任务并在完成后同步账号池状态。"""
    try:
        await create_song_task(task)
    finally:
        if task.account_name:
            await pool_manager.check_and_update_after_request(task.account_name)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    """根据 task_id 查询任务当前状态。"""
    repo = TaskRepository(mongodb.db)
    task = await repo.find_by_id(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found.",
        )
    return TaskResponse(**task.model_dump())


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks() -> list[TaskResponse]:
    """返回所有任务（按创建时间倒序）。"""
    repo = TaskRepository(mongodb.db)
    tasks = await repo.find_all()
    return [TaskResponse(**t.model_dump()) for t in tasks]
