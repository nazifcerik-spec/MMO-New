"""Pure inventory/equipment rules: data-driven slots, equip validation (gear-free requirements) and the loot
filter contract."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.game_engine.items import RARITY_ORDER


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EquipmentSlot(_S):
    code: str = Field(pattern=r"^[a-z0-9_]+$")
    accepts: tuple[str, ...] = Field(min_length=1)
    blocked_by_two_handed: bool = False


class InventoryConfig(_S):
    equipment_slots: tuple[EquipmentSlot, ...] = Field(min_length=1)
    base_capacity: int = Field(ge=1, le=10_000)
    mailbox_capacity: int = Field(ge=0, le=10_000)
    overflow_sell_pct: int = Field(ge=0, le=100)
    filtered_sell_pct: int = Field(ge=0, le=100)
    mailbox_warn_pct: int = Field(ge=1, le=100)

    def slot(self, code: str) -> EquipmentSlot | None:
        return next((s for s in self.equipment_slots if s.code == code), None)

    def slots_for(self, item_slot: str) -> list[str]:
        return [s.code for s in self.equipment_slots if item_slot in s.accepts]


def pick_slot(cfg: InventoryConfig, item_slot: str, occupied: set[str], requested: str | None) -> str | None:
    """Requested slot if compatible; else the first free compatible slot; else the first compatible one."""
    options = cfg.slots_for(item_slot)
    if requested is not None:
        return requested if requested in options else None
    free = [s for s in options if s not in occupied]
    choices = free or options
    return choices[0] if choices else None


def proficiency_problems(
    template: dict[str, Any], *, weapon_families: list[str], armor_families: list[str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    wf, af = template.get("weapon_family"), template.get("armor_family")
    if wf and wf not in weapon_families:
        out.append({"kind": "weapon_proficiency", "code": wf})
    if af and af not in armor_families:
        out.append({"kind": "armor_proficiency", "code": af})
    return out


class LootFilter(_S):
    """Player loot filter contract (applied at AFK claim). auto_salvage is accepted now and honoured once the
    salvage system exists; until then rejected items are sold to the vendor (never silently lost)."""

    min_rarity: Literal["worn", "common", "fine", "rare", "epic", "legendary", "mythic", "relic"] = "common"
    categories: tuple[str, ...] = ()
    min_tier: int = Field(default=0, ge=0, le=10)
    class_tags: tuple[str, ...] = ()
    keep_materials: bool = True
    auto_salvage: bool = False


LootAction = Literal["keep", "sell", "salvage"]


def evaluate_filter(f: LootFilter, template: dict[str, Any], *, salvage_available: bool = False) -> LootAction:
    category = template["category"]
    if category == "material" and f.keep_materials:
        return "keep"
    if category in ("quest_key_token",):
        return "keep"  # never filter progression items
    rejected = (
        RARITY_ORDER.index(template["rarity"]) < RARITY_ORDER.index(f.min_rarity)
        or template["tier"] < f.min_tier
        or (f.categories and category not in f.categories)
        or (f.class_tags and template.get("class_tags") and not set(f.class_tags) & set(template["class_tags"]))
    )
    if not rejected:
        return "keep"
    return "salvage" if f.auto_salvage and salvage_available else "sell"
