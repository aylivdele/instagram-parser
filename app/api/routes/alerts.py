from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_user_id
from app.repositories.alert_repository import AlertRepository

router = APIRouter()


@router.get("/alerts")
async def get_alerts(
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):
    repo = AlertRepository(session)
    alerts = await repo.get_alerts_dto(user_id)
    
    return {
        "success": True,
        "data": alerts
    }
