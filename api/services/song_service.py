"""歌曲生成服务——封装 SongsGen 调用，处理异步生成流程。"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from suno import SongsGen

from api.config import get_settings
from api.models.task import TaskInDB, TaskRepository, TaskStatus
from api.services.pool_manager import PoolExhaustedError, pool_manager

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=8)


async def _generate_song_sync(cookie: str, prompt: str, **kwargs) -> dict:
    """在后台线程中同步执行歌曲生成（避免阻塞事件循环）。"""
    def _run():
        gen = SongsGen(cookie)
        return gen.get_songs(prompt=prompt, **kwargs)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _run)


async def create_song_task(task: TaskInDB) -> None:
    """
    执行歌曲生成任务：从池中取账号，调用生成接口，更新任务状态。
    """
    settings = get_settings()
    task_repo = TaskRepository(pool_manager._repo._db)

    try:
        await task_repo.update_status(task.task_id, TaskStatus.RUNNING)

        try:
            async with pool_manager.acquire() as account:
                await task_repo.assign_account(task.task_id, account.email)
                logger.info(f"[{task.task_id}] Using account: {account.email}")

                kwargs = {}
                if task.title:
                    kwargs["title"] = task.title
                if task.tags:
                    kwargs["tags"] = task.tags
                kwargs["make_instrumental"] = task.make_instrumental
                kwargs["is_custom"] = task.is_custom

                result = await asyncio.wait_for(
                    _generate_song_sync(account.cookie, task.prompt, **kwargs),
                    timeout=settings.song_request_timeout,
                )

                await task_repo.update_status(task.task_id, TaskStatus.SUCCESS, result=result)
                logger.info(f"[{task.task_id}] Song generated successfully.")

        except PoolExhaustedError:
            await task_repo.update_status(task.task_id, TaskStatus.FAILED,
                                          error="No available accounts in the pool.")
            logger.error(f"[{task.task_id}] No available accounts.")

    except asyncio.TimeoutError:
        await task_repo.update_status(task.task_id, TaskStatus.FAILED,
                                      error="Generation timeout.")
        logger.error(f"[{task.task_id}] Generation timeout.")
    except Exception as exc:
        await task_repo.update_status(task.task_id, TaskStatus.FAILED, error=str(exc))
        logger.exception(f"[{task.task_id}] Generation failed.")
