from datetime import datetime
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.db.models import InstagramAccount
from app.repositories.account_repository import AccountRepository
from app.repositories.post_repository import PostRepository
from app.repositories.snapshot_repository import SnapshotRepository
from app.repositories.user_competitor_repository import UserCompetitorRepository
from app.repositories.alert_repository import AlertRepository

from app.services.trend_service import TrendService, SnapshotData
from app.services.account_analytics_service import AccountAnalyticsService
from app.services.interfaces import ContentType, FetchedPost, InstagramFetcherInterface


class MonitorService:

    def __init__(
        self,
        session: AsyncSession,
        fetcher: InstagramFetcherInterface,
        trend_service: TrendService,
        analytics_service: AccountAnalyticsService,
    ):
        self.session = session
        self.fetcher = fetcher
        self.trend_service = trend_service
        self.analytics_service = analytics_service

        self.account_repo = AccountRepository(session)
        self.post_repo = PostRepository(session)
        self.snapshot_repo = SnapshotRepository(session)
        self.user_comp_repo = UserCompetitorRepository(session)
        self.alert_repo = AlertRepository(session)
        self.logger = logging.getLogger(__name__)

    # ────────────────────────────────
    # Публичный метод: цикл по всем аккаунтам
    # ────────────────────────────────

    async def monitor_cycle(self):

        accounts = await self._get_accounts_with_subscribers()
        await self.fetcher.process_accounts(accounts, self._process_posts)

    async def _process_posts(self, account: InstagramAccount, fetched_posts: List[FetchedPost]):
        self.logger.info(f"Processing {len(fetched_posts)} for user {account.username}")

        reels_speeds = []
        posts_speeds = []

        for fetched in fetched_posts:

            post = await self._get_or_create_post(account.id, fetched)

            await self.snapshot_repo.create(
                post_id=post.id,
                views=fetched.views,
                likes=fetched.likes
            )

            snapshots = await self._get_post_snapshots(post.id)

            result = self.trend_service.analyze_post(
                post_id=post.id,
                published_at=post.published_at,
                snapshots=snapshots,
                account_avg_speed=account.avg_posts_views_per_hour if fetched.post_type == ContentType.POST else account.avg_reels_views_per_hour
            )

            if fetched.post_type == ContentType.REEL:
                reels_speeds.append(result.views_per_hour)
            else:
                posts_speeds.append(result.views_per_hour)


            if result.is_trending:
                await self._create_alerts_for_account_users(
                    account.id,
                    result
                )
            self.logger.info(f"{account.username}: Post {fetched.post_code}\nViews: {result.current_views}\nAvg. vph: {result.avg_views_per_hour}")

        account.avg_reels_views_per_hour = \
            self.analytics_service.calculate_account_average_speed(reels_speeds)

        account.avg_posts_views_per_hour = \
            self.analytics_service.calculate_account_average_speed(posts_speeds)
        
        account.last_checked = datetime.utcnow()

        await self.session.commit()

    # ────────────────────────────────

    async def _get_or_create_post(self, account_id: int, fetched: FetchedPost):
        post = await self.post_repo.get_by_code(fetched.post_code)
        if post:
            return post

        return await self.post_repo.create(
            account_id=account_id,
            post_code=fetched.post_code,
            url=fetched.url,
            published_at=fetched.published_at,
            post_type=fetched.post_type
        )

    # ────────────────────────────────

    async def _get_post_snapshots(self, post_id: int):
        from sqlalchemy import select
        from app.db.models import PostSnapshot

        result = await self.session.execute(
            select(PostSnapshot)
            .where(PostSnapshot.post_id == post_id)
            .order_by(PostSnapshot.checked_at)
        )

        snapshots = result.scalars().all()

        return [
            SnapshotData(
                views=s.views,
                checked_at=s.checked_at
            )
            for s in snapshots
        ]

    # ────────────────────────────────

    async def _create_alerts_for_account_users(self, account_id: int, trend_result):

        users = await self.user_comp_repo.get_users_by_account(account_id)

        for user_id in users:
            exists = await self.alert_repo.exists(user_id, trend_result.post_id)
            if not exists:
                await self.alert_repo.create(
                    user_id=user_id,
                    post_id=trend_result.post_id,
                    views=trend_result.current_views,
                    views_per_hour=trend_result.views_per_hour,
                    avg_views_per_hour=trend_result.avg_views_per_hour,
                    growth_rate=trend_result.growth_rate
                )

    # ────────────────────────────────

    async def _get_accounts_with_subscribers(self):
        from sqlalchemy import select
        from app.db.models import InstagramAccount, UserCompetitor

        result = await self.session.execute(
            select(InstagramAccount)
            .join(UserCompetitor,
                  InstagramAccount.id == UserCompetitor.account_id)
            .distinct()
        )

        return result.scalars().all()
