import asyncio
from datetime import datetime, time
import logging
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services.monitor_service import MonitorService
from app.services.telegram_service import TelegramNotificationService

MSK = ZoneInfo("Europe/Moscow")

class Scheduler:

    def __init__(
        self,
        session_factory: async_sessionmaker,
        monitor_service,
        telegram_service_factory,
        monitoring_interval_minutes: int = 60,
        skip_night_time: bool = True
    ):
        self.session_factory = session_factory
        self.monitor_service = monitor_service
        self.telegram_service_factory = telegram_service_factory
        self.interval = monitoring_interval_minutes
        self.skip_night_time = skip_night_time

        self._running = False
        self.logger = logging.getLogger(__name__)

    # ────────────────────────────────

    async def start(self):
        self._running = True

        while self._running:
            started_at = datetime.now(MSK)

            if self.is_within_working_hours(started_at) or not self.skip_night_time:
                print(f"[Scheduler] Cycle started at {started_at}")

                async with self.session_factory() as session:
                    telegram_service = self.telegram_service_factory(session)

                    try:
                        await self.monitor_service.monitor_cycle()
                        await telegram_service.send_pending_alerts()
                    except Exception as e:
                        self.logger.exception(f"[Scheduler] Error: {e}")

                print("[Scheduler] Cycle finished")
            else:
                print(f"[Scheduler] Skipping cycle for night time {started_at}")
            await asyncio.sleep(self.interval * 60)

    def is_within_working_hours(self, date: datetime) -> bool:
        now_msk = date.time()

        start = time(8, 0)

        if start <= now_msk:
            return True

        return False

    # ────────────────────────────────

    def stop(self):
        self._running = False
