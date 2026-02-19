from sqlalchemy import select
from app.db.models import Alert, InstagramAccount, InstagramPost
from sqlalchemy.ext.asyncio import AsyncSession


class AlertRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists(self, user_id: str, post_id: int):
        result = await self.session.execute(
            select(Alert)
            .where(Alert.user_id == user_id, Alert.post_id == post_id)
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        user_id: str,
        post_id: int,
        views: int,
        views_per_hour: float,
        avg_views_per_hour: float,
        growth_rate: float
    ):
        alert = Alert(
            user_id=user_id,
            post_id=post_id,
            views=views,
            views_per_hour=views_per_hour,
            avg_views_per_hour=avg_views_per_hour,
            growth_rate=growth_rate,
        )
        self.session.add(alert)
        await self.session.commit()
        return alert
    
    async def get_alerts_dto(self, user_id: str):
        result = await self.session.execute(
            select(
                Alert,
                InstagramPost.url,
                InstagramAccount.username
            )
            .join(
                InstagramPost,
                Alert.post_id == InstagramPost.id
            )
            .join(
                InstagramAccount,
                InstagramPost.account_id == InstagramAccount.id
            )
            .where(Alert.user_id == user_id)
            .order_by(Alert.detected_at.desc())
        )

        alerts = []

        for alert, post_url, username in result.all():
            alerts.append({
                "username": username,
                "growth": alert.growth_rate,
                "currentViews": alert.views,
                "timestamp": alert.detected_at,
                "postUrl": post_url
            })
        
        return alerts
