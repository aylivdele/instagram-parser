from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import datetime, timedelta, timezone


class Settings(BaseSettings):

    DATABASE_URL: str

    TELEGRAM_BOT_TOKEN: str
    APIFY_TOKEN: str

    MONITOR_INTERVAL: int = 60

    CONTENT_LOOKBACK_HOURS: int = 48
    APIFY_RESULTS_LIMIT: int = 30

    TREND_GROWTH_THRESHOLD: int = 150
    TREND_MAX_POST_AGE_HOURS: int = 48
    TREND_MIN_SNAPSHOTS: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

    def only_posts_newer_than(self) -> str:
        dt = datetime.now(timezone.utc) - timedelta(hours=self.CONTENT_LOOKBACK_HOURS)

        # убираем микросекунды
        dt = dt.replace(microsecond=0)

        return dt.isoformat().replace("+00:00", "")
