from typing import Any, Callable, Coroutine, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.db.models import InstagramAccount


class ContentType(str, Enum):
    REEL = "reel"
    POST = "post"


@dataclass
class FetchedPost:
    post_code: str #unique id of post/reel
    url: str
    views: int
    likes: int
    published_at: datetime
    post_type: ContentType


class InstagramFetcherInterface:
    async def process_accounts(self, accounts: List[InstagramAccount], process_callback: Callable[[InstagramAccount, List[FetchedPost]], Coroutine[Any, Any, Any]]):
        raise NotImplementedError
