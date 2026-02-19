from typing import Optional
from sqlalchemy import func, select
from app.db.models import Alert, Folder, InstagramAccount, InstagramPost, UserCompetitor
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
    async def get_count_alerts_by_user_id(self, user_id: str, folder_id: Optional[int]):
        count_query = (
            select(func.count())
            .select_from(Alert)
            .join(InstagramPost, Alert.post_id == InstagramPost.id)
            .join(InstagramAccount, InstagramPost.account_id == InstagramAccount.id)
            .join(
                UserCompetitor,
                (UserCompetitor.account_id == InstagramAccount.id)
                & (UserCompetitor.user_id == user_id)
            )
            .where(Alert.user_id == user_id)
        )

        if folder_id is not None:
            count_query = count_query.where(UserCompetitor.folder_id == folder_id)

        total_result = await self.session.execute(count_query)
        return total_result.scalar_one()
    
    async def get_alerts_dto(self, user_id: str, offset: int, limit: int, folder_id: Optional[int]):
        data_query = (select(
                Alert,
                InstagramPost.url,
                InstagramAccount.username,
                UserCompetitor.folder_id.label("folder_id")
            )
            .join(
                InstagramPost,
                Alert.post_id == InstagramPost.id
            )
            .join(
                InstagramAccount,
                InstagramPost.account_id == InstagramAccount.id
            )
            .join(
                UserCompetitor,
                (UserCompetitor.account_id == InstagramAccount.id)
                & (UserCompetitor.user_id == user_id)
            )
            .where(Alert.user_id == user_id))
        if folder_id is not None:
            data_query = data_query.where(UserCompetitor.folder_id == folder_id)

        result = await self.session.execute(
            data_query
            .order_by(Alert.detected_at.desc())    
            .offset(offset)
            .limit(limit)
        )

        alerts = []

        for alert, post_url, username, folder_id in result.all():
            alerts.append({
                "username": username,
                "folderId": folder_id,
                "growth": alert.growth_rate,
                "currentViews": alert.views,
                "timestamp": alert.detected_at,
                "postUrl": post_url
            })
        
        return alerts
