from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Character(Base, TimestampMixin):
    __tablename__ = "characters"
    __table_args__ = (
        # Case-insensitive uniqueness among live characters only (soft-deleted names are released).
        Index(
            "uq_characters_name_normalized_live",
            "name_normalized",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("level >= 1 AND level <= 1000", name="level_range"),
        CheckConstraint("xp >= 0", name="xp_non_negative"),
        CheckConstraint("unspent_stat_points >= 0", name="points_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(64), nullable=False)
    # FKs to content tables are added when race/class content lands (Phases 06/07).
    race_id: Mapped[int] = mapped_column(Integer, nullable=False)
    base_class_id: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    xp: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    unspent_stat_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_level_up_at: Mapped[datetime | None] = mapped_column()
    last_active_at: Mapped[datetime | None] = mapped_column()
    deleted_at: Mapped[datetime | None] = mapped_column()

    __mapper_args__ = {"version_id_col": version}


class CharacterSettings(Base, TimestampMixin):
    __tablename__ = "character_settings"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    stat_profile_code: Mapped[str | None] = mapped_column(String(32))
    auto_allocate: Mapped[bool] = mapped_column(default=False, nullable=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
