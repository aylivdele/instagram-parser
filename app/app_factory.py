from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.settings import Settings
from app.services.lobstr_fetcher import LobstrFetcher
from app.services.scheduler import Scheduler
from app.services.scrape_creators_fetcher import ScrapeCreatorsFetcher
from app.services.trend_service import TrendService, TrendConfig
from app.services.account_analytics_service import AccountAnalyticsService
from app.services.monitor_service import MonitorService
from app.services.telegram_service import TelegramNotificationService
from app.services.apify_fetcher import ApifyFetcher


class AppFactory:

    def __init__(self):
        self.settings = Settings()

    def create_scheduler(self):

        # print("Creating worker with settings:")
        # print(f"Apify token: {self.settings.APIFY_TOKEN}")
        # print(f"Lookback iso: {self.settings.only_posts_newer_than()}")
        # print(f"Results limit: {self.settings.RESULTS_LIMIT}")

        engine = create_async_engine(
            self.settings.DATABASE_URL,
            echo=False
        )

        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False
        )

        trend_service = TrendService(
            TrendConfig(
                growth_threshold_percent=self.settings.TREND_GROWTH_THRESHOLD,
                max_post_age_hours=self.settings.TREND_MAX_POST_AGE_HOURS,
                min_snapshots=self.settings.TREND_MIN_SNAPSHOTS
            )
        )

        analytics_service = AccountAnalyticsService()

        # fetcher = LobstrFetcher(
        #     api_key=self.settings.LOBSTR_API_KEY,
        #     crawler_hash=self.settings.LOBSTR_REELS_CRAWLER_HASH,
        # )
        fetcher = ScrapeCreatorsFetcher(
            api_key=self.settings.SC_API_KEY,
            max_age_hours=float(self.settings.CONTENT_LOOKBACK_HOURS)
        )

        monitor_service = MonitorService(
                session_factory=session_factory,
                fetcher=fetcher,
                trend_service=trend_service,
                analytics_service=analytics_service
            )

        def telegram_factory(session):
            return TelegramNotificationService(
                session=session,
                bot_token=self.settings.TELEGRAM_BOT_TOKEN
            )

        return Scheduler(
            session_factory=session_factory,
            monitor_service=monitor_service,
            telegram_service_factory=telegram_factory,
            monitoring_interval_minutes=self.settings.MONITOR_INTERVAL
        )
