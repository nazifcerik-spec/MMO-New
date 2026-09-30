"""Item service: revision-pinned instances, deterministic seeded rolls with provenance, equipment effects and
requirement checks. Instances never read the live template for stats (ADR-0004)."""

import secrets
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.game_engine import items as rules_engine
from app.game_engine.stat_calculator import Contribution, contribution_from_effects
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.classes import BaseClass
from app.models.content import ContentRevision
from app.models.items import AffixDefinition, ItemInstance, ItemProvenance, ItemSet, ItemTemplate
from app.models.race import Race
from app.services import audit, combat_snapshot, progression
from app.services.content.types.items import item_rules

MAX_PAGE = 50
SEED_MASK = (1 << 62) - 1


async def published_template(db: AsyncSession, code: str) -> ItemTemplate:
    row = (
        await db.execute(
            select(ItemTemplate).where(
                ItemTemplate.code == code, ItemTemplate.status == "published", ItemTemplate.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Item not found", code="item_not_found")
    return row


async def revision_data(db: AsyncSession, code: str, revision_no: int) -> dict[str, Any]:
    rev = (
        await db.execute(
            select(ContentRevision.data).where(
                ContentRevision.entity_type == "item_template",
                ContentRevision.entity_code == code,
                ContentRevision.revision_no == revision_no,
            )
        )
    ).scalar_one_or_none()
    if rev is None:
        raise NotFoundError("Item revision not found", code="item_revision_not_found")
    return dict(rev["data"])


async def expand_pool(db: AsyncSession, pool: list[str]) -> list[dict[str, Any]]:
    codes = [p for p in pool if not p.startswith("group:")]
    groups = [p.removeprefix("group:") for p in pool if p.startswith("group:")]
    stmt = select(AffixDefinition).where(
        AffixDefinition.status == "published",
        AffixDefinition.deleted_at.is_(None),
        AffixDefinition.code.in_(codes) | AffixDefinition.group.in_(groups),
    )
    return [
        {
            "code": a.code,
            "kind": a.kind,
            "group": a.group,
            "categories": a.categories,
            "slots": a.slots,
            "class_tag": a.class_tag,
            "tier_min": a.tier_min,
            "tier_max": a.tier_max,
            "rarity_min": a.rarity_min,
            "weight": a.weight,
            "effect": a.effect,
            "rolls": a.rolls,
        }
        for a in (await db.execute(stmt)).scalars()
    ]


async def roll(db: AsyncSession, template: dict[str, Any], seed: int) -> dict[str, Any]:
    """Deterministic roll of instance state for a template revision's data."""
    rules = await item_rules(db)
    ar = template["affix_rules"]
    if template["category"] not in rules_engine.SLOTS_BY_CATEGORY:
        affixes: list[dict[str, Any]] = []
    elif rules.rarity_budgets[template["rarity"]].fixed:
        affixes = [
            {"code": f"fixed_{i}", "kind": "fixed", "value": None, "effect": f} for i, f in enumerate(ar["fixed"])
        ]
    else:
        override = (
            None if ar.get("min") is None and ar.get("max") is None else (ar.get("min") or 0, ar.get("max") or 10)
        )
        affixes = rules_engine.roll_affixes(
            rules,
            tier=template["tier"],
            rarity=template["rarity"],
            category=template["category"],
            slot=template["slot"],
            pool=await expand_pool(db, ar["pool"]),
            count_override=override,
            seed=seed,
        )
    return {
        "affixes": affixes,
        "sockets": rules_engine.roll_sockets(template["sockets"], seed),
        "durability_max": int(template["durability"].get("max", 0)),
    }


async def existing_by_key(db: AsyncSession, character_id: int, idempotency_key: str) -> ItemInstance | None:
    """The instance previously created with this grant key, if any (grant replays return it)."""
    prior = (
        await db.execute(
            select(ItemProvenance.instance_id).where(
                ItemProvenance.idempotency_key == f"create:{character_id}:{idempotency_key}"
            )
        )
    ).scalar_one_or_none()
    return await db.get(ItemInstance, prior) if prior is not None else None


async def create_instance(
    db: AsyncSession,
    *,
    character: Character,
    template_code: str,
    source_type: str,
    idempotency_key: str,
    source_id: str | None = None,
    quantity: int = 1,
    seed: int | None = None,
    actor_id: int | None = None,
    location: str = "inventory",
) -> ItemInstance:
    """Grant a new instance pinned to the current published revision. Same key ⇒ same instance (no dupes)."""
    prior = await existing_by_key(db, character.id, idempotency_key)
    if prior is not None:
        return prior
    prov_key = f"create:{character.id}:{idempotency_key}"
    tpl = await published_template(db, template_code)
    if not 1 <= quantity <= tpl.stack_size:
        raise ValidationFailedError(f"Quantity must be 1-{tpl.stack_size}", code="invalid_quantity")
    data = await revision_data(db, tpl.code, tpl.revision_no)
    seed = (seed & SEED_MASK) if seed is not None else secrets.randbits(62)  # fits signed BIGINT
    rolled = await roll(db, data, seed)
    inst = ItemInstance(
        owner_character_id=character.id,
        template_code=tpl.code,
        template_revision_no=tpl.revision_no,
        quantity=quantity,
        affixes=rolled["affixes"],
        durability=rolled["durability_max"],
        durability_max=rolled["durability_max"],
        sockets=rolled["sockets"],
        bound=data["bind_policy"] in ("on_pickup", "account"),
        roll_seed=seed,
        provenance_id=uuid.uuid4(),
        source_type=source_type,
        source_id=source_id,
        location=location,
    )
    db.add(inst)
    await db.flush()
    db.add(
        ItemProvenance(
            instance_id=inst.id,
            provenance_id=inst.provenance_id,
            event="created",
            character_id=character.id,
            actor_id=actor_id,
            idempotency_key=prov_key,
            details={
                "template": tpl.code,
                "revision_no": tpl.revision_no,
                "seed": seed,
                "source_type": source_type,
                "source_id": source_id,
                "quantity": quantity,
                "affixes": [{"code": a["code"], "value": a["value"]} for a in rolled["affixes"]],
            },
        )
    )
    await db.flush()
    return inst


async def primary_stats(db: AsyncSession, character: Character) -> dict[str, float]:
    sheet = await progression.stat_sheet(db, character)
    return {k: v for k, v in sheet.finals().items() if k.isupper()}


async def check_requirements(db: AsyncSession, character: Character, data: dict[str, Any]) -> list[dict[str, Any]]:
    base = await db.get(BaseClass, character.base_class_id)
    race = await db.get(Race, character.race_id)
    return rules_engine.requirement_check(
        data,
        level=character.level,
        stats=await primary_stats(db, character),
        class_code=base.code if base else "",
        race_code=race.code if race else "",
    )


async def instance_view(
    db: AsyncSession, inst: ItemInstance, locale: str, character: Character | None = None
) -> dict[str, Any]:
    data = await revision_data(db, inst.template_code, inst.template_revision_no)
    rules = await item_rules(db)
    keys = [f"item.{inst.template_code}.name", f"item.{inst.template_code}.description"]
    text = await resolve_text_map(db, keys, locale)
    view = {
        "id": inst.id,
        "template_code": inst.template_code,
        "template_revision_no": inst.template_revision_no,
        "name": text[keys[0]],
        "description": text.get(keys[1]),
        "category": data["category"],
        "slot": data["slot"],
        "tier": data["tier"],
        "rarity": data["rarity"],
        "min_level": data["min_level"],
        "quantity": inst.quantity,
        "affixes": inst.affixes,
        "unique_effect": data.get("unique_effect"),
        "sockets": inst.sockets,
        "gems": inst.gems,
        "durability": inst.durability,
        "durability_max": inst.durability_max,
        "bound": inst.bound,
        "upgrade_level": inst.upgrade_level,
        "location": inst.location,
        "equipped_slot": inst.equipped_slot,
        "requirements": data["requirements"],
        "effects": rules_engine.instance_effects(
            data, {"affixes": inst.affixes, "upgrade_level": inst.upgrade_level, "gems": inst.gems}, rules
        ),
        "provenance_id": str(inst.provenance_id),
        "source_type": inst.source_type,
        "bind_policy": data["bind_policy"],
        "tradeable": data["tradeable"] and not inst.bound,
        "sellable": data["sellable"],
        "vendor_value": data["vendor_value"],
        "sources": data.get("sources", []),
        "set_code": data.get("set_code"),
        "class_tags": data.get("class_tags", []),
        "weapon_family": data.get("weapon_family"),
        "armor_family": data.get("armor_family"),
    }
    if character is not None:
        unmet = await check_requirements(db, character, data)
        view["unmet"] = unmet
        view["equippable"] = not unmet and data["slot"] is not None
    return view


async def list_instances(
    db: AsyncSession, character_id: int, *, location: str | None, after_id: int | None, limit: int
) -> list[ItemInstance]:
    stmt = select(ItemInstance).where(
        ItemInstance.owner_character_id == character_id, ItemInstance.location != "destroyed"
    )
    if location:
        stmt = stmt.where(ItemInstance.location == location)
    if after_id:
        stmt = stmt.where(ItemInstance.id > after_id)
    return list((await db.execute(stmt.order_by(ItemInstance.id).limit(min(limit, MAX_PAGE)))).scalars())


async def get_owned_instance(
    db: AsyncSession, character_id: int, instance_id: int, *, for_update: bool = False
) -> ItemInstance:
    stmt = select(ItemInstance).where(
        ItemInstance.id == instance_id,
        ItemInstance.owner_character_id == character_id,
        ItemInstance.location != "destroyed",
    )
    if for_update:
        stmt = stmt.with_for_update()
    inst = (await db.execute(stmt)).scalar_one_or_none()
    if inst is None:
        raise NotFoundError("Item not found", code="item_not_found")
    return inst


async def catalog(
    db: AsyncSession,
    locale: str,
    *,
    category: str | None,
    tier: int | None,
    rarity: str | None,
    after_id: int | None,
    limit: int,
) -> dict[str, Any]:
    stmt = select(ItemTemplate).where(ItemTemplate.status == "published", ItemTemplate.deleted_at.is_(None))
    if category:
        stmt = stmt.where(ItemTemplate.category == category)
    if tier is not None:
        stmt = stmt.where(ItemTemplate.tier == tier)
    if rarity:
        stmt = stmt.where(ItemTemplate.rarity == rarity)
    if after_id:
        stmt = stmt.where(ItemTemplate.id > after_id)
    limit = max(1, min(limit, MAX_PAGE))
    rows = list((await db.execute(stmt.order_by(ItemTemplate.id).limit(limit))).scalars())
    text = await resolve_text_map(db, [r.name_key for r in rows], locale)
    total = (
        await db.execute(
            select(func.count())
            .select_from(ItemTemplate)
            .where(ItemTemplate.status == "published", ItemTemplate.deleted_at.is_(None))
        )
    ).scalar_one()
    return {
        "items": [
            {
                "code": r.code,
                "name": text[r.name_key],
                "category": r.category,
                "slot": r.slot,
                "tier": r.tier,
                "rarity": r.rarity,
                "min_level": r.min_level,
                "weapon_family": r.weapon_family,
                "armor_family": r.armor_family,
                "class_tags": r.class_tags,
                "requirements": r.requirements,
                "base_stats": r.base_stats,
                "icon": r.icon,
            }
            for r in rows
        ],
        "next_after_id": rows[-1].id if len(rows) == limit else None,
        "total_published": total,
    }


async def template_detail(db: AsyncSession, code: str, locale: str) -> dict[str, Any]:
    tpl = await published_template(db, code)
    data = await revision_data(db, tpl.code, tpl.revision_no)
    keys = [
        tpl.name_key,
        tpl.description_key or "",
        data.get("short_description_key") or "",
        data.get("lore_key") or "",
    ]
    text = await resolve_text_map(db, [k for k in keys if k], locale)
    set_info = None
    if data["set_code"]:
        s = (await db.execute(select(ItemSet).where(ItemSet.code == data["set_code"]))).scalar_one_or_none()
        if s:
            set_info = {
                "code": s.code,
                "name": (await resolve_text_map(db, [s.name_key], locale))[s.name_key],
                "bonuses": s.bonuses,
            }
    return {
        "code": tpl.code,
        "revision_no": tpl.revision_no,
        "name": text[tpl.name_key],
        "description": text.get(tpl.description_key or ""),
        "lore": text.get(data.get("lore_key") or ""),
        **{k: v for k, v in data.items() if k not in ("short_description_key", "lore_key", "affix_rules")},
        "affix_count": data["affix_rules"],
        "set": set_info,
    }


async def roll_preview(db: AsyncSession, code: str, seeds: list[int]) -> list[dict[str, Any]]:
    tpl = (await db.execute(select(ItemTemplate).where(ItemTemplate.code == code))).scalar_one_or_none()
    if tpl is None:
        raise NotFoundError("Item not found", code="item_not_found")
    from app.services.content import service as content_service
    from app.services.content.types.items import ITEM_TEMPLATE_TYPE

    data = (await content_service.working_view(db, ITEM_TEMPLATE_TYPE, tpl))["data"]
    return [{"seed": s, **await roll(db, data, s)} for s in seeds]


# --------------------------------------------------------------------------- equipment providers
async def equipped(db: AsyncSession, character: Character) -> list[ItemInstance]:
    return list(
        (
            await db.execute(
                select(ItemInstance)
                .where(ItemInstance.owner_character_id == character.id, ItemInstance.location == "equipped")
                .order_by(ItemInstance.id)
            )
        ).scalars()
    )


async def equipment_effects(
    db: AsyncSession, character: Character, instances: list[ItemInstance] | None = None
) -> list[dict[str, Any]]:
    """All effects from equipped items (revision-pinned) + active set bonuses. Broken items (0 durability) are inert.
    `instances` lets callers evaluate a hypothetical loadout (equip previews) with the same code path."""
    rules = await item_rules(db)
    out: list[dict[str, Any]] = []
    sets: dict[str, int] = {}
    for inst in instances if instances is not None else await equipped(db, character):
        if inst.durability_max and inst.durability == 0:
            continue
        data = await revision_data(db, inst.template_code, inst.template_revision_no)
        out += rules_engine.instance_effects(
            data, {"affixes": inst.affixes, "upgrade_level": inst.upgrade_level, "gems": inst.gems}, rules
        )
        if data.get("set_code"):
            sets[data["set_code"]] = sets.get(data["set_code"], 0) + 1
    if sets:
        for s in (await db.execute(select(ItemSet).where(ItemSet.code.in_(list(sets))))).scalars():
            for bonus in s.bonuses:
                if sets[s.code] >= bonus["pieces"]:
                    out += bonus["effects"]
    return out


async def equipment_contributions(db: AsyncSession, character: Character) -> list[Contribution]:
    effects = await equipment_effects(db, character)
    return [contribution_from_effects("equipment", "equipped", effects)] if effects else []


async def equipped_weapon_family(db: AsyncSession, character: Character) -> str | None:
    for inst in await equipped(db, character):
        if inst.equipped_slot == "main_hand":
            data = await revision_data(db, inst.template_code, inst.template_revision_no)
            return data.get("weapon_family")
    return None


async def audit_grant(db: AsyncSession, inst: ItemInstance, actor_id: int | None, reason: str) -> None:
    await audit.record(
        db,
        actor_id=actor_id,
        action="item.grant",
        entity_type="item_instance",
        entity_id=inst.id,
        meta={"template": inst.template_code, "character_id": inst.owner_character_id, "reason": reason},
    )


progression.CONTRIBUTION_PROVIDERS.append(equipment_contributions)
combat_snapshot.EFFECT_PROVIDERS.append(equipment_effects)
combat_snapshot.WEAPON_PROVIDERS.append(equipped_weapon_family)
