from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import datetime, timedelta


class Settings(BaseSettings):

    DATABASE_URL: str

    TELEGRAM_BOT_TOKEN: str
    APIFY_TOKEN: str

    LOBSTR_REELS_CRAWLER_HASH: str
    LOBSTR_API_KEY: str
    MONITOR_INTERVAL: int = 60

    CONTENT_LOOKBACK_HOURS: int = 48
    RESULTS_LIMIT: int = 30

    TREND_GROWTH_THRESHOLD: int = 150
    TREND_MAX_POST_AGE_HOURS: int = 48
    TREND_MIN_SNAPSHOTS: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

    def only_posts_newer_than(self) -> str:
        dt = datetime.utcnow() - timedelta(hours=self.CONTENT_LOOKBACK_HOURS)
        return dt.isoformat() + "Z"
