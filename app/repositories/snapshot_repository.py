from app.db.models import PostSnapshot
from sqlalchemy.ext.asyncio import AsyncSession


class SnapshotRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, post_id: int, views: int, likes: int):
        snapshot = PostSnapshot(
            post_id=post_id,
            views=views,
            likes=likes
        )
        self.session.add(snapshot)
        await self.session.commit()
        return snapshot
