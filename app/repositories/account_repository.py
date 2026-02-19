from sqlalchemy import select
from app.db.models import InstagramAccount
from sqlalchemy.ext.asyncio import AsyncSession


class AccountRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_username(self, username: str):
        result = await self.session.execute(
            select(InstagramAccount)
            .where(InstagramAccount.username == username)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, username: str):
        account = await self.get_by_username(username)
        if account:
            return account

        account = InstagramAccount(username=username)
        self.session.add(account)
        await self.session.commit()
        return account

    async def get_accounts_with_subscribers(self):
        result = await self.session.execute(
            select(InstagramAccount)
            .join(InstagramAccount.posts, isouter=True)
        )
        return result.scalars().all()
