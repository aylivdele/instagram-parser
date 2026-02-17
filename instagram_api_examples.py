"""
Пример интеграции с реальными Instagram API
Выберите один из вариантов ниже
"""

import aiohttp
import asyncio
from typing import List
from datetime import datetime
from instagram_monitor import Post

# ============================================================================
# ВАРИАНТ 1: Apify Instagram Scraper (Рекомендуется)
# Платный, но надежный. ~$50/месяц для среднего использования
# https://apify.com/apify/instagram-scraper
# ============================================================================

APIFY_TOKEN = "ваш_apify_token"

async def fetch_instagram_posts_apify(username: str, limit: int = 10) -> List[Post]:
    """
    Получение постов через Apify Instagram Scraper
    """
    # Запуск актора
    run_url = "https://api.apify.com/v2/acts/apify~instagram-scraper/runs"
    
    payload = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": limit,
        "searchType": "hashtag",
        "searchLimit": 1
    }
    
    headers = {
        "Authorization": f"Bearer {APIFY_TOKEN}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        # Запускаем актор
        async with session.post(run_url, json=payload, headers=headers) as resp:
            run_data = await resp.json()
            run_id = run_data["data"]["id"]
        
        # Ждем завершения
        await asyncio.sleep(10)
        
        # Получаем результаты
        dataset_url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
        async with session.get(dataset_url) as resp:
            items = await resp.json()
        
        # Преобразуем в Post объекты
        posts = []
        for item in items[:limit]:
            posts.append(Post(
                post_id=item["id"],
                username=username,
                url=item["url"],
                views=item.get("videoViewCount", 0) or item.get("likesCount", 0) * 10,  # Приблизительная оценка
                likes=item["likesCount"],
                timestamp=datetime.fromisoformat(item["timestamp"].replace('Z', '+00:00'))
            ))
        
        return posts


# ============================================================================
# ВАРИАНТ 2: RapidAPI Instagram API
# Различные тарифы, от бесплатного до $200/месяц
# https://rapidapi.com/hub
# ============================================================================

RAPIDAPI_KEY = "ваш_rapidapi_ключ"

async def fetch_instagram_posts_rapidapi(username: str, limit: int = 10) -> List[Post]:
    """
    Получение постов через RapidAPI
    """
    url = "https://instagram-scraper-api2.p.rapidapi.com/v1/posts"
    
    querystring = {
        "username_or_id_or_url": username,
        "url_embed_safe": "true"
    }
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "instagram-scraper-api2.p.rapidapi.com"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=querystring) as resp:
            data = await resp.json()
        
        posts = []
        items = data.get("data", {}).get("items", [])[:limit]
        
        for item in items:
            posts.append(Post(
                post_id=item["id"],
                username=username,
                url=f"https://instagram.com/p/{item['code']}/",
                views=item.get("video_view_count", 0) or item.get("like_count", 0) * 10,
                likes=item.get("like_count", 0),
                timestamp=datetime.fromtimestamp(item["taken_at"])
            ))
        
        return posts


# ============================================================================
# ВАРИАНТ 3: Instagram Graph API (Официальный)
# Бесплатный, но требует Instagram Business аккаунт
# https://developers.facebook.com/docs/instagram-api
# ============================================================================

INSTAGRAM_ACCESS_TOKEN = "ваш_access_token"
INSTAGRAM_BUSINESS_ACCOUNT_ID = "ваш_business_account_id"

async def fetch_instagram_posts_official(username: str = None, limit: int = 10) -> List[Post]:
    """
    Получение постов через официальный Instagram Graph API
    
    ВАЖНО: Может получать только собственные посты, не конкурентов!
    Для мониторинга конкурентов используйте другие варианты.
    """
    url = f"https://graph.instagram.com/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media"
    
    params = {
        "fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count",
        "access_token": INSTAGRAM_ACCESS_TOKEN,
        "limit": limit
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
        
        posts = []
        for item in data.get("data", []):
            # Для видео можно получить просмотры через дополнительный запрос
            views = 0
            if item["media_type"] == "VIDEO":
                insights_url = f"https://graph.instagram.com/{item['id']}/insights"
                insights_params = {
                    "metric": "video_views",
                    "access_token": INSTAGRAM_ACCESS_TOKEN
                }
                async with session.get(insights_url, params=insights_params) as insights_resp:
                    insights_data = await insights_resp.json()
                    if "data" in insights_data and len(insights_data["data"]) > 0:
                        views = insights_data["data"][0]["values"][0]["value"]
            
            posts.append(Post(
                post_id=item["id"],
                username=username or "me",
                url=item["permalink"],
                views=views or item.get("like_count", 0) * 10,
                likes=item.get("like_count", 0),
                timestamp=datetime.fromisoformat(item["timestamp"].replace('Z', '+00:00'))
            ))
        
        return posts


# ============================================================================
# ВАРИАНТ 4: Instaloader (Веб-скрапинг)
# Бесплатный, но может нарушать ToS Instagram
# Требует установки: pip install instaloader
# ============================================================================

try:
    import instaloader
    
    async def fetch_instagram_posts_instaloader(username: str, limit: int = 10) -> List[Post]:
        """
        Получение постов через Instaloader
        
        ПРЕДУПРЕЖДЕНИЕ: Может привести к блокировке аккаунта.
        Используйте на свой риск.
        """
        L = instaloader.Instaloader()
        
        # Опционально: авторизация для большей стабильности
        # L.login("ваш_instagram_login", "ваш_пароль")
        
        profile = instaloader.Profile.from_username(L.context, username)
        
        posts = []
        for post in profile.get_posts():
            if len(posts) >= limit:
                break
            
            posts.append(Post(
                post_id=post.shortcode,
                username=username,
                url=f"https://instagram.com/p/{post.shortcode}/",
                views=post.video_view_count if post.is_video else post.likes * 10,
                likes=post.likes,
                timestamp=post.date_utc
            ))
        
        return posts
        
except ImportError:
    print("Instaloader не установлен. Установите: pip install instaloader")


# ============================================================================
# Как использовать в instagram_monitor.py:
# ============================================================================

"""
В файле instagram_monitor.py замените метод fetch_instagram_posts:

async def fetch_instagram_posts(self, username: str, limit: int = 10) -> List[Post]:
    # Выберите один из вариантов выше:
    
    # return await fetch_instagram_posts_apify(username, limit)
    # return await fetch_instagram_posts_rapidapi(username, limit)
    # return await fetch_instagram_posts_official(username, limit)
    # return await fetch_instagram_posts_instaloader(username, limit)
    
    pass
"""


# ============================================================================
# Тестирование
# ============================================================================

async def test_api():
    """Протестируйте выбранный API"""
    print("Тестирование Instagram API...")
    
    # Раскомментируйте нужный вариант
    # posts = await fetch_instagram_posts_apify("nike", limit=3)
    # posts = await fetch_instagram_posts_rapidapi("nike", limit=3)
    # posts = await fetch_instagram_posts_official(limit=3)
    # posts = await fetch_instagram_posts_instaloader("nike", limit=3)
    
    # for post in posts:
    #     print(f"Post: {post.url}")
    #     print(f"  Likes: {post.likes}")
    #     print(f"  Views: {post.views}")
    #     print(f"  Time: {post.timestamp}")
    #     print()

if __name__ == "__main__":
    asyncio.run(test_api())
