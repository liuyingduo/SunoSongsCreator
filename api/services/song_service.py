"""歌曲生成服务——封装 SongsGen 调用，处理异步生成流程。"""
import asyncio
import logging

from suno import SongsGen

from api.config import get_settings
from api.models.task import TaskInDB, TaskRepository, TaskStatus
from api.services.pool_manager import PoolExhaustedError, pool_manager

logger = logging.getLogger(__name__)


async def create_song_task(task: TaskInDB) -> None:
    """
    执行歌曲生成任务：
    1. 从池中取账号
    2. 使用异步 SongsGen 提交任务
    3. 异步轮询查询状态
    4. 更新任务状态
    """
    settings = get_settings()
    task_repo = TaskRepository(pool_manager._repo._db)

    try:
        await task_repo.update_status(task.task_id, TaskStatus.RUNNING)

        try:
            async with pool_manager.acquire() as account:
                await task_repo.assign_account(task.task_id, account.account_name)
                logger.info(f"[{task.task_id}] Using account: {account.account_name}")

                # 使用异步上下文管理器管理 SongsGen
                async with SongsGen(account.cookie) as gen:
                    # 步骤 1: 异步提交生成请求
                    request_ids = await gen.create_songs(
                        prompt=task.prompt,
                        tags=task.tags,
                        title=task.title or "",
                        make_instrumental=task.make_instrumental,
                        is_custom=task.is_custom,
                        model=task.model
                    )
                    logger.info(f"[{task.task_id}] Submitted to Suno, ids: {request_ids}")

                    # 步骤 2: 异步轮询状态
                    start_time = asyncio.get_event_loop().time()
                    result = None
                    
                    while True:
                        if (asyncio.get_event_loop().time() - start_time) > settings.song_request_timeout:
                            raise asyncio.TimeoutError()

                        # 异步查询状态
                        result = await gen.get_songs_output(request_ids)
                        
                        if result:
                            break
                        
                        await asyncio.sleep(5)

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
