"""Item content (templates, affixes, sets) and player-owned item instances with provenance (ADR-0004)."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.content import ContentMixin

RARITY_CHECK = "rarity IN ('worn','common','fine','rare','epic','legendary','mythic','relic')"


class ItemSet(Base, ContentMixin):
    __tablename__ = "item_sets"
    __table_args__ = (ContentMixin.status_check(),)

    bonuses: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # {pieces, effects}


class AffixDefinition(Base, ContentMixin):
    __tablename__ = "affix_definitions"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("kind IN ('prefix','suffix')", name="kind_valid"),
        CheckConstraint("tier_min BETWEEN 0 AND 10 AND tier_max BETWEEN tier_min AND 10", name="tiers_valid"),
    )

    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    group: Mapped[str] = mapped_column(String(48), nullable=False)  # mutually exclusive on one item
    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    slots: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    class_tag: Mapped[str | None] = mapped_column(String(16))
    tier_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier_max: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    rarity_min: Mapped[str] = mapped_column(String(16), nullable=False, default="common")
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    effect: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # {effect_type, params, value_param}
    rolls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # {tier_from, tier_to, min, max}


class ItemTemplate(Base, ContentMixin):
    __tablename__ = "item_templates"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("tier BETWEEN 0 AND 10", name="tier_valid"),
        CheckConstraint("min_level BETWEEN 1 AND 1000", name="min_level_valid"),
        CheckConstraint(RARITY_CHECK, name="rarity_valid"),
        CheckConstraint("stack_size BETWEEN 1 AND 9999", name="stack_size_valid"),
        CheckConstraint("vendor_value >= 0", name="vendor_value_valid"),
        CheckConstraint("bind_policy IN ('none','on_pickup','on_equip','account')", name="bind_policy_valid"),
        Index("ix_item_templates_catalog", "category", "tier", "rarity"),
    )

    short_description_key: Mapped[str | None] = mapped_column(String(200))
    lore_key: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String(32))
    family: Mapped[str | None] = mapped_column(String(48))
    slot: Mapped[str | None] = mapped_column(String(16))
    weapon_family: Mapped[str | None] = mapped_column(ForeignKey("weapon_families.code", ondelete="RESTRICT"))
    armor_family: Mapped[str | None] = mapped_column(ForeignKey("armor_families.code", ondelete="RESTRICT"))
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)
    rarity: Mapped[str] = mapped_column(String(16), nullable=False)
    stack_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    bind_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    tradeable: Mapped[bool] = mapped_column(nullable=False, default=True)
    sellable: Mapped[bool] = mapped_column(nullable=False, default=True)
    vendor_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    durability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # {max}
    sockets: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # {min, max}
    class_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    allowed_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    blocked_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    allowed_races: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    blocked_races: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    requirement_profile: Mapped[str | None] = mapped_column(String(32))
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # {stats, profession}
    base_stats: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    affix_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # {pool, min, max}
    unique_effect: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {key, effects, mastery_scaling}
    set_code: Mapped[str | None] = mapped_column(ForeignKey("item_sets.code", ondelete="RESTRICT"))
    salvage: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    icon: Mapped[str | None] = mapped_column(String(200))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class ItemInstance(Base, TimestampMixin):
    """A player-owned copy. Stats come from `template_revision_no` (never the live template) + rolled values."""

    __tablename__ = "item_instances"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="quantity_positive"),
        CheckConstraint("durability >= 0 AND durability <= durability_max", name="durability_valid"),
        CheckConstraint("upgrade_level >= 0", name="upgrade_valid"),
        CheckConstraint(
            "location IN ('inventory','equipped','bank','mail','market','destroyed')", name="location_valid"
        ),
        Index("ix_item_instances_owner_location", "owner_character_id", "location"),
        # one item per equipment slot per character
        Index(
            "uq_item_instances_equipped_slot",
            "owner_character_id",
            "equipped_slot",
            unique=True,
            postgresql_where=text("location = 'equipped'"),
        ),
        CheckConstraint("(location = 'equipped') = (equipped_slot IS NOT NULL)", name="equipped_slot_consistent"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    template_code: Mapped[str] = mapped_column(ForeignKey("item_templates.code", ondelete="RESTRICT"), nullable=False)
    template_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    affixes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    durability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    durability_max: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sockets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gems: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    bound: Mapped[bool] = mapped_column(nullable=False, default=False)
    quality: Mapped[str | None] = mapped_column(String(24))
    upgrade_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    location: Mapped[str] = mapped_column(String(16), nullable=False, default="inventory")
    equipped_slot: Mapped[str | None] = mapped_column(String(16))
    roll_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provenance_id: Mapped[Any] = mapped_column(Uuid, nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(128))
    source_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class ItemProvenance(Base):
    """Append-only item history (creation roll, binds, upgrades, transfers, destruction)."""

    __tablename__ = "item_provenance"
    __table_args__ = (
        Index("ix_item_provenance_instance", "instance_id", "created_at"),
        Index("uq_item_provenance_idem", "idempotency_key", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("item_instances.id", ondelete="CASCADE"), nullable=False)
    provenance_id: Mapped[Any] = mapped_column(Uuid, nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
