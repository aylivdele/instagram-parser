import asyncio
import logging
from app.app_factory import AppFactory


async def main():
    logging.basicConfig(level=logging.INFO)
    factory = AppFactory()
    scheduler = factory.create_scheduler()
    await scheduler.start()


if __name__ == "__main__":
    asyncio.run(main())
