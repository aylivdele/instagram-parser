from sqlalchemy import select
from app.db.models import InstagramAccount, UserCompetitor
from sqlalchemy.ext.asyncio import AsyncSession


class UserCompetitorRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id_and_account_id(self, user_id: str, account_id: int):
        result = await self.session.execute(
            select(UserCompetitor)
            .where(
                UserCompetitor.user_id == user_id,
                UserCompetitor.account_id == account_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_add(self, user_id: str, account_id: int, folder_id: int | None):
        entity = await self.get_by_user_id_and_account_id(user_id, account_id)
        if entity:
            return entity
        
        entity = UserCompetitor(
            user_id=user_id,
            account_id=account_id,
            folder_id=folder_id
        )
        self.session.add(entity)
        await self.session.commit()
        return entity

    async def remove(self, user_id: str, account_id: int):
        result = await self.session.execute(
            select(UserCompetitor)
            .where(
                UserCompetitor.user_id == user_id,
                UserCompetitor.account_id == account_id
            )
        )
        entity = result.scalar_one_or_none()
        if entity:
            await self.session.delete(entity)
            await self.session.commit()

    async def get_user_accounts(self, user_id: str):
        result = await self.session.execute(
            select(InstagramAccount.username, InstagramAccount.avg_posts_views_per_hour, InstagramAccount.avg_reels_views_per_hour, UserCompetitor.folder_id)
            .join(InstagramAccount, InstagramAccount.id == UserCompetitor.account_id)
            .where(UserCompetitor.user_id == user_id)
        )
        return result.all()
    
    async def get_users_by_account(self, account_id: int):

        result = await self.session.execute(
            select(UserCompetitor.user_id)
            .where(UserCompetitor.account_id == account_id)
        )

        return [row[0] for row in result.all()]
