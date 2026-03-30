"""健康检查路由。"""
from fastapi import APIRouter

from api.db.mongodb import mongodb
from api.services.pool_manager import pool_manager

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check() -> dict:
    """返回服务健康状态、数据库连接状态、账号池状态。"""
    mongo_ok = await mongodb.ping()
    pool_status = await pool_manager.get_pool_status()
    return {
        "status": "ok" if mongo_ok else "degraded",
        "mongodb": "connected" if mongo_ok else "disconnected",
        "pool": pool_status,
    }
