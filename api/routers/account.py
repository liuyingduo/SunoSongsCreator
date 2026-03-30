"""账号管理路由——注册账号、查询账号、删除账号。"""
import logging

from fastapi import APIRouter, HTTPException, status

from api.db.mongodb import mongodb
from api.models.account import AccountCreate, AccountRepository, AccountResponse
from api.services.pool_manager import pool_manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def register_account(payload: AccountCreate) -> AccountResponse:
    """
    注册（上传）账号：
    - 保存邮箱与 Cookie 到 MongoDB
    - 立即查询该账号的余额
    - 视余额情况决定是否加入可用账号池
    """
    repo = AccountRepository(mongodb.db)
    try:
        credits = await pool_manager.register_account(payload.email, payload.cookie)
    except Exception as exc:
        logger.error(f"Failed to register account {payload.email}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to register account: {exc}",
        )

    account_in_db = await repo.find_by_email(payload.email)
    if not account_in_db:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account was not saved correctly.",
        )
    return AccountResponse(**account_in_db.model_dump())


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts() -> list[AccountResponse]:
    """返回数据库中所有已注册的账号（不含 Cookie）。"""
    repo = AccountRepository(mongodb.db)
    accounts = await repo.find_all()
    return [AccountResponse(**acc.model_dump()) for acc in accounts]


@router.delete("/accounts/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(email: str) -> None:
    """删除指定邮箱的账号，同时从池中移除。"""
    repo = AccountRepository(mongodb.db)
    deleted = await repo.delete_by_email(email)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account with email '{email}' not found.",
        )
    logger.info(f"Deleted account: {email}")


@router.get("/accounts/pool/status")
async def pool_status() -> dict:
    """返回当前账号池的详细状态。"""
    return await pool_manager.get_pool_status()
