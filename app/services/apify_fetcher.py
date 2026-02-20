import asyncio
import aiohttp
from typing import List
from datetime import datetime

from app.services.interfaces import (
    InstagramFetcherInterface,
    FetchedPost,
    ContentType
)


class ApifyFetcher(InstagramFetcherInterface):

    def __init__(
        self,
        api_token: str,
        actor_id: str,
        lookback_iso: str,
        results_limit: int
    ):
        self.api_token = api_token
        self.actor_id = actor_id
        self.lookback_iso = lookback_iso
        self.results_limit = results_limit
        self.base_url = "https://api.apify.com/v2"

    async def fetch_posts(self, username: str) -> List[FetchedPost]:
        try:
            reels = await self._fetch_by_type(username, "reels")
            posts = await self._fetch_by_type(username, "posts")

            return reels + posts
        except Exception as e:
            print(f"[Apify Fetcher] Error: {e}")
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

        url = f"{self.base_url}/acts/{self.actor_id}/runs?token={self.api_token}"

        payload = {
            "username": username,
            "resultsType": results_type,
            "resultsLimit": self.results_limit,
            "onlyPostsNewerThan": self.lookback_iso
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
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

    def _map_posts(self, items, results_type):

        posts = []

        for item in items:

            if results_type == "reels":
                post_type = ContentType.REEL
                views = item.get("videoViewCount", 0)
            else:
                post_type = ContentType.POST
                views = item.get("likesCount", 0)

            posts.append(
                FetchedPost(
                    post_code=item["shortCode"],
                    url=item["url"],
                    views=views,
                    likes=item.get("likesCount", 0),
                    published_at=datetime.fromtimestamp(
                        item["timestamp"]
                    ),
                    post_type=post_type
                )
            )

        return posts
