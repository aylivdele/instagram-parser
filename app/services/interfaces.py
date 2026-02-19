from typing import List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ContentType(str, Enum):
    REEL = "reel"
    POST = "post"


@dataclass
class FetchedPost:
    post_code: str
    url: str
    views: int
    likes: int
    published_at: datetime
    post_type: ContentType


class InstagramFetcherInterface:
    async def fetch_posts(self, username: str) -> List[FetchedPost]:
        raise NotImplementedError
