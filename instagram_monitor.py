"""
Instagram Trend Monitor Backend
Отслеживает посты конкурентов и детектирует аномально быстрый рост просмотров
"""

import asyncio
import aiohttp
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sqlite3
from dataclasses import dataclass, asdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _parse_chat_ids(env_value: str) -> List[str]:
    """
    Разбирает TELEGRAM_CHAT_IDS из строки окружения в список строк.

    Поддерживаемые форматы:
        TELEGRAM_CHAT_IDS=58386007,387051080
        TELEGRAM_CHAT_IDS=[58386007, 387051080]
        TELEGRAM_CHAT_IDS=["58386007", "387051080"]
    """
    if not env_value:
        return []
    # Убираем квадратные скобки, если они есть
    cleaned = env_value.strip().lstrip("[").rstrip("]")
    # Разбиваем по запятой, убираем кавычки и пробелы
    return [part.strip().strip('"').strip("'") for part in cleaned.split(",") if part.strip()]

# ── Конфигурация Apify ─────────────────────────────────────────
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")

# Актор apify/instagram-post-scraper (официальный, поддерживается Apify)
# Документация: https://apify.com/apify/instagram-post-scraper
APIFY_ACTOR_ID = "apify~instagram-post-scraper"

# Синхронный REST-эндпоинт: запускает актор и сразу возвращает датасет
# Таймаут до 5 минут — актор завершается обычно за 30-90 секунд
APIFY_RUN_SYNC_URL = (
    f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}"
    f"/run-sync-get-dataset-items"
    f"?token={APIFY_TOKEN}"
    f"&timeout=300"        # макс. время ожидания ответа, сек
    f"&memory=256"         # MB RAM для актора (минимум достаточный)
)


@dataclass
class Post:
    post_id: str
    username: str
    url: str
    views: int
    likes: int
    timestamp: datetime


@dataclass
class PostMetrics:
    post_id: str
    username: str
    url: str
    current_views: int
    views_per_hour: float
    avg_views_per_hour: float
    growth_rate: float
    is_trending: bool
    alert_sent: bool = False


# ══════════════════════════════════════════════════════════════════
# Получение постов через Apify Instagram Post Scraper
# ══════════════════════════════════════════════════════════════════

def _parse_apify_item(item: dict, username: str) -> Optional[Post]:
    """
    Разбирает один элемент из датасета Apify в объект Post.

    Структура ответа apify/instagram-post-scraper (актуальная):
    {
      "id":           "ABC123shortcode",
      "url":          "https://www.instagram.com/p/ABC123/",
      "likesCount":   1500,          # -1 если автор скрыл лайки
      "videoViewCount": 42000,       # только для видео/reels, иначе null
      "videoPlayCount": 45000,       # альтернативное поле просмотров
      "commentsCount": 230,
      "timestamp":    "2024-11-01T12:00:00.000Z",
      "ownerUsername": "nike",
      "type":         "Video" | "Image" | "Sidecar",
      ...
    }
    """
    try:
        post_id = item.get("id") or item.get("shortCode")
        if not post_id:
            return None

        url = item.get("url") or item.get("postUrl") or ""
        if not url:
            short_code = item.get("shortCode", post_id)
            url = f"https://www.instagram.com/p/{short_code}/"

        likes = item.get("likesCount", 0) or 0
        if likes < 0:          # Instagram скрыл лайки — ставим 0
            likes = 0

        # Просмотры: для видео/reels есть videoViewCount или videoPlayCount,
        # для фото считаем через лайки (условный коэффициент ~10x)
        views = (
            item.get("videoViewCount")
            or item.get("videoPlayCount")
            or item.get("playsCount")
            or (likes * 10)   # fallback для фото
        )
        views = max(int(views), 0)

        raw_ts = item.get("timestamp") or item.get("takenAt")
        if isinstance(raw_ts, (int, float)):
            # Unix timestamp в секундах
            timestamp = datetime.utcfromtimestamp(raw_ts)
        elif isinstance(raw_ts, str):
            # ISO 8601: "2024-11-01T12:00:00.000Z"
            timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            timestamp = timestamp.replace(tzinfo=None)   # убираем timezone для sqlite
        else:
            timestamp = datetime.utcnow()

        # username из самого элемента приоритетнее переданного аргумента
        owner = item.get("ownerUsername") or item.get("username") or username

        return Post(
            post_id=str(post_id),
            username=owner,
            url=url,
            views=views,
            likes=likes,
            timestamp=timestamp,
        )

    except Exception as e:
        logger.warning(f"Не удалось разобрать элемент Apify: {e} | item={item}")
        return None


async def fetch_instagram_posts_apify(
    username: str,
    limit: int = 10,
    only_recent_hours: int = 48,
) -> List[Post]:
    """
    Получает последние посты пользователя через Apify Instagram Post Scraper.

    Использует синхронный эндпоинт run-sync-get-dataset-items:
    актор запускается и ждёт завершения в рамках одного HTTP-запроса.

    Args:
        username:           Instagram-логин без @
        limit:              Максимальное кол-во постов (resultsLimit для актора)
        only_recent_hours:  Фильтр: вернуть только посты не старше N часов
                            (onlyPostsNewerThan передаётся прямо в актор)

    Returns:
        Список Post, отсортированный от свежего к старому.

    Raises:
        RuntimeError: если APIFY_TOKEN не задан или API вернул ошибку.
    """
    if not APIFY_TOKEN:
        raise RuntimeError(
            "APIFY_TOKEN не задан. "
            "Добавьте его в .env или в переменные окружения Docker."
        )

    # Дата-фильтр: просим актор вернуть только свежие посты
    newer_than = (datetime.utcnow() - timedelta(hours=only_recent_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    # Входные параметры актора (актуальная схема apify/instagram-post-scraper)
    run_input = {
        "username": [username],          # список логинов
        "resultsLimit": limit,           # кол-во постов на профиль
        "onlyPostsNewerThan": newer_than,  # фильтр по дате (поддерживается актором)
    }

    logger.info(f"[Apify] Запрос постов @{username} (лимит={limit}, за {only_recent_hours}ч)")

    timeout = aiohttp.ClientTimeout(total=310)   # чуть больше таймаута актора

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            APIFY_RUN_SYNC_URL,
            json=run_input,
            headers={"Content-Type": "application/json"},
        ) as resp:

            if resp.status == 400:
                body = await resp.text()
                raise RuntimeError(f"[Apify] Неверный запрос (400): {body}")

            if resp.status == 401:
                raise RuntimeError(
                    "[Apify] Неверный токен (401). Проверьте APIFY_TOKEN."
                )

            if resp.status == 429:
                raise RuntimeError(
                    "[Apify] Превышен rate limit Apify (429). "
                    "Подождите или увеличьте интервал мониторинга."
                )

            if resp.status >= 500:
                body = await resp.text()
                raise RuntimeError(f"[Apify] Ошибка сервера ({resp.status}): {body}")

            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"[Apify] Неожиданный статус {resp.status}: {body}")

            # Датасет возвращается как JSON-массив напрямую
            items: list = await resp.json()

    if not isinstance(items, list):
        # Иногда при ошибке Apify возвращает объект {"error": ...}
        error_msg = items.get("error", {}).get("message", str(items)) if isinstance(items, dict) else str(items)
        raise RuntimeError(f"[Apify] Неожиданный формат ответа: {error_msg}")

    logger.info(f"[Apify] @{username}: получено {len(items)} элементов из датасета")

    posts: List[Post] = []
    for item in items:
        post = _parse_apify_item(item, username)
        if post is not None:
            posts.append(post)

    # Сортируем от самого свежего к старому
    posts.sort(key=lambda p: p.timestamp, reverse=True)

    logger.info(f"[Apify] @{username}: успешно разобрано {len(posts)} постов")
    return posts


# ══════════════════════════════════════════════════════════════════
# Основной класс монитора
# ══════════════════════════════════════════════════════════════════

class InstagramMonitor:
    def __init__(self, db_path: str = "monitor.db", telegram_token: str = None, telegram_chat_ids: List[str] = None):
        self.db_path = db_path
        self.telegram_token = telegram_token
        self.telegram_chat_ids: List[str] = telegram_chat_ids or []
        self.init_database()

    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS competitors (
                username TEXT PRIMARY KEY,
                added_at TIMESTAMP,
                avg_views_per_hour REAL DEFAULT 0,
                total_posts_analyzed INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS post_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                username TEXT,
                post_url TEXT,
                views INTEGER,
                likes INTEGER,
                checked_at TIMESTAMP,
                hours_since_posted REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                username TEXT,
                post_url TEXT,
                views INTEGER,
                views_per_hour REAL,
                avg_views_per_hour REAL,
                growth_rate REAL,
                detected_at TIMESTAMP,
                sent_to_telegram BOOLEAN DEFAULT 0
            )
        """)

        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")

    def add_competitor(self, username: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO competitors (username, added_at)
            VALUES (?, ?)
        """, (username, datetime.now()))
        conn.commit()
        conn.close()
        logger.info(f"Конкурент @{username} добавлен")

    def get_competitors(self) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM competitors")
        competitors = [row[0] for row in cursor.fetchall()]
        conn.close()
        return competitors

    async def fetch_instagram_posts(self, username: str, limit: int = 10) -> List[Post]:
        """
        Получить последние посты пользователя из Instagram через Apify.

        При недоступности Apify (нет токена / ошибка сети) логирует ошибку
        и возвращает пустой список, чтобы не ронять весь цикл мониторинга.
        """
        try:
            return await fetch_instagram_posts_apify(username, limit=limit)
        except RuntimeError as e:
            logger.error(f"Ошибка Apify для @{username}: {e}")
            return []
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при запросе Apify для @{username}")
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении постов @{username}: {e}")
            return []

    def save_post_snapshot(self, post: Post):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        hours_since_posted = (datetime.now() - post.timestamp).total_seconds() / 3600
        cursor.execute("""
            INSERT INTO post_snapshots
            (post_id, username, post_url, views, likes, checked_at, hours_since_posted)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            post.post_id, post.username, post.url,
            post.views, post.likes, datetime.now(), hours_since_posted
        ))
        conn.commit()
        conn.close()

    def calculate_post_metrics(self, post: Post) -> PostMetrics:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT views, checked_at, hours_since_posted
            FROM post_snapshots
            WHERE post_id = ?
            ORDER BY checked_at DESC
            LIMIT 5
        """, (post.post_id,))
        snapshots = cursor.fetchall()

        current_hours = (datetime.now() - post.timestamp).total_seconds() / 3600

        if len(snapshots) >= 2:
            prev_views = snapshots[1][0]
            time_diff = (
                datetime.now() - datetime.fromisoformat(snapshots[1][1])
            ).total_seconds() / 3600
            views_per_hour = (post.views - prev_views) / time_diff if time_diff > 0 else 0
        else:
            views_per_hour = post.views / current_hours if current_hours > 0 else 0

        cursor.execute("""
            SELECT AVG(views / hours_since_posted) as avg_vph
            FROM post_snapshots
            WHERE username = ? AND hours_since_posted > 0 AND hours_since_posted < 24
        """, (post.username,))
        result = cursor.fetchone()
        avg_views_per_hour = result[0] if result[0] else 1000

        cursor.execute("""
            UPDATE competitors SET avg_views_per_hour = ? WHERE username = ?
        """, (avg_views_per_hour, post.username))
        conn.commit()
        conn.close()

        growth_rate = (
            ((views_per_hour - avg_views_per_hour) / avg_views_per_hour) * 100
            if avg_views_per_hour > 0 else 0
        )

        is_trending = (
            growth_rate > 150
            and current_hours < 24
            and len(snapshots) >= 2
            and views_per_hour > avg_views_per_hour * 2
        )

        logger.info(
            f"Пост {post.post_id}: {views_per_hour:.0f} просм/ч "
            f"(среднее: {avg_views_per_hour:.0f}, рост: {growth_rate:.0f}%)"
        )

        return PostMetrics(
            post_id=post.post_id,
            username=post.username,
            url=post.url,
            current_views=post.views,
            views_per_hour=views_per_hour,
            avg_views_per_hour=avg_views_per_hour,
            growth_rate=growth_rate,
            is_trending=is_trending,
        )

    def save_alert(self, metrics: PostMetrics) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM alerts WHERE post_id = ?", (metrics.post_id,))
        if cursor.fetchone():
            logger.info(f"Алерт для {metrics.post_id} уже существует")
            conn.close()
            return False
        cursor.execute("""
            INSERT INTO alerts
            (post_id, username, post_url, views, views_per_hour,
             avg_views_per_hour, growth_rate, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.post_id, metrics.username, metrics.url,
            metrics.current_views, metrics.views_per_hour,
            metrics.avg_views_per_hour, metrics.growth_rate, datetime.now()
        ))
        conn.commit()
        conn.close()
        logger.info(f"🚀 Новый трендовый пост обнаружен: @{metrics.username}")
        return True

    async def _send_to_one_chat(
        self,
        session: aiohttp.ClientSession,
        chat_id: str,
        message: str,
    ) -> bool:
        """Отправляет сообщение в один чат. Возвращает True при успехе."""
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        try:
            async with session.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }) as response:
                if response.status == 200:
                    logger.info(f"Уведомление отправлено в чат {chat_id}")
                    return True
                else:
                    body = await response.text()
                    logger.error(f"Ошибка отправки в чат {chat_id}: {response.status} — {body}")
                    return False
        except Exception as e:
            logger.error(f"Исключение при отправке в чат {chat_id}: {e}")
            return False

    async def send_telegram_alert(self, metrics: PostMetrics, chat_ids: List[str] = None):
        """
        Рассылает алерт о трендовом посте во все чаты из списка.

        Args:
            metrics:  Метрики трендового поста.
            chat_ids: Список chat_id для отправки. Если None — берёт
                      self.telegram_chat_ids, заданные при инициализации.
        """
        if not self.telegram_token:
            logger.warning("Telegram токен не настроен")
            return

        recipients = chat_ids if chat_ids is not None else self.telegram_chat_ids
        if not recipients:
            logger.warning("Список получателей Telegram пуст — алерт не отправлен")
            return

        message = (
            f"🚀 <b>Обнаружен вирусный контент!</b>\n\n"
            f"👤 Аккаунт: @{metrics.username}\n"
            f"📊 Просмотры: {metrics.current_views:,}\n"
            f"⚡️ Скорость: {metrics.views_per_hour:.0f} просм/час\n"
            f"📈 Рост: +{metrics.growth_rate:.0f}% от обычного\n\n"
            f"Среднее: {metrics.avg_views_per_hour:.0f} просм/час\n\n"
            f"🔗 <a href=\"{metrics.url}\">Открыть пост</a>"
        )

        any_success = False
        async with aiohttp.ClientSession() as session:
            # Отправляем параллельно во все чаты
            results = await asyncio.gather(
                *[self._send_to_one_chat(session, cid, message) for cid in recipients],
                return_exceptions=True,
            )
            any_success = any(r is True for r in results)

        if any_success:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE alerts SET sent_to_telegram = 1 WHERE post_id = ?",
                (metrics.post_id,),
            )
            conn.commit()
            conn.close()

    async def monitor_cycle(self):
        competitors = self.get_competitors()
        if not competitors:
            logger.warning("Нет конкурентов для мониторинга")
            return

        logger.info(f"Начало цикла мониторинга ({len(competitors)} аккаунтов)")

        for username in competitors:
            try:
                posts = await self.fetch_instagram_posts(username, limit=5)

                recent_posts = [
                    p for p in posts
                    if (datetime.now() - p.timestamp).total_seconds() / 3600 < 48
                ]

                for post in recent_posts:
                    self.save_post_snapshot(post)
                    metrics = self.calculate_post_metrics(post)
                    if metrics.is_trending:
                        if self.save_alert(metrics):
                            await self.send_telegram_alert(metrics)

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Ошибка при обработке @{username}: {e}")

        logger.info("Цикл мониторинга завершён")

    async def run_continuous_monitoring(
        self,
        interval_minutes: int = 60,
    ):
        chat_list = ", ".join(self.telegram_chat_ids) if self.telegram_chat_ids else "не заданы"
        logger.info(
            f"Запуск непрерывного мониторинга "
            f"(интервал: {interval_minutes} мин, чаты: {chat_list})"
        )
        while True:
            try:
                await self.monitor_cycle()
                logger.info(f"Следующая проверка через {interval_minutes} минут")
                await asyncio.sleep(interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("Мониторинг остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(60)


# ══════════════════════════════════════════════════════════════════
# API для фронтенда
# ══════════════════════════════════════════════════════════════════

class MonitorAPI:
    def __init__(self, monitor: InstagramMonitor):
        self.monitor = monitor

    def get_alerts(self, limit: int = 10) -> List[Dict]:
        conn = sqlite3.connect(self.monitor.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, post_url, views, views_per_hour,
                   avg_views_per_hour, growth_rate, detected_at
            FROM alerts
            ORDER BY detected_at DESC
            LIMIT ?
        """, (limit,))
        alerts = []
        for row in cursor.fetchall():
            alerts.append({
                "username": row[0],
                "postUrl": row[1],
                "currentViews": row[2],
                "viewsPerHour": round(row[3]),
                "avgViewsPerHour": round(row[4]),
                "growth": round(row[5]),
                "timestamp": row[6],
            })
        conn.close()
        return alerts

    def get_competitors_stats(self) -> List[Dict]:
        conn = sqlite3.connect(self.monitor.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.username, c.avg_views_per_hour,
                   COUNT(DISTINCT ps.post_id) as total_posts
            FROM competitors c
            LEFT JOIN post_snapshots ps ON c.username = ps.username
            GROUP BY c.username
        """)
        competitors = []
        for row in cursor.fetchall():
            competitors.append({
                "username": row[0],
                "avgViews": round(row[1]) if row[1] else 0,
                "avgLikes": round(row[1] * 0.08) if row[1] else 0,
                "lastChecked": datetime.now().isoformat(),
            })
        conn.close()
        return competitors


# ══════════════════════════════════════════════════════════════════
# Точка входа
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    TELEGRAM_CHAT_IDS   = os.environ.get("TELEGRAM_CHAT_IDS",  "")
    DB_PATH             = os.environ.get("DB_PATH",             "instagram_monitor.db")

    chat_ids = _parse_chat_ids(TELEGRAM_CHAT_IDS)
    if not chat_ids:
        logger.warning(
            "TELEGRAM_CHAT_IDS не задан — уведомления в Telegram отправляться не будут. "
            "Пример: TELEGRAM_CHAT_IDS=58386007,387051080"
        )

    monitor = InstagramMonitor(
        db_path=DB_PATH,
        telegram_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_ids=chat_ids,
    )

    asyncio.run(monitor.run_continuous_monitoring(interval_minutes=60))
