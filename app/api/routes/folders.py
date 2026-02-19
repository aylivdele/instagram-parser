from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.api.dependencies import get_session, get_user_id
from app.db.models import Folder, UserCompetitor
from app.repositories.folders_repository import FoldersRepository
from pydantic import BaseModel

router = APIRouter()


class CreateFolderRequest(BaseModel):
    name: str
    color: str
    icon: str


@router.post("/folders")
async def create_folder(
    request: CreateFolderRequest,
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):

    repo = FoldersRepository(session)
    folder = await repo.create(user_id, request.name, request.color, request.icon)

    return {
        "success": True,
        "data": {
            "id": folder.id
        }
    }


@router.get("/folders")
async def get_folders(
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):
    repo = FoldersRepository(session)
    rows = await repo.get_folders_by_user_id(user_id)

    folders = [
        {
            "id": row.id,
            "name": row.name,
            "color": row.color,
            "icon": row.icon,
            "count": row.count
        }
        for row in rows
    ]

    return {
        "success": True,
        "data": folders
    }

@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: int,
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session)
):

    repo = FoldersRepository(session)
    folder = repo.delete_by_folder_id_and_user_id(folder_id, user_id)

    if not folder:
        return {"success": False, "error": "Folder not found"}

    await session.delete(folder)
    await session.commit()

    return {"success": True}
