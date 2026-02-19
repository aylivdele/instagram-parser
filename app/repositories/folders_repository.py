from sqlalchemy import select, func
from app.db.models import Folder, UserCompetitor
from sqlalchemy.ext.asyncio import AsyncSession


class FoldersRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_folders_by_user_id(self, user_id: str):
        result = await self.session.execute(
            select(
                Folder.id,
                Folder.name,
                Folder.color,
                Folder.icon,
                func.count(UserCompetitor.id).label("count")
            )
            .outerjoin(
                UserCompetitor,
                (UserCompetitor.folder_id == Folder.id)
                & (UserCompetitor.user_id == user_id)
            )
            .where(Folder.user_id == user_id)
            .group_by(Folder.id)
        )
        return result.all()

    async def create(self, user_id: str, name: str, color: str, icon: str):
        folder = Folder(
            user_id=user_id,
            name=name,
            color=color,
            icon=icon
        )

        self.session.add(folder)
        await self.session.commit()
        await self.session.refresh(folder)
        return folder
    
    async def delete_by_folder_id_and_user_id(self, folder_id: int, user_id: str): 
        result = await self.session.execute(
            select(Folder)
            .where(Folder.id == folder_id)
            .where(Folder.user_id == user_id)
        )

        return result.scalar_one_or_none()