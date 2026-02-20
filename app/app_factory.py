from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.settings import Settings
from app.services.scheduler import Scheduler
from app.services.trend_service import TrendService, TrendConfig
from app.services.account_analytics_service import AccountAnalyticsService
from app.services.monitor_service import MonitorService
from app.services.telegram_service import TelegramNotificationService
from app.services.apify_fetcher import ApifyFetcher


class AppFactory:

    def __init__(self):
        self.settings = Settings()

    def create_scheduler(self):

        print("Creating worker with settings:")
        print(f"Apify token: {self.settings.APIFY_TOKEN}")
        print(f"Apify actor id: {self.settings.APIFY_ACTOR_ID}")
        print(f"Lookback iso: {self.settings.only_posts_newer_than()}")
        print(f"Results limit: {self.settings.APIFY_RESULTS_LIMIT}")

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
                growth_threshold_percent=150,
                max_post_age_hours=24,
                min_snapshots=2
            )
        )

        analytics_service = AccountAnalyticsService()

        fetcher = ApifyFetcher(
            api_token=self.settings.APIFY_TOKEN,
            actor_id=self.settings.APIFY_ACTOR_ID,
            lookback_iso=self.settings.only_posts_newer_than(),
            results_limit=self.settings.APIFY_RESULTS_LIMIT
        )


        def monitor_factory(session):
            return MonitorService(
                session=session,
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
            monitor_service_factory=monitor_factory,
            telegram_service_factory=telegram_factory,
            monitoring_interval_minutes=self.settings.MONITOR_INTERVAL
        )
