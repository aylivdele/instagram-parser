"""
Lobstr.io implementation of InstagramFetcherInterface.

Стратегия переиспользования:
- Один Squid создаётся для краулера и сохраняется в SquidStore (файл/память).
- При каждом запуске проверяются существующие tasks в Squid;
  новый task добавляется только если username ещё не присутствует.
- Запускается один общий Run на весь Squid (все usernames сразу),
  результаты фильтруются по username и роздаются в callback параллельно.

Зависимости:
    pip install aiohttp

Переменные окружения:
    LOBSTR_API_KEY           — обязательно
    LOBSTR_REELS_CRAWLER     — hash краулера «Instagram Reels Scraper»
    LOBSTR_SQUID_STORE_PATH  — путь к JSON-файлу для персистентного хранения
                               squid_hash (по умолчанию ./lobstr_squid.json)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

import aiohttp

from app.db.models import InstagramAccount
from app.services.interfaces import ContentType, FetchedPost, InstagramFetcherInterface

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

BASE_URL = "https://api.lobstr.io/v1"
DEFAULT_REELS_CRAWLER_HASH = "instagram-reels-scraper"
DEFAULT_SQUID_STORE_PATH = "./lobstr_squid.json"

POLL_INTERVAL = 10
MAX_WAIT_SECONDS = 600

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SquidStore — персистентное хранение squid_hash
# ---------------------------------------------------------------------------

class SquidStore:
    """
    Хранит squid_hash для каждого crawler_hash в JSON-файле.
    Если файл недоступен — работает только в памяти (warn).
    """

    def __init__(self) -> None:
        self._data: Dict[str, str] = {}

    def get(self, crawler_hash: str) -> Optional[str]:
        return self._data.get(crawler_hash)

    def set(self, crawler_hash: str, squid_hash: str) -> None:
        self._data[crawler_hash] = squid_hash

    def delete(self, crawler_hash: str) -> None:
        self._data.pop(crawler_hash, None)


# ---------------------------------------------------------------------------
# Низкоуровневый async-клиент
# ---------------------------------------------------------------------------

class LobstrClient:
    """Тонкая async-обёртка над Lobstr.io REST API."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        self._session = session

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return await self._request_with_retry(method, path, 0, kwargs)
    
    async def _request_with_retry(self, method: str, path: str, retry_count: int = 0, **kwargs: Any):
        url = f"{BASE_URL}{path}"
        async with self._session.request(
            method, url, headers=self._headers, **kwargs
        ) as resp:
            if resp.status == 429 and retry_count < 3:
                await asyncio.sleep(70)
                return await self._request_with_retry(method, path, retry_count + 1, kwargs)
            resp.raise_for_status()
            return await resp.json()
    # --- Squids ---

    async def list_squids(self) -> List[dict]:
        """Вернуть все squids аккаунта (с учётом пагинации)."""
        squids: List[dict] = []
        page = 1
        while True:
            data = await self._request("GET", "/squids", params={"page": page})
            batch = data.get("data") or data  # API может вернуть список напрямую
            if isinstance(batch, list):
                squids.extend(batch)
            else:
                break
            # Если вернулась пустая страница или pagination закончилась
            if not batch or not data.get('next') or page > 10:
                break
            page += 1
        return squids

    async def verify_squid(self, squid_hash: str) -> bool:
        """Проверить, что squid с таким hash существует."""
        try:
            await self._request("GET", f"/squids/{squid_hash}")
            return True
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                return False
            raise

    # --- Tasks ---

    async def list_tasks(self, squid_hash: str) -> List[dict]:
        """Вернуть все tasks для данного squid."""
        tasks: List[dict] = []
        page = 1
        while True:
            params: dict[str, Any] = {"squid": squid_hash, "type": "params"}
            if page > 1:
                params["page"] = page

            data = await self._request(
                "GET", "/tasks", params=params
            )
            batch = data.get("data") or data
            if isinstance(batch, list):
                tasks.extend(batch)
            else:
                break
            if not batch or not data.get('next'):
                break
            page += 1
        return tasks

    async def add_tasks(self, squid_hash: str, profile_urls: list[str]) -> None:
        await self._request(
            "POST",
            "/tasks",
            json={
                "tasks": [{"url": url} for url in profile_urls],
                "squid": squid_hash
            },
        )
    async def remove_task(self, task_hash: str) -> None:
        await self._request(
            "DELETE",
            f"/tasks/{task_hash}",
        )

    # --- Runs ---

    async def create_run(self, squid_hash: str) -> str:
        data = await self._request("POST", "/runs", json={"squid": squid_hash})
        return data["id"]

    async def get_run_status(self, run_hash: str) -> dict:
        return await self._request("GET", f"/runs/{run_hash}")

    async def get_results(self, run_hash: str) -> List[dict]:
        results = []
        page = 1
        while True:
            params = {
                "run": run_hash,
                "page": page
            }
            data = await self._request("GET", "/results", params=params)
            batch = data.get("data") or data
            if isinstance(batch, list):
                results.extend(batch)
            else:
                break
            if not batch or not data.get('next'):
                break
            page += 1
        return results



# ---------------------------------------------------------------------------
# Парсинг
# ---------------------------------------------------------------------------

def _parse_datetime(value: Any) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _item_to_fetched_post(item: dict) -> Optional[FetchedPost]:
    post_code = item.get("shortcode") or item.get("post_code") or item.get("code") or ""
    if not post_code:
        return None

    url = (
        item.get("reel_url")
        or item.get("post_url")
        or item.get("url")
        or f"https://www.instagram.com/reel/{post_code}/"
    )
    views = _parse_int(
        item.get("views_count") or item.get("video_view_count")
        or item.get("views") or item.get("play_count")
    )
    likes = _parse_int(
        item.get("likes_count") or item.get("like_count") or item.get("likes")
    )
    published_at = _parse_datetime(
        item.get("timestamp") or item.get("posted_at")
        or item.get("taken_at_timestamp") or item.get("taken_at")
    )
    product_type = str(item.get("product_type", "")).lower()
    is_video = bool(item.get("is_video") or item.get("is_reel"))
    content_type = ContentType.REEL if (product_type == "clips" or is_video) else ContentType.POST

    return FetchedPost(
        post_code=post_code,
        url=url,
        views=views,
        likes=likes,
        published_at=published_at,
        post_type=content_type,
    )


def _parse_results(raw_items: List[dict], username: str) -> List[FetchedPost]:
    posts = []
    for item in raw_items:
        # Фильтрация по username
        input_url = item.get("input_url")
        if not input_url:
            owner = item.get("owner_username") or item.get("username") or ""
            if not owner and isinstance(item.get("owner"), dict):
                owner = item["owner"].get("username", "")
            if owner and owner.lower() != username.lower():
                continue
        else:
            parts = [p for p in input_url.rstrip("/").split("/") if p]
            if not parts or username != parts[-1]:
                continue
        
        post = _item_to_fetched_post(item)
        if post is not None:
            posts.append(post)
    return posts


# ---------------------------------------------------------------------------
# Менеджер Squid — инкапсулирует логику get-or-create + sync tasks
# ---------------------------------------------------------------------------

class SquidManager:
    """
    Отвечает за получение (или создание) единственного Squid для краулера
    и синхронизацию списка tasks с нужными usernames.
    """

    def __init__(
        self,
        client: LobstrClient,
        crawler_hash: str,
        store: SquidStore,
    ) -> None:
        self._client = client
        self._crawler_hash = crawler_hash
        self._store = store

    async def get_squid(self) -> str:
        """Вернуть существующий squid_hash или создать новый."""
        # 1. Проверяем локальный store
        squid_hash = self._store.get(self._crawler_hash)
        if squid_hash:
            log.info("Проверяем сохранённый Squid: %s", squid_hash)
            if await self._client.verify_squid(squid_hash):
                log.info("Squid %s существует, переиспользуем", squid_hash)
                return squid_hash
            else:
                log.warning("Squid %s не найден в API, ищем среди существующих", squid_hash)
                self._store.delete(self._crawler_hash)

        # 2. Ищем среди существующих squids по crawler_hash
        log.info("Ищем существующий Squid для краулера %s...", self._crawler_hash)
        all_squids = await self._client.list_squids()
        for sq in all_squids:
            if sq.get("crawler") == self._crawler_hash:
                squid_hash = sq["id"]
                log.info("Найден существующий Squid: %s", squid_hash)
                self._store.set(self._crawler_hash, squid_hash)
                return squid_hash

        raise Exception(f"Not found existing squid with crawler_hash: {self._crawler_hash}")

    async def ensure_tasks(self, squid_hash: str, usernames: List[str]) -> None:
        """
        Синхронизирует tasks в Squid с переданным списком usernames:
        - добавляет tasks для новых usernames (которых ещё нет в Squid)
        - удаляет tasks для лишних usernames (которых нет в переданном списке)
        """
        existing_tasks = await self._client.list_tasks(squid_hash)

        # Строим индекс: username → task_hash (для точечного удаления)
        existing: Dict[str, str] = {}  # username.lower() → task["hash"]
        for task in existing_tasks:
            value: str = (task.get("params") or {}).get("url") or ""
            parts = [p for p in value.rstrip("/").split("/") if p]
            if parts:
                existing[parts[-1].lower()] = task["id"]

        target = {u.lower() for u in usernames}

        if existing:
            log.info("Squid уже содержит tasks для: %s", sorted(existing.keys()))

        # --- Удаляем лишние ---
        to_delete = {u: h for u, h in existing.items() if u not in target}
        if to_delete:
            log.info("Удаляем лишние tasks для: %s", sorted(to_delete.keys()))
            await asyncio.gather(*[
                self._client.remove_task(task_hash)
                for task_hash in to_delete.values()
            ])
        else:
            log.info("Лишних tasks нет — удалять нечего")

        # --- Добавляем недостающие ---
        to_add = [f"https://www.instagram.com/{u}/" for u in usernames if u.lower() not in existing.keys()]
        if to_add:
            log.info("Добавляем tasks для новых usernames: %s", to_add)
            await self._client.add_tasks(squid_hash, to_add)
        else:
            log.info("Все нужные usernames уже присутствуют в Squid")


# ---------------------------------------------------------------------------
# Основная реализация
# ---------------------------------------------------------------------------

class LobstrFetcher(InstagramFetcherInterface):
    """
    Реализация InstagramFetcherInterface на базе Lobstr.io.

    Поведение при каждом вызове process_usernames:
    1. Берётся (или создаётся) один переиспользуемый Squid, привязанный к crawler.
    2. Для каждого username проверяется наличие task — добавляется только при отсутствии.
    3. Запускается один Run на весь Squid.
    4. После завершения результаты фильтруются по username и
       callback вызывается параллельно для каждого из них.

    Пример использования:
        fetcher = LobstrInstagramFetcher(
            api_key="YOUR_KEY",
            crawler_hash="YOUR_CRAWLER_HASH",
        )

        def on_posts(posts: List[FetchedPost]) -> None:
            for p in posts:
                print(p.url, p.views)

        asyncio.run(fetcher.process_usernames(["mrbeast", "cristiano"], on_posts))
    """

    def __init__(
        self,
        api_key: str,
        crawler_hash: Optional[str] = None,
        poll_interval: int = POLL_INTERVAL,
        max_wait_seconds: int = MAX_WAIT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._crawler_hash = (
            crawler_hash
            or DEFAULT_REELS_CRAWLER_HASH
        )
        self._poll_interval = poll_interval
        self._max_wait_seconds = max_wait_seconds

    async def process_accounts(
        self,
        accounts: List[InstagramAccount],
        process_callback: Callable[[InstagramAccount, List[FetchedPost]], None],
    ) -> None:
        if not accounts:
            return
        try:
            async with aiohttp.ClientSession() as session:
                client = LobstrClient(self._api_key, session)
                store = SquidStore()
                manager = SquidManager(client, self._crawler_hash, store)

                # 1. Получаем переиспользуемый Squid
                squid_hash = await manager.get_squid()

                usernames = [account.username for account in accounts]

                # 2. Синхронизируем tasks (добавляем только новые usernames)
                await manager.ensure_tasks(squid_hash, usernames)

                # 3. Запускаем один общий Run
                log.info("Запускаем Run для Squid %s (%d usernames)...", squid_hash, len(usernames))
                run_hash = await client.create_run(squid_hash)
                log.info("Run запущен: %s", run_hash)

                # 4. Ждём завершения
                all_results = await self._poll_until_done(client, run_hash)
                log.info("Run завершён, всего результатов: %d", len(all_results))

            # 5. Параллельно фильтруем по username и вызываем callback
            # (вне aiohttp.ClientSession — сессия больше не нужна)
            await asyncio.gather(*[
                self._dispatch(all_results, account, process_callback)
                for account in accounts
            ], return_exceptions=True)
        except Exception:
            log.exception("Exception while processing accounts")

    async def _dispatch(
        self,
        all_results: List[dict],
        account: InstagramAccount,
        callback: Callable[[InstagramAccount, List[FetchedPost]], None],
    ) -> None:
        posts = _parse_results(all_results, username=account.username)
        if posts:
            log.info("[%s] Передаём %d записей в callback", account.username, len(posts))
            callback(account, posts)
        else:
            log.warning("[%s] Результатов не найдено", account.username)

    async def _poll_until_done(
        self, client: LobstrClient, run_hash: str
    ) -> List[dict]:
        elapsed = 0
        while elapsed < self._max_wait_seconds:
            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

            try:
                status_data = await client.get_run_status(run_hash)
            except Exception as exc:
                log.warning("Ошибка при polling run %s: %s, retry...", run_hash, exc)
                continue

            status = status_data.get("status", "")
            export_done = status_data.get("export_done", False)
            log.debug("run=%s status=%s export_done=%s elapsed=%ds",
                      run_hash, status, export_done, elapsed)

            if status == "error":
                raise RuntimeError(f"Run {run_hash} завершился с ошибкой")

            if export_done:
                return await client.get_results(run_hash)

        raise TimeoutError(
            f"Run {run_hash} не завершился за {self._max_wait_seconds}с"
        )
