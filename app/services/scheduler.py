import asyncio
from datetime import datetime
import logging
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services.monitor_service import MonitorService
from app.services.telegram_service import TelegramNotificationService


class Scheduler:

    def __init__(
        self,
        session_factory: async_sessionmaker,
        monitor_service_factory,
        telegram_service_factory,
        monitoring_interval_minutes: int = 60,
    ):
        self.session_factory = session_factory
        self.monitor_service_factory = monitor_service_factory
        self.telegram_service_factory = telegram_service_factory
        self.interval = monitoring_interval_minutes

        self._running = False
        self.logger = logging.getLogger(__name__)

    # ────────────────────────────────

    async def start(self):
        self._running = True

        while self._running:
            started_at = datetime.utcnow()
            print(f"[Scheduler] Cycle started at {started_at}")

            async with self.session_factory() as session:
                monitor_service = self.monitor_service_factory(session)
                telegram_service = self.telegram_service_factory(session)

                try:
                    await monitor_service.monitor_cycle()
                    await telegram_service.send_pending_alerts()
                except Exception as e:
                    self.logger.exception(f"[Scheduler] Error: {e}")

            print("[Scheduler] Cycle finished")
            await asyncio.sleep(self.interval * 60)

    # ────────────────────────────────

    def stop(self):
        self._running = False
