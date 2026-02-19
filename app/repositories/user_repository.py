from sqlalchemy import select
from app.db.models import User
from sqlalchemy.ext.asyncio import AsyncSession


class UserRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: str):
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(self, user_id: str, telegram_chat_id: str | None = None):
        user = User(id=user_id, telegram_chat_id=telegram_chat_id)
        self.session.add(user)
        await self.session.commit()
        return user

    async def get_or_create(self, user_id: str):
        user = await self.get(user_id)
        if user:
            return user
        return await self.create(user_id)
