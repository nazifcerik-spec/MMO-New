"""Class system content: resources, weapon/armor families, base classes, Lv100 branches, Lv300 specs,
per-stage requirements and per-character class progression."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.content import ContentMixin


class ClassResource(Base, ContentMixin):
    __tablename__ = "class_resources"
    __table_args__ = (ContentMixin.status_check(), CheckConstraint("max_value > 0", name="max_positive"))

    max_value: Mapped[float] = mapped_column(Float, nullable=False)
    start_value: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    regen_per_s: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    decay_per_s: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class WeaponFamily(Base, ContentMixin):
    __tablename__ = "weapon_families"
    __table_args__ = (ContentMixin.status_check(), CheckConstraint("hands IN (1, 2)", name="hands_valid"))

    hands: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)


class ArmorFamily(Base, ContentMixin):
    __tablename__ = "armor_families"
    __table_args__ = (ContentMixin.status_check(),)


class BaseClass(Base, ContentMixin):
    __tablename__ = "base_classes"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("category IN ('combat','support')", name="category_valid"),
    )

    category: Mapped[str] = mapped_column(String(16), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role_key: Mapped[str] = mapped_column(String(200), nullable=False)
    primary_stat: Mapped[str] = mapped_column(String(3), nullable=False)
    secondary_stat: Mapped[str] = mapped_column(String(3), nullable=False)
    utility_stat: Mapped[str] = mapped_column(String(3), nullable=False)
    main_damage_stat: Mapped[str] = mapped_column(String(3), nullable=False)
    resources: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # class_resources.code
    weapon_families: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # AllowedWeaponFamily
    armor_families: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # ArmorProficiency
    dual_wield: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    item_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    base_passive_code: Mapped[str] = mapped_column(String(96), nullable=False)
    base_effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    solo_accord: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ClassBranch(Base, ContentMixin):
    """Lv100 promotion path (two per base class)."""

    __tablename__ = "class_branches"
    __table_args__ = (ContentMixin.status_check(),)

    base_class_code: Mapped[str] = mapped_column(
        ForeignKey("base_classes.code", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role_key: Mapped[str] = mapped_column(String(200), nullable=False)
    passive_code: Mapped[str] = mapped_column(String(96), nullable=False)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class Specialization(Base, ContentMixin):
    """Lv300 final specialization (two per branch → exactly 40)."""

    __tablename__ = "specializations"
    __table_args__ = (ContentMixin.status_check(),)

    branch_code: Mapped[str] = mapped_column(
        ForeignKey("class_branches.code", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role_key: Mapped[str] = mapped_column(String(200), nullable=False)
    mastery_noun_key: Mapped[str] = mapped_column(String(200), nullable=False)
    passive_code: Mapped[str] = mapped_column(String(96), nullable=False)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class ClassProgressionRequirement(Base, TimestampMixin):
    """Per-stage gate. base_class_code NULL = global default; a row per class may override."""

    __tablename__ = "class_progression_requirements"
    __table_args__ = (
        UniqueConstraint("stage", "base_class_code", postgresql_nulls_not_distinct=True),
        CheckConstraint("stage IN ('promotion','specialization','awakening','capstone','mastery')", name="stage_valid"),
        CheckConstraint("min_level BETWEEN 1 AND 1000", name="level_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    base_class_code: Mapped[str | None] = mapped_column(ForeignKey("base_classes.code", ondelete="CASCADE"))
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)
    required_quest_code: Mapped[str | None] = mapped_column(String(96))


class CharacterClassProgression(Base, TimestampMixin):
    __tablename__ = "character_class_progressions"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    base_class_code: Mapped[str] = mapped_column(ForeignKey("base_classes.code", ondelete="RESTRICT"), nullable=False)
    branch_code: Mapped[str | None] = mapped_column(ForeignKey("class_branches.code", ondelete="RESTRICT"))
    specialization_code: Mapped[str | None] = mapped_column(ForeignKey("specializations.code", ondelete="RESTRICT"))
    promoted_at: Mapped[datetime | None] = mapped_column()
    specialized_at: Mapped[datetime | None] = mapped_column()
    awakened_at: Mapped[datetime | None] = mapped_column()
    capstone_unlocked_at: Mapped[datetime | None] = mapped_column()
    mastery_at: Mapped[datetime | None] = mapped_column()
    path_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_path_change_at: Mapped[datetime | None] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}
