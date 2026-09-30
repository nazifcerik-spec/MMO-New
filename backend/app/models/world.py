"""PvE world content: zone tiers, zones, enemies, enemy ability profiles, encounters, bosses, drop tables.

Nested, always-read-together structures (pools, requirements, drop entries, boss phases) are validated JSONB
arrays; cross-entity references that must stay intact use FKs on stable codes."""

from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.content import ContentMixin


class ZoneTier(Base, ContentMixin):
    __tablename__ = "zone_tiers"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint("tier BETWEEN 0 AND 10", name="tier_valid"),
        CheckConstraint("min_level >= 1 AND max_level <= 1000 AND min_level <= max_level", name="levels_valid"),
    )

    tier: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, nullable=False)
    # Zone-tier scaling, separate from per-level enemy scaling: {hp_pct, attack_pct, defense_pct, xp_pct, gold_pct}
    scaling: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rarity_band: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class EnemyAbilityProfile(Base, ContentMixin):
    __tablename__ = "enemy_ability_profiles"
    __table_args__ = (ContentMixin.status_check(),)

    abilities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class DropTable(Base, ContentMixin):
    __tablename__ = "drop_tables"
    __table_args__ = (ContentMixin.status_check(), CheckConstraint("rolls BETWEEN 0 AND 20", name="rolls_valid"))

    rolls: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # DropTableEntry list: {kind, ref?, tier?, category?, rarity?, weight, chance_pct, min_qty, max_qty, boss_only}
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class EnemyTemplate(Base, ContentMixin):
    __tablename__ = "enemy_templates"
    __table_args__ = (ContentMixin.status_check(), CheckConstraint("rank IN ('normal','elite')", name="rank_valid"))

    family: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    archetype: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    damage_type: Mapped[str] = mapped_column(String(16), nullable=False, default="physical")
    stat_mods: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # stat -> percent
    ability_profile_code: Mapped[str | None] = mapped_column(
        ForeignKey("enemy_ability_profiles.code", ondelete="RESTRICT")
    )
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reward_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=100)


class BossTemplate(Base, ContentMixin):
    __tablename__ = "boss_templates"
    __table_args__ = (ContentMixin.status_check(),)

    family: Mapped[str] = mapped_column(String(32), nullable=False)
    archetype: Mapped[str] = mapped_column(String(32), nullable=False)
    damage_type: Mapped[str] = mapped_column(String(16), nullable=False, default="physical")
    stat_mods: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ability_profile_code: Mapped[str | None] = mapped_column(
        ForeignKey("enemy_ability_profiles.code", ondelete="RESTRICT")
    )
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    phases: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    adds: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    enrage_after_s: Mapped[float | None] = mapped_column(Float)
    drop_table_code: Mapped[str | None] = mapped_column(ForeignKey("drop_tables.code", ondelete="RESTRICT"))
    reward_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)


class EncounterTemplate(Base, ContentMixin):
    __tablename__ = "encounter_templates"
    __table_args__ = (ContentMixin.status_check(),)

    members: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # {enemy_code, min, max}
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class Zone(Base, ContentMixin):
    __tablename__ = "zones"
    __table_args__ = (
        ContentMixin.status_check(),
        CheckConstraint(
            "min_level >= 1 AND min_level <= recommended_level AND recommended_level <= max_level "
            "AND max_level <= 1000",
            name="levels_valid",
        ),
        CheckConstraint("danger_rating BETWEEN 1 AND 10", name="danger_valid"),
        CheckConstraint("boss_chance_pct BETWEEN 0 AND 100", name="boss_chance_valid"),
    )

    tier_code: Mapped[str] = mapped_column(ForeignKey("zone_tiers.code", ondelete="RESTRICT"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    recommended_level: Mapped[int] = mapped_column(Integer, nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, nullable=False)
    danger_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    environment_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    encounter_pool: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # {encounter_code, weight}
    boss_pool: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)  # {boss_code, weight}
    boss_chance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    loot_modifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    drop_table_code: Mapped[str | None] = mapped_column(ForeignKey("drop_tables.code", ondelete="RESTRICT"))
    profession_nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # ZoneRequirement list: {kind: min_level|zone_cleared|class_stage|quest, value?, code?}
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
