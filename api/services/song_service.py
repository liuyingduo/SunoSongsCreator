"""Song generation service that submits jobs to Suno and polls for results."""

import asyncio
import logging

from suno import SongsGen

from api.config import get_settings
from api.models.task import TaskInDB, TaskRepository, TaskStatus
from api.services.pool_manager import PoolExhaustedError, PoolAccount, pool_manager

logger = logging.getLogger(__name__)


async def _generate_with_account(task: TaskInDB, account: PoolAccount, timeout_seconds: int) -> dict:
    async with SongsGen(account.cookie) as gen:
        request_ids = await gen.create_songs(
            prompt=task.prompt,
            tags=task.tags,
            title=task.title or "",
            make_instrumental=task.make_instrumental,
            is_custom=task.is_custom,
            model=task.model,
        )
        logger.info(f"[{task.task_id}] Submitted to Suno, ids: {request_ids}")

        start_time = asyncio.get_event_loop().time()
        while True:
            if (asyncio.get_event_loop().time() - start_time) > timeout_seconds:
                raise asyncio.TimeoutError()

            result = await gen.get_songs_output(request_ids)
            if result:
                return result

            await asyncio.sleep(5)


async def create_song_task(task: TaskInDB) -> None:
    """Execute one generation task and persist the final task state."""
    settings = get_settings()
    task_repo = TaskRepository(pool_manager._repo._db)

    try:
        await task_repo.update_status(task.task_id, TaskStatus.RUNNING)

        try:
            if task.account_name:
                account = await pool_manager.get_reserved_account(task.account_name)
            else:
                account = await pool_manager.reserve_account()
                await task_repo.assign_account(task.task_id, account.account_name)
                task.account_name = account.account_name

            logger.info(f"[{task.task_id}] Using account: {account.account_name}")
            result = await _generate_with_account(task, account, settings.song_request_timeout)
            await task_repo.update_status(task.task_id, TaskStatus.SUCCESS, result=result)
            logger.info(f"[{task.task_id}] Song generated successfully.")

        except PoolExhaustedError:
            await task_repo.update_status(
                task.task_id,
                TaskStatus.FAILED,
                error="No available accounts in the pool.",
            )
            logger.error(f"[{task.task_id}] No available accounts.")

    except asyncio.TimeoutError:
        await task_repo.update_status(task.task_id, TaskStatus.FAILED, error="Generation timeout.")
        logger.error(f"[{task.task_id}] Generation timeout.")
    except Exception as exc:
        await task_repo.update_status(task.task_id, TaskStatus.FAILED, error=str(exc))
        logger.exception(f"[{task.task_id}] Generation failed.")
