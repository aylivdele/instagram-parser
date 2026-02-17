"""
Instagram Trend Monitor Backend
Отслеживает посты конкурентов и детектирует аномально быстрый рост просмотров
"""

import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sqlite3
from dataclasses import dataclass, asdict
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    growth_rate: float  # Скорость роста в процентах
    is_trending: bool
    alert_sent: bool = False


class InstagramMonitor:
    def __init__(self, db_path: str = "monitor.db", telegram_token: str = None):
        self.db_path = db_path
        self.telegram_token = telegram_token
        self.init_database()
        
    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица конкурентов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS competitors (
                username TEXT PRIMARY KEY,
                added_at TIMESTAMP,
                avg_views_per_hour REAL DEFAULT 0,
                total_posts_analyzed INTEGER DEFAULT 0
            )
        """)
        
        # Таблица постов с историей проверок
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
        
        # Таблица алертов
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
        """Добавить конкурента для мониторинга"""
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
        """Получить список всех конкурентов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT username FROM competitors")
        competitors = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return competitors
    
    async def fetch_instagram_posts(self, username: str, limit: int = 10) -> List[Post]:
        """
        Получить последние посты пользователя из Instagram
        
        ВАЖНО: Здесь используется упрощенный пример.
        В реальности нужно использовать:
        1. Instagram Graph API (требует Business аккаунт)
        2. Сторонние API (Apify, RapidAPI)
        3. Веб-скрапинг (может нарушать ToS)
        """
        
        # Пример с использованием Apify API (платный, но надежный)
        # URL = f"https://api.apify.com/v2/acts/apify~instagram-scraper/runs"
        
        # Для демонстрации создадим моковые данные
        logger.info(f"Получение постов для @{username}")
        
        # Здесь должен быть реальный запрос к API
        mock_posts = [
            Post(
                post_id=f"{username}_post_{i}",
                username=username,
                url=f"https://instagram.com/p/example{i}",
                views=1000 * (i + 1),
                likes=100 * (i + 1),
                timestamp=datetime.now() - timedelta(hours=i)
            )
            for i in range(limit)
        ]
        
        return mock_posts
    
    def save_post_snapshot(self, post: Post):
        """Сохранить снимок метрик поста"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        hours_since_posted = (datetime.now() - post.timestamp).total_seconds() / 3600
        
        cursor.execute("""
            INSERT INTO post_snapshots 
            (post_id, username, post_url, views, likes, checked_at, hours_since_posted)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            post.post_id,
            post.username,
            post.url,
            post.views,
            post.likes,
            datetime.now(),
            hours_since_posted
        ))
        
        conn.commit()
        conn.close()
    
    def calculate_post_metrics(self, post: Post) -> PostMetrics:
        """
        Анализ скорости роста поста
        Ключевой метод для детекции трендов!
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем историю проверок этого поста
        cursor.execute("""
            SELECT views, checked_at, hours_since_posted
            FROM post_snapshots
            WHERE post_id = ?
            ORDER BY checked_at DESC
            LIMIT 5
        """, (post.post_id,))
        
        snapshots = cursor.fetchall()
        
        # Вычисляем текущую скорость роста просмотров
        current_hours = (datetime.now() - post.timestamp).total_seconds() / 3600
        
        if len(snapshots) >= 2:
            # Есть предыдущие проверки - считаем скорость за последний час
            prev_views = snapshots[1][0]
            time_diff = (datetime.now() - datetime.fromisoformat(snapshots[1][1])).total_seconds() / 3600
            
            views_per_hour = (post.views - prev_views) / time_diff if time_diff > 0 else 0
        else:
            # Первая проверка - оцениваем среднюю скорость с момента публикации
            views_per_hour = post.views / current_hours if current_hours > 0 else 0
        
        # Получаем среднюю скорость для этого пользователя
        cursor.execute("""
            SELECT AVG(views / hours_since_posted) as avg_vph
            FROM post_snapshots
            WHERE username = ? AND hours_since_posted > 0 AND hours_since_posted < 24
        """, (post.username,))
        
        result = cursor.fetchone()
        avg_views_per_hour = result[0] if result[0] else 1000  # Дефолтное значение
        
        # Обновляем среднее значение для конкурента
        cursor.execute("""
            UPDATE competitors
            SET avg_views_per_hour = ?
            WHERE username = ?
        """, (avg_views_per_hour, post.username))
        
        conn.commit()
        conn.close()
        
        # Вычисляем процент отклонения от нормы
        if avg_views_per_hour > 0:
            growth_rate = ((views_per_hour - avg_views_per_hour) / avg_views_per_hour) * 100
        else:
            growth_rate = 0
        
        # Критерии тренда:
        # 1. Скорость роста выше средней на 150%+
        # 2. Пост не старше 24 часов (свежий контент)
        # 3. Минимум 2 проверки для подтверждения тренда
        is_trending = (
            growth_rate > 150 and 
            current_hours < 24 and 
            len(snapshots) >= 2 and
            views_per_hour > avg_views_per_hour * 2
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
            is_trending=is_trending
        )
    
    def save_alert(self, metrics: PostMetrics):
        """Сохранить алерт о трендовом посте"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Проверяем, не отправляли ли уже алерт по этому посту
        cursor.execute("""
            SELECT id FROM alerts WHERE post_id = ?
        """, (metrics.post_id,))
        
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
            metrics.post_id,
            metrics.username,
            metrics.url,
            metrics.current_views,
            metrics.views_per_hour,
            metrics.avg_views_per_hour,
            metrics.growth_rate,
            datetime.now()
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"🚀 Новый трендовый пост обнаружен: @{metrics.username}")
        return True
    
    async def send_telegram_alert(self, metrics: PostMetrics, chat_id: str):
        """Отправить уведомление в Telegram"""
        if not self.telegram_token:
            logger.warning("Telegram токен не настроен")
            return
        
        message = f"""
🚀 <b>Обнаружен вирусный контент!</b>

👤 Аккаунт: @{metrics.username}
📊 Просмотры: {metrics.current_views:,}
⚡️ Скорость: {metrics.views_per_hour:.0f} просм/час
📈 Рост: +{metrics.growth_rate:.0f}% от обычного

Среднее: {metrics.avg_views_per_hour:.0f} просм/час

🔗 <a href="{metrics.url}">Открыть пост</a>
        """
        
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json={
                    "chat_id": chat_id,
                    "text": message.strip(),
                    "parse_mode": "HTML"
                }) as response:
                    if response.status == 200:
                        logger.info(f"Уведомление отправлено в Telegram")
                        
                        # Помечаем как отправленное
                        conn = sqlite3.connect(self.db_path)
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE alerts SET sent_to_telegram = 1
                            WHERE post_id = ?
                        """, (metrics.post_id,))
                        conn.commit()
                        conn.close()
                    else:
                        logger.error(f"Ошибка отправки в Telegram: {response.status}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления: {e}")
    
    async def monitor_cycle(self, telegram_chat_id: Optional[str] = None):
        """Один цикл мониторинга всех конкурентов"""
        competitors = self.get_competitors()
        
        if not competitors:
            logger.warning("Нет конкурентов для мониторинга")
            return
        
        logger.info(f"Начало цикла мониторинга ({len(competitors)} аккаунтов)")
        
        for username in competitors:
            try:
                # Получаем свежие посты
                posts = await self.fetch_instagram_posts(username, limit=5)
                
                # Анализируем только посты младше 48 часов
                recent_posts = [
                    p for p in posts 
                    if (datetime.now() - p.timestamp).total_seconds() / 3600 < 48
                ]
                
                for post in recent_posts:
                    # Сохраняем текущее состояние
                    self.save_post_snapshot(post)
                    
                    # Анализируем метрики
                    metrics = self.calculate_post_metrics(post)
                    
                    # Если обнаружен тренд
                    if metrics.is_trending:
                        if self.save_alert(metrics):
                            # Отправляем уведомление
                            if telegram_chat_id:
                                await self.send_telegram_alert(metrics, telegram_chat_id)
                
                # Пауза между аккаунтами
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Ошибка при обработке @{username}: {e}")
        
        logger.info("Цикл мониторинга завершен")
    
    async def run_continuous_monitoring(
        self, 
        interval_minutes: int = 60,
        telegram_chat_id: Optional[str] = None
    ):
        """Непрерывный мониторинг с заданным интервалом"""
        logger.info(f"Запуск непрерывного мониторинга (интервал: {interval_minutes} мин)")
        
        while True:
            try:
                await self.monitor_cycle(telegram_chat_id)
                logger.info(f"Следующая проверка через {interval_minutes} минут")
                await asyncio.sleep(interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("Мониторинг остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(60)  # Пауза перед повтором


# API для фронтенда
class MonitorAPI:
    def __init__(self, monitor: InstagramMonitor):
        self.monitor = monitor
    
    def get_alerts(self, limit: int = 10) -> List[Dict]:
        """Получить последние алерты для фронтенда"""
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
                "timestamp": row[6]
            })
        
        conn.close()
        return alerts
    
    def get_competitors_stats(self) -> List[Dict]:
        """Получить статистику по конкурентам"""
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
                "avgLikes": round(row[1] * 0.08) if row[1] else 0,  # ~8% conversion
                "lastChecked": datetime.now().isoformat()
            })
        
        conn.close()
        return competitors


# Пример использования
if __name__ == "__main__":
    # Настройки
    TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Получите у @BotFather
    TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"  # Ваш Telegram ID
    
    # Инициализация
    monitor = InstagramMonitor(
        db_path="instagram_monitor.db",
        telegram_token=TELEGRAM_BOT_TOKEN
    )
    
    # Запуск мониторинга (проверка каждый час)
    asyncio.run(monitor.run_continuous_monitoring(
        interval_minutes=60,
        telegram_chat_id=TELEGRAM_CHAT_ID
    ))
