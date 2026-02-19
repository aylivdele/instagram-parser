from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, BigInteger, ForeignKey,
    DateTime, Boolean, Float, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base
import enum
from sqlalchemy import Enum


# ───────────────── USERS ─────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active: Mapped[datetime | None] = mapped_column(DateTime)

    competitors = relationship("UserCompetitor", back_populates="user", cascade="all, delete")


# ───────────────── FOLDERS ─────────────────

class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    color: Mapped[str] = mapped_column(String, default="#0088cc")
    icon: Mapped[str] = mapped_column(String, default="📁")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "name"),
    )


# ───────────────── INSTAGRAM ACCOUNTS ─────────────────

class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)
    avg_reels_views_per_hour: Mapped[float] = mapped_column(Float, default=0)
    avg_posts_views_per_hour: Mapped[float] = mapped_column(Float, default=0)

    posts = relationship("InstagramPost", back_populates="account", cascade="all, delete")


# ───────────────── USER COMPETITORS ─────────────────

class UserCompetitor(Base):
    __tablename__ = "user_competitors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("instagram_accounts.id", ondelete="CASCADE"))
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "account_id"),
    )

    user = relationship("User", back_populates="competitors")
    account = relationship("InstagramAccount")


# ───────────────── POSTS ─────────────────



class PostType(str, enum.Enum):
    REEL = "reel"
    POST = "post"

class InstagramPost(Base):
    __tablename__ = "instagram_posts"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("instagram_accounts.id"))
    post_code = Column(String, unique=True, index=True)

    post_type: Mapped[PostType] = mapped_column(
        Enum(PostType, name="post_type_enum"),
        nullable=False
    )

    url = Column(String)
    published_at = Column(DateTime, index=True)

    account = relationship("InstagramAccount", back_populates="posts")
    snapshots = relationship("PostSnapshot", back_populates="post", cascade="all, delete")



# ───────────────── SNAPSHOTS ─────────────────

class PostSnapshot(Base):
    __tablename__ = "post_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("instagram_posts.id", ondelete="CASCADE"))
    views: Mapped[int] = mapped_column(Integer)
    likes: Mapped[int] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    post = relationship("InstagramPost", back_populates="snapshots")


# ───────────────── ALERTS ─────────────────

class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    post_id: Mapped[int] = mapped_column(ForeignKey("instagram_posts.id", ondelete="CASCADE"))
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    views: Mapped[int] = mapped_column(Integer)
    views_per_hour: Mapped[float] = mapped_column(Float)
    avg_views_per_hour: Mapped[float] = mapped_column(Float)
    growth_rate: Mapped[float] = mapped_column(Float)
    sent_to_telegram: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("user_id", "post_id"),
    )
