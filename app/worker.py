import asyncio
from app.app_factory import AppFactory


async def main():
    factory = AppFactory()
    scheduler = factory.create_scheduler()
    await scheduler.start()


if __name__ == "__main__":
    asyncio.run(main())
