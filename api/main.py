"""Suno API 服务——FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.db.mongodb import mongodb
from api.routers import account, health, task
from api.services.pool_manager import pool_manager
from api.services.scheduler import scheduler_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongodb.connect()
    await pool_manager.initialize()
    scheduler_service.start()
    yield
    scheduler_service.stop()
    await pool_manager.shutdown()
    await mongodb.disconnect()


app = FastAPI(
    title="SunoSongsCreator API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(account.router, prefix="/api")
app.include_router(task.router, prefix="/api")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
