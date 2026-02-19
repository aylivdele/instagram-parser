from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from fastapi import Depends, Header, HTTPException

from app.db.session import AsyncSessionLocal

async def get_user_id(x_user_id: str = Header(...)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="User ID required")
    return x_user_id


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session