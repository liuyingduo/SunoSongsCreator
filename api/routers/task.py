"""Task routes for creating and querying song generation jobs."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from api.db.mongodb import mongodb
from api.models.task import TaskCreate, TaskInDB, TaskRepository, TaskResponse
from api.services.pool_manager import PoolExhaustedError, pool_manager
from api.services.song_service import create_song_task

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(payload: TaskCreate) -> TaskResponse:
    """Create a task after reserving an account up front."""
    repo = TaskRepository(mongodb.db)

    try:
        reserved_account = await pool_manager.reserve_account()
    except PoolExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    task_id = str(uuid.uuid4())
    task = TaskInDB(
        task_id=task_id,
        account_name=reserved_account.account_name,
        **payload.model_dump(),
    )

    try:
        await repo.create(task)
        logger.info(
            f"Created task {task_id} with prompt: {payload.prompt[:50]} "
            f"using reserved account {reserved_account.account_name}"
        )
        asyncio.create_task(_execute_and_sync(task))
        return TaskResponse(**task.model_dump())
    except Exception:
        await pool_manager.release_account(reserved_account.account_name)
        raise


async def _execute_and_sync(task: TaskInDB) -> None:
    """Run the task and always refresh/release the reserved account afterward."""
    try:
        await create_song_task(task)
    finally:
        if task.account_name:
            await pool_manager.check_and_update_after_request(task.account_name)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    """Return the current state for one task."""
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
    """Return all tasks ordered by creation time descending."""
    repo = TaskRepository(mongodb.db)
    tasks = await repo.find_all()
    return [TaskResponse(**t.model_dump()) for t in tasks]
