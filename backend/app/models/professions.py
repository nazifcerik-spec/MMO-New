"""Professions (content), per-character profession progress, Specialist Licenses, profession XP ledger and titles."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.content import ContentMixin


class Profession(Base, ContentMixin):
    __tablename__ = "professions"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("type IN ('gathering','crafting','service')", name="type_valid"),
    )

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    tool_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    stats: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title_key: Mapped[str] = mapped_column(String(200), nullable=False)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class ProfessionSpecialization(Base, ContentMixin):
    __tablename__ = "profession_specializations"
    __table_args__ = (ContentMixin.status_check(),)

    profession_code: Mapped[str] = mapped_column(
        ForeignKey("professions.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class CharacterProfession(Base, TimestampMixin):
    __tablename__ = "character_professions"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 500", name="level_valid"),
        CheckConstraint("xp >= 0", name="xp_valid"),
        CheckConstraint("specialization_code IS NULL OR level >= 200", name="spec_level"),
        Index("ix_character_professions_licensed", "character_id", "licensed"),
    )

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    profession_code: Mapped[str] = mapped_column(ForeignKey("professions.code", ondelete="RESTRICT"), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    xp: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    specialization_code: Mapped[str | None] = mapped_column(
        ForeignKey("profession_specializations.code", ondelete="RESTRICT")
    )
    specialized_at: Mapped[datetime | None] = mapped_column()
    licensed: Mapped[bool] = mapped_column(nullable=False, default=False)
    licensed_at: Mapped[datetime | None] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class CharacterProfessionMeta(Base, TimestampMixin):
    """Per-character license bookkeeping (activation count for free licenses, last change for the cooldown)."""

    __tablename__ = "character_profession_meta"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    license_activations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_license_change_at: Mapped[datetime | None] = mapped_column()


class ProfessionXpEvent(Base):
    """Append-only profession XP ledger; the idempotency key makes every grant exactly-once."""

    __tablename__ = "profession_xp_events"
    __table_args__ = (UniqueConstraint("character_id", "idempotency_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    profession_code: Mapped[str] = mapped_column(ForeignKey("professions.code", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    level_before: Mapped[int] = mapped_column(Integer, nullable=False)
    level_after: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class CharacterTitle(Base):
    """Earned titles (level ladder, profession grandmaster, later quests/achievements)."""

    __tablename__ = "character_titles"
    __table_args__ = (UniqueConstraint("character_id", "title_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title_code: Mapped[str] = mapped_column(String(96), nullable=False)
    title_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    earned_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
