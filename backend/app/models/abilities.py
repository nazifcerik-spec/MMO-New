"""Abilities (active/passive/ultimate/stance/aura/proc), talent trees & nodes, awakenings, masteries."""

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.content import ContentMixin

ABILITY_TYPES = ("ACTIVE", "PASSIVE", "ULTIMATE", "STANCE", "AURA", "PROC")


class AbilityDefinition(Base, ContentMixin):
    """`ranks` holds the AbilityRank list: [{rank, cost:{resource,amount}|null, cooldown_s, cast_time_s,
    effects:[AbilityEffect...]}]. `trigger` classifies passive triggers for UI/tactics (PassiveTrigger)."""

    __tablename__ = "ability_definitions"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("ability_type IN ('ACTIVE','PASSIVE','ULTIMATE','STANCE','AURA','PROC')", name="type_valid"),
        CheckConstraint("owner_type IN ('class','branch','specialization','global')", name="owner_valid"),
        CheckConstraint("unlock_level BETWEEN 1 AND 1000", name="unlock_level_valid"),
    )

    owner_type: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_code: Mapped[str | None] = mapped_column(String(96), index=True)
    ability_type: Mapped[str] = mapped_column(String(16), nullable=False)
    unlock_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    target_rule: Mapped[str] = mapped_column(String(24), nullable=False, default="self")
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    ranks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TalentTree(Base, ContentMixin):
    __tablename__ = "talent_trees"
    __table_args__ = (ContentMixin.status_check(),)

    base_class_code: Mapped[str] = mapped_column(
        ForeignKey("base_classes.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    focus_key: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TalentNode(Base, ContentMixin):
    """Node effects are per rank (scaled by allocated rank). `requires` = TalentEdge prerequisites."""

    __tablename__ = "talent_nodes"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("tier BETWEEN 1 AND 6", name="tier_valid"),
        CheckConstraint("max_rank BETWEEN 1 AND 10", name="max_rank_valid"),
    )

    tree_code: Mapped[str] = mapped_column(
        ForeignKey("talent_trees.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    max_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    required_points_in_tree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_capstone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    archetype_key: Mapped[str | None] = mapped_column(String(200))
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class AwakeningDefinition(Base, ContentMixin):
    __tablename__ = "awakening_definitions"
    __table_args__ = (ContentMixin.status_check(),)

    specialization_code: Mapped[str] = mapped_column(
        ForeignKey("specializations.code", ondelete="RESTRICT"), nullable=False, unique=True
    )
    required_level: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class MasteryDefinition(Base, ContentMixin):
    __tablename__ = "mastery_definitions"
    __table_args__ = (ContentMixin.status_check(),)

    base_class_code: Mapped[str] = mapped_column(
        ForeignKey("base_classes.code", ondelete="RESTRICT"), nullable=False, unique=True
    )
    required_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    cosmetic_code: Mapped[str] = mapped_column(String(96), nullable=False)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class CharacterTalentAllocation(Base, TimestampMixin):
    __tablename__ = "character_talent_allocations"
    __table_args__ = (CheckConstraint("rank >= 1", name="rank_positive"),)

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    node_code: Mapped[str] = mapped_column(ForeignKey("talent_nodes.code", ondelete="RESTRICT"), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
