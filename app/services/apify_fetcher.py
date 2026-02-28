import asyncio
import json
import logging
import aiohttp
from typing import Any, Callable, Coroutine, List
from datetime import datetime

from app.db.models import InstagramAccount
from app.services.interfaces import (
    InstagramFetcherInterface,
    FetchedPost,
    ContentType
)


class ApifyFetcher(InstagramFetcherInterface):

    def __init__(
        self,
        api_token: str,
        lookback_iso: str,
        results_limit: int
    ):
        self.api_token = api_token
        self.lookback_iso = lookback_iso
        self.results_limit = results_limit
        self.base_url = "https://api.apify.com/v2"
        self.logger = logging.getLogger(__name__)


    async def process_accounts(self, accounts: List[InstagramAccount], process_callback: Callable[[InstagramAccount, List[FetchedPost]], Coroutine[Any, Any, Any]]):
        try:
            for account in accounts:
                reels = await self._fetch_by_type(account.username, "reels")
                # posts = await self._fetch_by_type(username, "posts")
                await process_callback(account, reels)

        except Exception as e:
            self.logger.exception("Apify fetcher exception")
            return []


    async def _fetch_by_type(self, username: str, results_type: str):

        print(f"[Apify Fetcher] Fetching data for username {username} with type {results_type}")
        run_id = await self._start_actor(username, results_type)
        print(f"[Apify Fetcher] Started run with id {run_id} for username {username} with type {results_type}")
        dataset_id = await self._wait_for_finish(run_id)
        print(f"[Apify Fetcher] Dataset_id for username {username} with type {results_type}: {dataset_id}")
        items = await self._get_dataset_items(dataset_id)
        print(f"[Apify Fetcher] Got {len(items)} items for username {username} with type {results_type}")

        return self._map_posts(items, results_type)

    async def _start_actor(self, username: str, results_type: str):

        actor_id = "apify~instagram-post-scraper" if results_type == "posts" else "apify~instagram-reel-scraper"

        url = f"{self.base_url}/acts/{actor_id}/runs?token={self.api_token}"

        payload = {
            "username": [username],
            "resultsLimit": self.results_limit,
            "skipPinnedPosts": True,
            "onlyPostsNewerThan": self.lookback_iso
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if 'data' not in data:
                    self.pretty_print_json(data, 100)
                    raise Exception('Unexpected answer from apify')
                return data["data"]["id"]

    async def _wait_for_finish(self, run_id: str):

        url = f"{self.base_url}/actor-runs/{run_id}?token={self.api_token}"

        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get(url) as resp:
                    data = await resp.json()
                    status = data["data"]["status"]

                    if status == "SUCCEEDED":
                        return data["data"]["defaultDatasetId"]

                    if status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                        raise Exception("Apify actor failed")

                await asyncio.sleep(5)

    async def _get_dataset_items(self, dataset_id: str):

        url = f"{self.base_url}/datasets/{dataset_id}/items?token={self.api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()
            
    

    def pretty_print_json(self, data, max_str_len: int = 200):
        def truncate(obj):
            if isinstance(obj, dict):
                return {k: truncate(v) for k, v in obj.items()}

            if isinstance(obj, list):
                return [truncate(v) for v in obj]

            if isinstance(obj, str):
                if len(obj) > max_str_len:
                    return obj[:max_str_len] + "...[TRUNCATED]"
                return obj

            return obj

        truncated = truncate(data)

        print(
            json.dumps(
                truncated,
                indent=2,
                ensure_ascii=False
            )
        )

    def _filter_apify_errors(self, items: list[dict]) -> list[dict]:
        clean_items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            if "error" in item:
                print(f"[Apify Fetcher] Skipping error item: {item} - {json.dumps(item.get('error'), indent=2)}")
                continue

            clean_items.append(item)

        return clean_items

    def _map_posts(self, items, results_type) -> List[FetchedPost]:
        items = self._filter_apify_errors(items)
        posts = []
        # self.pretty_print_json(items, 50)

        for item in items:


            if results_type == "reels":
                post_type = ContentType.REEL
                views = item.get("videoViewCount", 0)
            else:
                post_type = ContentType.POST
                views = item.get("likesCount", 0)

            posts.append(
                FetchedPost(
                    post_code=item.get("shortCode"),
                    url=item.get("url"),
                    views=views,
                    likes=item.get("likesCount", 0),
                    published_at=datetime.fromisoformat(
                        item.get("timestamp")
                    ),
                    post_type=post_type
                )
            )

        return posts
