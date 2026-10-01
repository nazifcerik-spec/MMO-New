"""Gathering nodes, recipes, imbues (content) + recipe knowledge, craft jobs and the enchanting audit ledger."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.content import ContentMixin


class GatheringNode(Base, ContentMixin):
    __tablename__ = "gathering_nodes"
    __table_args__ = (ContentMixin.status_check(), CheckConstraint("tier BETWEEN 0 AND 10", name="tier_valid"))

    profession_code: Mapped[str] = mapped_column(ForeignKey("professions.code", ondelete="RESTRICT"), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    actions_per_hour: Mapped[float | None] = mapped_column(Float)
    entries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False
    )  # {template_code, weight, min, max, rare}


class Recipe(Base, ContentMixin):
    __tablename__ = "recipes"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("required_level BETWEEN 1 AND 500", name="level_valid"),
        CheckConstraint("recipe_rarity IN ('common','rare','epic')", name="rarity_valid"),
        CheckConstraint("craft_time_s > 0", name="time_valid"),
    )

    profession_code: Mapped[str] = mapped_column(
        ForeignKey("professions.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    required_level: Mapped[int] = mapped_column(Integer, nullable=False)
    recipe_rarity: Mapped[str] = mapped_column(String(16), nullable=False, default="common")
    unlock: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )  # {kind: auto|scroll|reputation|exploration, ref}
    scroll_template_code: Mapped[str | None] = mapped_column(ForeignKey("item_templates.code", ondelete="RESTRICT"))
    ingredients: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # {template_code, qty}
    tool_kind: Mapped[str | None] = mapped_column(String(32))
    workstation: Mapped[str | None] = mapped_column(String(32))
    craft_time_s: Mapped[float] = mapped_column(Float, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # {template_code, qty}
    quality_applies: Mapped[bool] = mapped_column(nullable=False, default=True)
    fail_chance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    fail_return_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=50)


class ImbueDefinition(Base, ContentMixin):
    __tablename__ = "imbue_definitions"
    __table_args__ = (ContentMixin.status_check(),)

    required_level: Mapped[int] = mapped_column(Integer, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    slots: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    gold_cost: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    materials: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class CharacterRecipe(Base):
    __tablename__ = "character_recipes"

    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    recipe_code: Mapped[str] = mapped_column(ForeignKey("recipes.code", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    learned_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class CraftJob(Base, TimestampMixin):
    """A queued/running batch craft. Ingredients are consumed atomically at start (recorded in `consumed`);
    cancel refunds them; claim resolves deterministically from the recipe snapshot + seed, exactly once."""

    __tablename__ = "craft_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('running','claimed','cancelled')", name="status_valid"),
        CheckConstraint("quantity BETWEEN 1 AND 1000", name="quantity_valid"),
        UniqueConstraint("character_id", "start_key"),
        Index("ix_craft_jobs_character_status", "character_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    recipe_code: Mapped[str] = mapped_column(ForeignKey("recipes.code", ondelete="RESTRICT"), nullable=False)
    recipe_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    recipe_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    start_key: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_key: Mapped[str | None] = mapped_column(String(128))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class EnchantEvent(Base):
    """Deterministic, append-only enchanting ledger (reroll / imbue / salvage): seed, before/after, costs."""

    __tablename__ = "enchant_events"
    __table_args__ = (UniqueConstraint("character_id", "idempotency_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("item_instances.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cost: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
