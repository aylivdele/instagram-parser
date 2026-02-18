"""
Instagram Trend Monitor Backend
Отслеживает посты конкурентов и детектирует аномально быстрый рост просмотров
Мультипользовательская версия с конфигурируемыми параметрами
"""

import asyncio
import aiohttp
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sqlite3
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# Конфигурация из переменных окружения
# ══════════════════════════════════════════════════════════════════

class Config:
    """Централизованная конфигурация приложения"""
    
    # ── Apify ──────────────────────────────────────────────────────
    APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
    APIFY_ACTOR_ID = "apify~instagram-post-scraper"
    
    # ── Параметры мониторинга ──────────────────────────────────────
    # Сколько постов загружать с каждого аккаунта за проверку
    POSTS_LIMIT = int(os.environ.get("POSTS_LIMIT", "10"))
    
    # Анализировать только посты не старше N часов
    POSTS_MAX_AGE_HOURS = int(os.environ.get("POSTS_MAX_AGE_HOURS", "48"))
    
    # Интервал между проверками (минуты)
    MONITORING_INTERVAL_MINUTES = int(os.environ.get("MONITORING_INTERVAL_MINUTES", "60"))
    
    # ── Критерии детекции трендов ──────────────────────────────────
    # Минимальный рост скорости просмотров для алерта (%)
    TREND_GROWTH_THRESHOLD = float(os.environ.get("TREND_GROWTH_THRESHOLD", "150"))
    
    # Максимальный возраст поста для детекции тренда (часы)
    TREND_MAX_POST_AGE_HOURS = int(os.environ.get("TREND_MAX_POST_AGE_HOURS", "24"))
    
    # Минимальное количество проверок поста для подтверждения тренда
    TREND_MIN_SNAPSHOTS = int(os.environ.get("TREND_MIN_SNAPSHOTS", "2"))
    
    # Множитель средней скорости (текущая должна быть в N раз выше средней)
    TREND_SPEED_MULTIPLIER = float(os.environ.get("TREND_SPEED_MULTIPLIER", "2.0"))
    
    # ── База данных ────────────────────────────────────────────────
    DB_PATH = os.environ.get("DB_PATH", "instagram_monitor.db")
    
    # ── Telegram ───────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    
    @classmethod
    def log_config(cls):
        """Вывести текущую конфигурацию в лог"""
        logger.info("=" * 60)
        logger.info("Конфигурация Instagram Monitor:")
        logger.info(f"  Постов за проверку: {cls.POSTS_LIMIT}")
        logger.info(f"  Макс. возраст поста: {cls.POSTS_MAX_AGE_HOURS}ч")
        logger.info(f"  Интервал мониторинга: {cls.MONITORING_INTERVAL_MINUTES} мин")
        logger.info(f"  Порог роста для тренда: {cls.TREND_GROWTH_THRESHOLD}%")
        logger.info(f"  Макс. возраст для тренда: {cls.TREND_MAX_POST_AGE_HOURS}ч")
        logger.info(f"  Мин. проверок для тренда: {cls.TREND_MIN_SNAPSHOTS}")
        logger.info(f"  Множитель скорости: {cls.TREND_SPEED_MULTIPLIER}x")
        logger.info(f"  База данных: {cls.DB_PATH}")
        logger.info(f"  Apify токен: {'задан' if cls.APIFY_TOKEN else 'НЕ ЗАДАН'}")
        logger.info(f"  Telegram токен: {'задан' if cls.TELEGRAM_BOT_TOKEN else 'НЕ ЗАДАН'}")
        logger.info("=" * 60)


# ── URL для Apify API ──────────────────────────────────────────────
APIFY_RUN_SYNC_URL = (
    f"https://api.apify.com/v2/acts/{Config.APIFY_ACTOR_ID}"
    f"/run-sync-get-dataset-items"
    f"?token={Config.APIFY_TOKEN}"
    f"&timeout=300"
    f"&memory=256"
)


def _parse_chat_ids(env_value: str) -> List[str]:
    """Разбирает TELEGRAM_CHAT_IDS из строки окружения в список строк"""
    if not env_value:
        return []
    cleaned = env_value.strip().lstrip("[").rstrip("]")
    return [part.strip().strip('"').strip("'") for part in cleaned.split(",") if part.strip()]


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
    """Разбирает один элемент из датасета Apify в объект Post"""
    try:
        post_id = item.get("id") or item.get("shortCode")
        if not post_id:
            return None

        url = item.get("url") or item.get("postUrl") or ""
        if not url:
            short_code = item.get("shortCode", post_id)
            url = f"https://www.instagram.com/p/{short_code}/"

        likes = item.get("likesCount", 0) or 0
        if likes < 0:
            likes = 0

        views = (
            item.get("videoViewCount")
            or item.get("videoPlayCount")
            or item.get("playsCount")
            or (likes * 10)
        )
        views = max(int(views), 0)

        raw_ts = item.get("timestamp") or item.get("takenAt")
        if isinstance(raw_ts, (int, float)):
            timestamp = datetime.utcfromtimestamp(raw_ts)
        elif isinstance(raw_ts, str):
            timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            timestamp = timestamp.replace(tzinfo=None)
        else:
            timestamp = datetime.utcnow()

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
        logger.warning(f"Не удалось разобрать элемент Apify: {e}")
        return None


async def fetch_instagram_posts_apify(
    username: str,
    limit: int = None,
    only_recent_hours: int = None,
) -> List[Post]:
    """Получает последние посты пользователя через Apify Instagram Post Scraper"""
    if not Config.APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN не задан")

    limit = limit or Config.POSTS_LIMIT
    only_recent_hours = only_recent_hours or Config.POSTS_MAX_AGE_HOURS

    newer_than = (datetime.utcnow() - timedelta(hours=only_recent_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    run_input = {
        "username": [username],
        "resultsLimit": limit,
        "onlyPostsNewerThan": newer_than,
    }

    logger.info(f"[Apify] Запрос постов @{username} (лимит={limit}, за {only_recent_hours}ч)")

    timeout = aiohttp.ClientTimeout(total=310)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            APIFY_RUN_SYNC_URL,
            json=run_input,
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status > 299:
                body = await resp.text()
                raise RuntimeError(f"[Apify] Ошибка {resp.status}: {body}")

            items: list = await resp.json()

    if not isinstance(items, list):
        raise RuntimeError(f"[Apify] Неожиданный формат ответа")

    posts: List[Post] = []
    for item in items:
        post = _parse_apify_item(item, username)
        if post is not None:
            posts.append(post)

    posts.sort(key=lambda p: p.timestamp, reverse=True)
    logger.info(f"[Apify] @{username}: разобрано {len(posts)} постов")
    return posts


# ══════════════════════════════════════════════════════════════════
# Основной класс монитора
# ══════════════════════════════════════════════════════════════════

class InstagramMonitor:
    def __init__(self, db_path: str = None, telegram_token: str = None):
        self.db_path = db_path or Config.DB_PATH
        self.telegram_token = telegram_token or Config.TELEGRAM_BOT_TOKEN
        self.init_database()

    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                telegram_chat_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP
            )
        """)

        # Таблица папок для организации конкурентов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                color TEXT DEFAULT '#0088cc',
                icon TEXT DEFAULT '📁',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sort_order INTEGER DEFAULT 0,
                UNIQUE(user_id, name),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_folders_user 
            ON folders(user_id, sort_order)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS competitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                folder_id INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                avg_views_per_hour REAL DEFAULT 0,
                total_posts_analyzed INTEGER DEFAULT 0,
                UNIQUE(user_id, username),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_competitors_user 
            ON competitors(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_competitors_folder 
            ON competitors(user_id, folder_id)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS post_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                username TEXT NOT NULL,
                post_url TEXT,
                views INTEGER,
                likes INTEGER,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hours_since_posted REAL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_post_snapshots_user_username 
            ON post_snapshots(user_id, username)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_post_snapshots_post_id 
            ON post_snapshots(user_id, post_id, checked_at)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                username TEXT NOT NULL,
                post_url TEXT,
                views INTEGER,
                views_per_hour REAL,
                avg_views_per_hour REAL,
                growth_rate REAL,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_to_telegram BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_user 
            ON alerts(user_id, detected_at DESC)
        """)

        conn.commit()
        conn.close()
        logger.info("База данных инициализирована (мультипользовательская схема)")

    def register_user(self, user_id: str, telegram_chat_id: str = None):
        """Регистрирует нового пользователя или обновляет существующего"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO users (user_id, telegram_chat_id, last_active)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                telegram_chat_id = COALESCE(excluded.telegram_chat_id, users.telegram_chat_id),
                last_active = excluded.last_active
        """, (user_id, telegram_chat_id, datetime.now()))
        
        conn.commit()
        conn.close()

    def get_user_chat_id(self, user_id: str) -> Optional[str]:
        """Получить telegram_chat_id пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_chat_id FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    # ── Управление папками ─────────────────────────────────────────

    def create_folder(self, user_id: str, name: str, color: str = '#0088cc', icon: str = '📁') -> int:
        """Создать новую папку"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем максимальный sort_order для добавления в конец
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM folders WHERE user_id = ?",
            (user_id,)
        )
        sort_order = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO folders (user_id, name, color, icon, sort_order)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, color, icon, sort_order))
        
        folder_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"[{user_id}] Создана папка '{name}'")
        return folder_id

    def update_folder(self, user_id: str, folder_id: int, name: str = None, color: str = None, icon: str = None):
        """Обновить папку"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if color is not None:
            updates.append("color = ?")
            params.append(color)
        if icon is not None:
            updates.append("icon = ?")
            params.append(icon)
        
        if not updates:
            conn.close()
            return
        
        params.extend([user_id, folder_id])
        query = f"UPDATE folders SET {', '.join(updates)} WHERE user_id = ? AND id = ?"
        
        cursor.execute(query, params)
        conn.commit()
        conn.close()

    def delete_folder(self, user_id: str, folder_id: int):
        """Удалить папку (конкуренты переместятся в "Без папки")"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM folders WHERE user_id = ? AND id = ?", (user_id, folder_id))
        conn.commit()
        conn.close()
        logger.info(f"[{user_id}] Удалена папка {folder_id}")

    def get_folders(self, user_id: str) -> List[Dict]:
        """Получить все папки пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, color, icon, sort_order,
                   (SELECT COUNT(*) FROM competitors WHERE folder_id = folders.id) as count
            FROM folders
            WHERE user_id = ?
            ORDER BY sort_order
        """, (user_id,))
        
        folders = []
        for row in cursor.fetchall():
            folders.append({
                "id": row[0],
                "name": row[1],
                "color": row[2],
                "icon": row[3],
                "sort_order": row[4],
                "count": row[5],
            })
        conn.close()
        return folders

    def reorder_folders(self, user_id: str, folder_ids: List[int]):
        """Изменить порядок папок"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for order, folder_id in enumerate(folder_ids):
            cursor.execute(
                "UPDATE folders SET sort_order = ? WHERE user_id = ? AND id = ?",
                (order, user_id, folder_id)
            )
        
        conn.commit()
        conn.close()

    # ── Управление конкурентами ────────────────────────────────────

    def add_competitor(self, user_id: str, username: str, folder_id: int = None):
        """Добавить конкурента для конкретного пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO competitors (user_id, username, folder_id, added_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, folder_id, datetime.now()))
        conn.commit()
        conn.close()
        logger.info(f"[{user_id}] Добавлен конкурент @{username}")

    def move_competitor_to_folder(self, user_id: str, username: str, folder_id: int = None):
        """Переместить конкурента в другую папку"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE competitors SET folder_id = ? WHERE user_id = ? AND username = ?",
            (folder_id, user_id, username)
        )
        conn.commit()
        conn.close()

    def remove_competitor(self, user_id: str, username: str):
        """Удалить конкурента и все связанные данные"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM competitors WHERE user_id = ? AND username = ?", (user_id, username))
        cursor.execute("DELETE FROM post_snapshots WHERE user_id = ? AND username = ?", (user_id, username))
        cursor.execute("DELETE FROM alerts WHERE user_id = ? AND username = ?", (user_id, username))
        
        conn.commit()
        conn.close()
        logger.info(f"[{user_id}] Удалён конкурент @{username}")

    def get_competitors(self, user_id: str) -> List[str]:
        """Получить список конкурентов пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM competitors WHERE user_id = ?", (user_id,))
        competitors = [row[0] for row in cursor.fetchall()]
        conn.close()
        return competitors

    def get_all_users_with_competitors(self) -> List[str]:
        """Получить список всех user_id с конкурентами"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT user_id FROM competitors")
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users

    async def fetch_instagram_posts(self, username: str, limit: int = None) -> List[Post]:
        """Получить последние посты через Apify"""
        try:
            return await fetch_instagram_posts_apify(username, limit=limit)
        except Exception as e:
            logger.error(f"Ошибка получения постов @{username}: {e}")
            return []

    def save_post_snapshot(self, user_id: str, post: Post):
        """Сохранить снимок поста"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        hours_since_posted = (datetime.now() - post.timestamp).total_seconds() / 3600
        cursor.execute("""
            INSERT INTO post_snapshots
            (user_id, post_id, username, post_url, views, likes, checked_at, hours_since_posted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, post.post_id, post.username, post.url,
            post.views, post.likes, datetime.now(), hours_since_posted
        ))
        conn.commit()
        conn.close()

    def calculate_post_metrics(self, user_id: str, post: Post) -> PostMetrics:
        """Анализ скорости роста поста с конфигурируемыми порогами"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT views, checked_at, hours_since_posted
            FROM post_snapshots
            WHERE user_id = ? AND post_id = ?
            ORDER BY checked_at DESC
            LIMIT 5
        """, (user_id, post.post_id))
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
            WITH ranked_snapshots AS (
                SELECT 
                    post_id, views, checked_at,
                    LAG(views) OVER (PARTITION BY post_id ORDER BY checked_at) as prev_views,
                    LAG(checked_at) OVER (PARTITION BY post_id ORDER BY checked_at) as prev_checked
                FROM post_snapshots
                WHERE user_id = ? AND username = ? AND hours_since_posted < ?
            ),
            deltas AS (
                SELECT 
                    (views - prev_views) as views_delta,
                    (julianday(checked_at) - julianday(prev_checked)) * 24 as hours_delta
                FROM ranked_snapshots
                WHERE prev_views IS NOT NULL
            )
            SELECT AVG(views_delta / hours_delta) as avg_vph
            FROM deltas
            WHERE hours_delta > 0 AND views_delta >= 0
        """, (user_id, post.username, Config.POSTS_MAX_AGE_HOURS))
        
        result = cursor.fetchone()
        
        if not result[0]:
            cursor.execute("""
                SELECT AVG(views / hours_since_posted) as avg_vph
                FROM post_snapshots
                WHERE user_id = ? AND username = ? 
                  AND hours_since_posted > 0 
                  AND hours_since_posted < ?
            """, (user_id, post.username, Config.TREND_MAX_POST_AGE_HOURS))
            result = cursor.fetchone()
        
        avg_views_per_hour = result[0] if result[0] else 1000

        cursor.execute("""
            UPDATE competitors 
            SET avg_views_per_hour = ? 
            WHERE user_id = ? AND username = ?
        """, (avg_views_per_hour, user_id, post.username))
        conn.commit()
        conn.close()

        growth_rate = (
            ((views_per_hour - avg_views_per_hour) / avg_views_per_hour) * 100
            if avg_views_per_hour > 0 else 0
        )

        is_trending = (
            growth_rate > Config.TREND_GROWTH_THRESHOLD
            and current_hours < Config.TREND_MAX_POST_AGE_HOURS
            and len(snapshots) >= Config.TREND_MIN_SNAPSHOTS
            and views_per_hour > avg_views_per_hour * Config.TREND_SPEED_MULTIPLIER
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

    def save_alert(self, user_id: str, metrics: PostMetrics) -> bool:
        """Сохранить алерт"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM alerts WHERE user_id = ? AND post_id = ?",
            (user_id, metrics.post_id)
        )
        if cursor.fetchone():
            conn.close()
            return False
        
        cursor.execute("""
            INSERT INTO alerts
            (user_id, post_id, username, post_url, views, views_per_hour,
             avg_views_per_hour, growth_rate, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, metrics.post_id, metrics.username, metrics.url,
            metrics.current_views, metrics.views_per_hour,
            metrics.avg_views_per_hour, metrics.growth_rate, datetime.now()
        ))
        conn.commit()
        conn.close()
        logger.info(f"[{user_id}] 🚀 Тренд: @{metrics.username}")
        return True

    async def send_telegram_alert(self, user_id: str, metrics: PostMetrics):
        """Отправить алерт пользователю"""
        if not self.telegram_token:
            return

        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
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

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                }) as response:
                    if response.status == 200:
                        conn = sqlite3.connect(self.db_path)
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE alerts SET sent_to_telegram = 1 WHERE user_id = ? AND post_id = ?",
                            (user_id, metrics.post_id),
                        )
                        conn.commit()
                        conn.close()
            except Exception as e:
                logger.error(f"Ошибка отправки в Telegram: {e}")

    async def monitor_user(self, user_id: str):
        """Один цикл мониторинга для пользователя"""
        competitors = self.get_competitors(user_id)
        if not competitors:
            return

        for username in competitors:
            try:
                posts = await self.fetch_instagram_posts(username)

                recent_posts = [
                    p for p in posts
                    if (datetime.now() - p.timestamp).total_seconds() / 3600 < Config.POSTS_MAX_AGE_HOURS
                ]

                for post in recent_posts:
                    self.save_post_snapshot(user_id, post)
                    metrics = self.calculate_post_metrics(user_id, post)
                    
                    if metrics.is_trending:
                        if self.save_alert(user_id, metrics):
                            await self.send_telegram_alert(user_id, metrics)

                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"[{user_id}] Ошибка @{username}: {e}")

    async def monitor_cycle(self):
        """Цикл мониторинга всех пользователей"""
        users = self.get_all_users_with_competitors()
        if not users:
            return

        await asyncio.gather(
            *[self.monitor_user(user_id) for user_id in users],
            return_exceptions=True
        )

    async def run_continuous_monitoring(self):
        """Непрерывный мониторинг"""
        interval = Config.MONITORING_INTERVAL_MINUTES
        logger.info(f"Старт мониторинга (интервал: {interval} мин)")
        
        while True:
            try:
                await self.monitor_cycle()
                await asyncio.sleep(interval * 60)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                await asyncio.sleep(60)


# ══════════════════════════════════════════════════════════════════
# API для фронтенда
# ══════════════════════════════════════════════════════════════════

class MonitorAPI:
    def __init__(self, monitor: InstagramMonitor):
        self.monitor = monitor

    def get_alerts(self, user_id: str, limit: int = 10) -> List[Dict]:
        """Получить алерты пользователя"""
        conn = sqlite3.connect(self.monitor.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, post_url, views, views_per_hour,
                   avg_views_per_hour, growth_rate, detected_at
            FROM alerts
            WHERE user_id = ?
            ORDER BY detected_at DESC
            LIMIT ?
        """, (user_id, limit))
        
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

    def get_competitors_stats(self, user_id: str) -> List[Dict]:
        """Получить статистику конкурентов пользователя"""
        conn = sqlite3.connect(self.monitor.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                c.username,
                c.folder_id,
                c.avg_views_per_hour,
                COUNT(DISTINCT ps.post_id) as total_posts,
                COALESCE(AVG(ps.likes), 0) as avg_likes,
                MAX(ps.checked_at) as last_checked
            FROM competitors c
            LEFT JOIN (
                SELECT post_id, user_id, username, likes, checked_at
                FROM (
                    SELECT 
                        post_id, user_id, username, likes, checked_at,
                        ROW_NUMBER() OVER (PARTITION BY post_id ORDER BY checked_at DESC) as rn
                    FROM post_snapshots
                    WHERE user_id = ? AND hours_since_posted < ?
                )
                WHERE rn = 1
            ) ps ON c.user_id = ps.user_id AND c.username = ps.username
            WHERE c.user_id = ?
            GROUP BY c.username
        """, (user_id, Config.POSTS_MAX_AGE_HOURS, user_id))
        
        competitors = []
        for row in cursor.fetchall():
            competitors.append({
                "username": row[0],
                "folderId": row[1],
                "avgViews": round(row[2]) if row[2] else 0,
                "avgLikes": round(row[4]) if row[4] else 0,
                "totalPosts": row[3],
                "lastChecked": row[5] if row[5] else datetime.now().isoformat(),
            })
        conn.close()
        return competitors


if __name__ == "__main__":
    Config.log_config()
    monitor = InstagramMonitor()
    asyncio.run(monitor.run_continuous_monitoring())
