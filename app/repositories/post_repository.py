from sqlalchemy import select
from app.db.models import InstagramPost
from sqlalchemy.ext.asyncio import AsyncSession


class PostRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_code(self, post_code: str):
        result = await self.session.execute(
            select(InstagramPost)
            .where(InstagramPost.post_code == post_code)
        )
        return result.scalar_one_or_none()

    async def create(self, account_id: int, post_code: str, url: str, published_at):
        post = InstagramPost(
            account_id=account_id,
            post_code=post_code,
            url=url,
            published_at=published_at
        )
        self.session.add(post)
        await self.session.commit()
        return post
