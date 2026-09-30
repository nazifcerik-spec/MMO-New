from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.content import ContentMixin


class PassiveProfile(Base, ContentMixin):
    """Designer-authored class passive profile (rules over the class kit + identity effects)."""

    __tablename__ = "passive_profiles"
    __table_args__ = (ContentMixin.status_check(),)

    base_class_code: Mapped[str] = mapped_column(
        ForeignKey("base_classes.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # lowest = class default
    defaults: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class CharacterAfkProfile(Base, TimestampMixin):
    """The player's combat/AFK strategy (simple preset or advanced settings)."""

    __tablename__ = "character_afk_profiles"
    __table_args__ = (
        CheckConstraint("mode IN ('PASSIVE_ONLY','ACTIVE_TACTICS','HYBRID')", name="mode_valid"),
        CheckConstraint("potion_threshold_pct BETWEEN 0 AND 100", name="potion_threshold_valid"),
        CheckConstraint("risk_level IN ('safe','balanced','dangerous','elite_hunt')", name="risk_valid"),
    )

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    preset_code: Mapped[str | None] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="HYBRID")
    stance: Mapped[str] = mapped_column(String(32), nullable=False, default="efficient")
    target_priority: Mapped[str] = mapped_column(String(16), nullable=False, default="lowest_hp")
    potion_threshold_pct: Mapped[float] = mapped_column(Float, nullable=False, default=40)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")
    passive_profile_code: Mapped[str | None] = mapped_column(ForeignKey("passive_profiles.code", ondelete="SET NULL"))
    loot_filter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    tactics: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}
