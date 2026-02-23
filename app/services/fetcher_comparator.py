import asyncio
from dataclasses import dataclass
import logging
from typing import List, Dict
from collections import defaultdict

from app.core.settings import Settings
from app.db.models import InstagramAccount
from app.services.apify_fetcher import ApifyFetcher
from app.services.interfaces import FetchedPost, InstagramFetcherInterface
from app.services.lobstr_fetcher import LobstrFetcher
from app.services.scrape_creators_fetcher import ScrapeCreatorsFetcher

logger = logging.getLogger(__name__)

class MultiFetcherComparator:

    def __init__(self, fetchers: List[InstagramFetcherInterface]):
        self.fetchers = fetchers
        self.logger = logger

    async def compare(self, accounts: List[InstagramAccount]):

        # results[username][fetcher_name] = [posts]
        results: Dict[str, Dict[str, List[FetchedPost]]] = defaultdict(dict)

        tasks = []

        for fetcher in self.fetchers:
          tasks.append(
              asyncio.create_task(
                  self._run_fetcher(fetcher, accounts, results)
              )
          )

        await asyncio.gather(*tasks)

        return results

    async def _run_fetcher(self, fetcher, accounts, results):
        async def callback(acc, fetched_posts):
            nonlocal results
            results[acc.username][fetcher.__class__.__name__] = fetched_posts

        try:
          await fetcher.process_accounts(accounts, callback)
        except Exception:
           self.logger.exception(f"Error running fetcher {fetcher.__class__.__name__}")

@dataclass
class SimpleAccount:
    username: str

async def main():
    settings = Settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
        handlers=[
            logging.FileHandler("debug.log", encoding="utf-8"),
            logging.StreamHandler()
        ],
    )
    fetchers = [
        ApifyFetcher(settings.APIFY_TOKEN, settings.only_posts_newer_than(), 100),
        LobstrFetcher(settings.LOBSTR_API_KEY, settings.LOBSTR_REELS_CRAWLER_HASH),
        ScrapeCreatorsFetcher(settings.SC_API_KEY, max_age_hours=settings.CONTENT_LOOKBACK_HOURS)
    ]
    comparator = MultiFetcherComparator(fetchers)
    accounts = [SimpleAccount(username="temagovorit"), SimpleAccount(username="russ.supreme"), SimpleAccount(username="theivansergeev")]
    results = await comparator.compare(accounts)
    diff_results(results)
    logger.info("\n\n------DEEP COMPARE------\n\n")
    deep_compare(results)

    


if __name__ == "__main__":
    asyncio.run(main())

def diff_results(results: Dict):

    for username, providers in results.items():

        logger.info(f"\n=== {username} ===")

        for provider, items in providers.items():
            logger.info(f"{provider}: {len(items)} рилсов")
            

        if len(providers) < 2:
            continue

        provider_names = list(providers.keys())

        base = providers[provider_names[0]]

        for other_name in provider_names[1:]:

            other = providers[other_name]

            base_codes = {p.post_code for p in base}
            other_codes = {p.post_code for p in other}

            logger.info(f"\nComparing {provider_names[0]} vs {other_name}")

            logger.info(f"[{provider_names[0]}] Missing in {other_name}:", base_codes - other_codes)
            logger.info(f"[{provider_names[0]}] Extra in {other_name}:", other_codes - base_codes)


def deep_compare(results: Dict[str, Dict[str, List[FetchedPost]]]):

    for username, providers in results.items():

        logger.info(f"\n==============================")
        logger.info(f"Account: {username}")
        logger.info(f"==============================")

        # Собираем все уникальные post_code
        all_post_codes = set()

        for posts in providers.values():
            for p in posts:
                all_post_codes.add(p.post_code)

        # Для каждого поста строим таблицу
        for post_code in sorted(all_post_codes):

            logger.info(f"\nPost: {post_code}")

            # Заголовок таблицы
            fetcher_names = list(providers.keys())
            header = ["Metric"] + fetcher_names

            # Строим строки
            rows = []

            # Индексируем посты по fetcher
            indexed = {}

            for fetcher_name, posts in providers.items():
                indexed[fetcher_name] = {
                    p.post_code: p for p in posts
                }

            # Строка просмотров
            views_row = ["views"]
            for fetcher_name in fetcher_names:
                post = indexed[fetcher_name].get(post_code)
                views_row.append(str(post.views) if post else "N/A")

            # Строка лайков
            likes_row = ["likes"]
            for fetcher_name in fetcher_names:
                post = indexed[fetcher_name].get(post_code)
                likes_row.append(str(post.likes) if post else "N/A")

            rows.append(views_row)
            rows.append(likes_row)

            print_table(header, rows)

def print_table(header, rows):

    # вычисляем ширину колонок
    columns = list(zip(header, *rows))
    col_widths = [max(len(str(cell)) for cell in col) for col in columns]

    def format_row(row):
        return " | ".join(
            str(cell).ljust(width)
            for cell, width in zip(row, col_widths)
        )

    # печать
    logger.info(format_row(header))
    logger.info("-+-".join("-" * w for w in col_widths))

    for row in rows:
        logger.info(format_row(row))