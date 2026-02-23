from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, Folder, User, InstagramPost, InstagramAccount, UserCompetitor

MSK = ZoneInfo("Europe/Moscow")

class TelegramNotificationService:

    def __init__(self, session: AsyncSession, bot_token: str):
        self.session = session
        self.bot_token = bot_token
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # ────────────────────────────────
    # Публичный метод
    # ────────────────────────────────

    async def send_pending_alerts(self):

        alerts = await self._get_unsent_alerts()

        for alert, post_url, username, folder_name, date in alerts:
            chat_id = await self._get_user_chat_id(alert.user_id)

            if not chat_id:
                continue

            message = await self._build_message(alert, post_url, username, date, folder_name)

            success = await self._send_message(chat_id, message)

            if success:
                alert.sent_to_telegram = True

        await self.session.commit()

    # ────────────────────────────────

    async def _get_unsent_alerts(self):

        result = await self.session.execute(
            select(
                Alert,
                InstagramPost.url,
                InstagramAccount.username,
                Folder.name,
                InstagramPost.published_at
            )
            .join(InstagramPost, Alert.post_id == InstagramPost.id)
            .join(InstagramAccount, InstagramPost.account_id == InstagramAccount.id)
            .join(
                UserCompetitor,
                (UserCompetitor.account_id == InstagramAccount.id)
                & (UserCompetitor.user_id == Alert.user_id)
            )
            .outerjoin(Folder, Folder.id == UserCompetitor.folder_id)
            .where(Alert.sent_to_telegram == False)
        )

        return result.all()

    # ────────────────────────────────

    async def _get_user_chat_id(self, user_id: str):

        result = await self.session.execute(
            select(User.telegram_chat_id)
            .where(User.id == user_id)
        )

        return result.scalar_one_or_none()

    # ────────────────────────────────

    async def _build_message(self, alert: Alert, post_url: str, username: str, date: datetime, folder_name: str | None = None):

        return (
            f"🚀 <b>Обнаружен вирусный пост!</b>\n\n"
            f"👤 Аккаунт: @{username}\n"
            f"🗓 Дата поста: {date.astimezone(MSK).strftime('%m-%d %H:%M')} мск\n"
            f"📁 Папка: {folder_name if folder_name else 'Без папки'}\n"
            f"📊 Просмотры: {alert.views:,}\n"
            f"⚡ Скорость: {alert.views_per_hour:.0f} в час\n"
            f"📈 Рост: +{alert.growth_rate:.0f}%\n\n"
            f"<a href=\"{post_url}\">Открыть пост</a>"
        )

    # ────────────────────────────────

    async def _send_message(self, chat_id: str, message: str):

        if not message:
            return False

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    self.api_url,
                    json={
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                    }
                ) as response:

                    return response.status == 200

            except Exception:
                return False
