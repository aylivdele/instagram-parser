from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.repositories.user_repository import UserRepository

router = APIRouter()


class RegisterRequest(BaseModel):
    telegram_chat_id: str | None = None
    user_id: str


@router.post("/register")
async def register(
    request: RegisterRequest,
    session: AsyncSession = Depends(get_session)
):
    repo = UserRepository(session)
    user = await repo.get(request.user_id)

    if not user:
        user = await repo.create(request.user_id, request.telegram_chat_id)

    return {"success": True, "status": "ok", "user_id": user.id}
