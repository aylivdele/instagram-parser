"""
ScrapeCreators implementation of InstagramFetcherInterface.

Архитектура:
- ScrapeCreators — синхронный REST API (запрос → ответ), не async-очередь.
- Каждый username обрабатывается параллельно через asyncio + aiohttp.
- Для каждого профиля полностью собирается пагинация (/v1/instagram/user/reels
  через max_id), затем callback вызывается сразу после получения всех страниц.
- process_callback вызывается по мере завершения каждого username,
  не дожидаясь остальных.

Особенность API (из документации):
- Endpoint: GET https://api.scrapecreators.com/v1/instagram/user/reels
- Параметры: handle (или user_id), max_id (курсор следующей страницы)
- Ответ: { "items": [...], "more_available": bool, "next_max_id": str }
- Каждый item: { "media": { "code", "taken_at", "play_count",
                             "like_and_view_counts_disabled",
                             "like_count" (опц.), ...} }
- Заголовок авторизации: x-api-key

Зависимости:
    pip install aiohttp

Переменные окружения:
    SCRAPECREATORS_API_KEY  — обязательно
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, List, Optional

import aiohttp

from app.db.models import InstagramAccount
from app.services.interfaces import FetchedPost, InstagramFetcherInterface

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

BASE_URL = "https://api.scrapecreators.com"
REELS_ENDPOINT = "/v1/instagram/user/reels"

# Пауза между страницами одного профиля (мс → сек).
# ScrapeCreators не имеет жёстких rate limits, но вежливая пауза снижает риск.
PAGE_DELAY_SECONDS = 0.3

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Низкоуровневый клиент
# ---------------------------------------------------------------------------

class ScrapeCreatorsClient:
    """Тонкая async-обёртка над ScrapeCreators REST API."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }
        self._session = session

    async def get_reels_page(
        self,
        handle: str,
        max_id: Optional[str] = None,
    ) -> dict:
        """
        Получить одну страницу Reels для профиля.

        Параметры:
            handle  — Instagram username
            max_id  — курсор пагинации из предыдущего ответа (None = первая страница)

        Возвращает сырой dict с полями:
            items          — список медиа-объектов
            more_available — есть ли ещё страницы
            next_max_id    — курсор следующей страницы
        """
        params: dict[str, str] = {"handle": handle}
        if max_id is not None:
            params["max_id"] = max_id

        url = f"{BASE_URL}{REELS_ENDPOINT}"
        async with self._session.get(
            url, headers=self._headers, params=params
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


# ---------------------------------------------------------------------------
# Парсинг
# ---------------------------------------------------------------------------

def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_dt(value: Any) -> datetime:
    """Преобразовать Unix timestamp (int) или ISO-строку в datetime UTC."""
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _media_to_fetched_post(media: dict) -> Optional[FetchedPost]:
    """
    Преобразовать объект media из ответа ScrapeCreators в FetchedPost.

    Структура ответа (из документации и реального примера):
        media.code          — shortcode (уникальный код)
        media.taken_at      — Unix timestamp публикации
        media.play_count    — просмотры Reel
        media.ig_play_count — (дубль) просмотры именно в Instagram
        media.like_count    — лайки (может отсутствовать)
        media.like_and_view_counts_disabled — bool
        media.media_type    — 2 = видео/Reel, 1 = фото/пост
    """
    code = media.get("code") or media.get("shortcode") or ""
    if not code:
        return None

    url = f"https://www.instagram.com/reel/{code}/"

    # Просмотры: ig_play_count точнее, play_count — fallback
    views = _safe_int(
        media.get("ig_play_count")
        or media.get("play_count")
    )

    likes = _safe_int(media.get("like_count"))

    published_at = _parse_dt(media.get("taken_at"))

    # media_type=2 → видео/Reel; product_type="clips" тоже указывает на Reel
    media_type = _safe_int(media.get("media_type"))
    product_type = str(media.get("product_type", "")).lower()
    is_reel = media_type == 2 or product_type == "clips"
    content_type = ContentType.REEL if is_reel else ContentType.POST

    return FetchedPost(
        post_code=code,
        url=url,
        views=views,
        likes=likes,
        published_at=published_at,
        post_type=content_type,
    )


def _parse_items(raw_items: List[dict]) -> List[FetchedPost]:
    posts = []
    for item in raw_items:
        # Ответ вложен: item → { "media": {...} }
        media = item.get("media") if isinstance(item.get("media"), dict) else item
        post = _media_to_fetched_post(media)
        if post is not None:
            posts.append(post)
    return posts


# ---------------------------------------------------------------------------
# Основная реализация
# ---------------------------------------------------------------------------

class ScrapeCreatorsFetcher(InstagramFetcherInterface):
    """
    Реализация InstagramFetcherInterface на базе ScrapeCreators API.

    Ключевые отличия от Lobstr-реализации:
    - API синхронный: запрос сразу возвращает данные, без polling.
    - Пагинация вручную: несколько запросов через max_id до more_available=False.
    - Каждый username обрабатывается параллельно; callback вызывается
      сразу после полной выгрузки каждого профиля.

    Пример использования:
        fetcher = ScrapeCreatorsInstagramFetcher(api_key="YOUR_KEY")

        def on_posts(posts: List[FetchedPost]) -> None:
            for p in posts:
                print(p.url, p.views)

        asyncio.run(fetcher.process_usernames(["mrbeast", "cristiano"], on_posts))
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        page_delay: float = PAGE_DELAY_SECONDS,
        max_age_hours: Optional[int] = 24,
    ) -> None:
        self._api_key = api_key or os.environ["SCRAPECREATORS_API_KEY"]
        self._page_delay = page_delay
        self._max_age_hours = max_age_hours

    async def process_usernames(
        self,
        accounts: List[InstagramAccount], 
        process_callback: Callable[[InstagramAccount, List[FetchedPost]], None]
    ) -> None:
        """
        Запускает сбор Reels для всех usernames параллельно.
        Вызывает process_callback(posts) для каждого username сразу
        после получения всех его страниц — независимо от остальных.
        """
        if not accounts:
            return

        connector = aiohttp.TCPConnector(limit=20)
        async with aiohttp.ClientSession(connector=connector) as session:
            client = ScrapeCreatorsClient(self._api_key, session)

            tasks = [
                self._fetch_one(client, account, process_callback)
                for account in accounts
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for account, result in zip(accounts, results):
            if isinstance(result, Exception):
                log.error("Ошибка при обработке @%s: %s", account.username, result)

    async def _fetch_one(
        self,
        client: ScrapeCreatorsClient,
        account: InstagramAccount,
        callback: Callable[[InstagramAccount, List[FetchedPost]], None],
    ) -> None:
      cutoff: datetime = datetime.now(tz=timezone.utc) - timedelta(hours=self._max_age_hours)
      username = account.username
      log.info("[%s] Загружаем Reels не старше %g ч (cutoff: %s)", username, self._max_age_hours, cutoff.isoformat())

      all_posts: List[FetchedPost] = []
      max_id: Optional[str] = None
      page = 0

      while True:
          page += 1
          log.debug("[%s] Страница %d (max_id=%s)", username, page, max_id)

          try:
              data = await client.get_reels_page(username, max_id=max_id)
          except aiohttp.ClientResponseError as exc:
              if exc.status == 404:
                  log.warning("[%s] Профиль не найден (404)", username)
                  break
              raise

          raw_items: List[dict] = data.get("items") or []
          posts = _parse_items(raw_items)

          # Reels на странице отсортированы от новых к старым.
          # Как только встречаем пост старше cutoff — дальше смотреть нет смысла.
          stop_pagination = False
          for post in posts:
              if post.published_at < cutoff:
                  stop_pagination = True
                  log.debug("[%s] Найден пост старше cutoff (%s), останавливаем пагинацию", username, post.published_at.isoformat())
                  break
              all_posts.append(post)

          log.debug("[%s] Страница %d: принято %d, всего: %d", username, page, len(all_posts) - (len(all_posts) - len([p for p in posts if p.published_at >= cutoff])), len(all_posts))

          if stop_pagination:
              break

          more_available: bool = data.get("more_available", False)
          next_max_id: Optional[str] = data.get("next_max_id") or None

          if not more_available or not next_max_id:
              break

          max_id = next_max_id

          if self._page_delay > 0:
              await asyncio.sleep(self._page_delay)

      log.info("[%s] Готово: %d Reels за %d страниц (не старше %g ч)", username, len(all_posts), page, self._max_age_hours)

      if all_posts:
          callback(account, all_posts)
      else:
          log.warning("[%s] Нет Reels в заданном временном окне", username)