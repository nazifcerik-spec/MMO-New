"""Quests (graph content), achievements (counter thresholds), per-character progress, counters and title choice."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.content import ContentMixin


class Quest(Base, ContentMixin):
    __tablename__ = "quests"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint(
            "quest_type IN ('kill','collect','profession','explore','boss','promotion','tutorial')", name="type_valid"
        ),
        CheckConstraint("min_level BETWEEN 1 AND 1000", name="level_valid"),
    )

    quest_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    chain: Mapped[str | None] = mapped_column(String(48))
    min_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prerequisites: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    class_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    objectives: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    rewards: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    repeatable: Mapped[bool] = mapped_column(nullable=False, default=False)


class Achievement(Base, ContentMixin):
    __tablename__ = "achievements"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("status_rarity IN ('bronze','silver','gold','platinum','mythic','relic')", name="rarity_valid"),
        CheckConstraint("threshold >= 1", name="threshold_valid"),
    )

    counter: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    threshold: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status_rarity: Mapped[str] = mapped_column(String(16), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    title_code: Mapped[str | None] = mapped_column(String(96))
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="general")


class CharacterQuest(Base):
    __tablename__ = "character_quests"
    __table_args__ = (
        CheckConstraint("status IN ('active','completed','claimed','abandoned')", name="status_valid"),
        Index("ix_character_quests_character_status", "character_id", "status"),
    )

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    quest_code: Mapped[str] = mapped_column(ForeignKey("quests.code", ondelete="CASCADE"), primary_key=True)
    quest_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    progress: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    accepted_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column()
    claimed_at: Mapped[datetime | None] = mapped_column()
    claim_key: Mapped[str | None] = mapped_column(String(128))
    times_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CharacterCounter(Base):
    """Aggregated lifetime counters (kills, boss kills, crafts, trades, max levels …) for achievements."""

    __tablename__ = "character_counters"
    __table_args__ = (CheckConstraint("value >= 0", name="value_non_negative"),)

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    counter: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)


class CharacterAchievement(Base):
    __tablename__ = "character_achievements"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    achievement_code: Mapped[str] = mapped_column(ForeignKey("achievements.code", ondelete="CASCADE"), primary_key=True)
    unlocked_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class CharacterTitleSelection(Base):
    """The one displayed title: 'level', 'class', 'race' or 'earned:<title_code>' (validated on read and write)."""

    __tablename__ = "character_title_selection"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    title_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)
