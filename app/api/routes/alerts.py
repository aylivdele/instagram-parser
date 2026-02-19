import math
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_user_id
from app.repositories.alert_repository import AlertRepository

router = APIRouter()


@router.get("/alerts")
async def get_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    folder_id: Optional[int] = Query(None),
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):
    repo = AlertRepository(session)

    offset = (page - 1) * page_size
    alerts = await repo.get_alerts_dto(user_id, offset, page_size, folder_id)
    total = await repo.get_count_alerts_by_user_id(user_id, folder_id)
    pages = math.ceil(total / page_size) if total else 1

    return {
        "success": True,
        "data": alerts,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": pages
        }
    }
