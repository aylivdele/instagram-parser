from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_user_id
from app.repositories.account_repository import AccountRepository
from app.repositories.user_competitor_repository import UserCompetitorRepository

router = APIRouter()


class CompetitorRequest(BaseModel):
    username: str
    folder_id: int | None = None


@router.post("/competitors")
async def add_competitor(
    request: CompetitorRequest,
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):
    account_repo = AccountRepository(session)
    user_comp_repo = UserCompetitorRepository(session)

    account = await account_repo.get_or_create(request.username)

    await user_comp_repo.get_or_add(user_id, account.id, folder_id=request.folder_id)

    return {
        "success": True,
        "status": "ok"
    }


@router.get("/competitors")
async def list_competitors(
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):
    user_comp_repo = UserCompetitorRepository(session)
    accounts = await user_comp_repo.get_user_accounts(user_id)
    dto_accounts = [({
                "username": username,
                "avgViews": avg_reels_views_per_hour,
                "avgLikes": avg_posts_views_per_hour,
                "folderId": folder_id
            }) for username, avg_reels_views_per_hour, avg_posts_views_per_hour, folder_id in accounts]
    return {
        "success": True,
        "data": dto_accounts
    }


@router.delete("/competitors/{username}")
async def delete_competitor(
    username: str,
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):
    account_repo = AccountRepository(session)
    user_comp_repo = UserCompetitorRepository(session)

    account = await account_repo.get_by_username(username)
    if not account:
        return {"success": False, "error": "not_found"}

    await user_comp_repo.remove(user_id, account.id)

    return {"success": True, "status": "deleted"}
