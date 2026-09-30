"""Inventory & equipment: stack-aware grants with a bounded overflow mailbox, atomic server-side equip/unequip
validated against gear-free stats (no circular requirement exploits), equip previews, and AFK loot/potion/
durability integrations."""

import zlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.game_engine import inventory as rules
from app.game_engine.items import requirement_check
from app.game_engine.rng import Rng, derive_seed
from app.game_engine.stat_calculator import allocation_contribution, compute_stat_sheet, contribution_from_effects
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.classes import BaseClass
from app.models.items import ItemInstance, ItemProvenance, ItemTemplate
from app.models.race import Race
from app.services import afk, afk_profiles, audit, items, progression, wallet
from app.services.content.types.balance import get_published_balance
from app.services.races import stat_label_keys

# Extra capacity sources (bags, account upgrades…): async (db, character) -> int
CAPACITY_PROVIDERS: list[Any] = []
SALVAGE_AVAILABLE = False  # flipped by the crafting/salvage system (Phase 18)


async def config(db: AsyncSession) -> rules.InventoryConfig:
    return await get_published_balance(db, "inventory", rules.InventoryConfig)


async def capacity(db: AsyncSession, character: Character, cfg: rules.InventoryConfig | None = None) -> int:
    cfg = cfg or await config(db)
    extra = 0
    for p in CAPACITY_PROVIDERS:
        extra += int(await p(db, character))
    return cfg.base_capacity + extra


async def _count(db: AsyncSession, character_id: int, location: str) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(ItemInstance)
                .where(ItemInstance.owner_character_id == character_id, ItemInstance.location == location)
            )
        ).scalar_one()
    )


async def _provenance(
    db: AsyncSession, inst: ItemInstance, event: str, key: str, character_id: int, details: dict[str, Any]
) -> bool:
    """Append a provenance event; returns False if this idempotency key was already applied."""
    exists = (await db.execute(select(ItemProvenance.id).where(ItemProvenance.idempotency_key == key))).first()
    if exists:
        return False
    db.add(
        ItemProvenance(
            instance_id=inst.id,
            provenance_id=inst.provenance_id,
            event=event,
            character_id=character_id,
            idempotency_key=key,
            details=details,
        )
    )
    await db.flush()
    return True


async def add_item(
    db: AsyncSession,
    *,
    character: Character,
    template_code: str,
    quantity: int,
    source_type: str,
    source_id: str | None,
    key: str,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Place items: merge stacks → free inventory slots → overflow mailbox → auto-sell (never lost).
    Every sub-operation is idempotent on `key`."""
    cfg = await config(db)
    tpl = await items.published_template(db, template_code)
    outcome: list[dict[str, Any]] = []
    remaining = quantity
    if tpl.stack_size > 1:
        stacks = list(
            (
                await db.execute(
                    select(ItemInstance)
                    .where(
                        ItemInstance.owner_character_id == character.id,
                        ItemInstance.template_code == tpl.code,
                        ItemInstance.template_revision_no == tpl.revision_no,
                        ItemInstance.location == "inventory",
                        ItemInstance.quantity < tpl.stack_size,
                    )
                    .order_by(ItemInstance.id)
                    .with_for_update()
                )
            ).scalars()
        )
        for i, st in enumerate(stacks):
            if remaining <= 0:
                break
            add = min(remaining, tpl.stack_size - st.quantity)
            if await _provenance(
                db, st, "stack_add", f"{key}:stack:{i}", character.id, {"qty": add, "source": source_type}
            ):
                st.quantity += add
            remaining -= add
            outcome.append({"template_code": tpl.code, "qty": add, "placed": "inventory", "instance_id": st.id})
    cap = await capacity(db, character, cfg)
    n = 0
    while remaining > 0:
        qty = min(remaining, tpl.stack_size)
        prior = await items.existing_by_key(db, character.id, f"{key}:new:{n}")
        if prior is not None:  # replay: already placed
            outcome.append(
                {"template_code": tpl.code, "qty": prior.quantity, "placed": prior.location, "instance_id": prior.id}
            )
            remaining -= qty
            n += 1
            continue
        used = await _count(db, character.id, "inventory")
        mail = await _count(db, character.id, "mail")
        location = "inventory" if used < cap else ("mail" if mail < cfg.mailbox_capacity else None)
        if location is None:
            gold = tpl.vendor_value * qty * cfg.overflow_sell_pct // 100
            if gold:
                await wallet.change_gold(
                    db,
                    character_id=character.id,
                    delta=gold,
                    reason="overflow_autosell",
                    idempotency_key=f"{key}:sell:{n}",
                    ref_type="item_template",
                    ref_id=tpl.code,
                )
            outcome.append({"template_code": tpl.code, "qty": qty, "placed": "sold", "gold": gold})
        else:
            inst = await items.create_instance(
                db,
                character=character,
                template_code=tpl.code,
                source_type=source_type,
                source_id=source_id,
                idempotency_key=f"{key}:new:{n}",
                quantity=qty,
                seed=None if seed is None else derive_seed(seed, n),
                location=location,
            )
            outcome.append({"template_code": tpl.code, "qty": qty, "placed": location, "instance_id": inst.id})
        remaining -= qty
        n += 1
    return outcome


# --------------------------------------------------------------------------- equipment
async def _class_and_race(db: AsyncSession, character: Character) -> tuple[BaseClass, Race]:
    base = await db.get(BaseClass, character.base_class_id)
    race = await db.get(Race, character.race_id)
    assert base is not None and race is not None
    return base, race


async def gear_free_primary_stats(db: AsyncSession, character: Character) -> dict[str, float]:
    """Primary stats from base + allocation + race/class/talents only — no equipment. Requirements are checked
    against these so no item (or chain of items) can enable itself."""
    cfg = await progression.load_config(db)
    alloc = await progression.get_allocation(db, character.id)
    contribs = [allocation_contribution(alloc.as_dict())]
    for provider in progression.CONTRIBUTION_PROVIDERS:
        if provider is items.equipment_contributions:
            continue
        contribs.extend(await provider(db, character))
    sheet = compute_stat_sheet(cfg, character.level, contribs)
    return {k: v for k, v in sheet.finals().items() if k.isupper()}


async def validate_equip(
    db: AsyncSession, character: Character, inst: ItemInstance, data: dict[str, Any], slot: str
) -> list[dict[str, Any]]:
    cfg = await config(db)
    base, race = await _class_and_race(db, character)
    unmet = requirement_check(
        data,
        level=character.level,
        stats=await gear_free_primary_stats(db, character),
        class_code=base.code,
        race_code=race.code,
    )
    unmet += rules.proficiency_problems(data, weapon_families=base.weapon_families, armor_families=base.armor_families)
    slot_def = cfg.slot(slot)
    if slot_def is None or data.get("slot") not in slot_def.accepts:
        unmet.append({"kind": "slot", "code": slot})
    if inst.bound and inst.owner_character_id != character.id:  # bound items never change hands
        unmet.append({"kind": "binding"})
    return unmet


async def _equipped_map(db: AsyncSession, character_id: int, *, for_update: bool = False) -> dict[str, ItemInstance]:
    stmt = select(ItemInstance).where(
        ItemInstance.owner_character_id == character_id, ItemInstance.location == "equipped"
    )
    if for_update:
        stmt = stmt.with_for_update()
    return {i.equipped_slot or "": i for i in (await db.execute(stmt)).scalars()}


async def _two_handed(db: AsyncSession, data: dict[str, Any]) -> bool:
    from app.models.classes import WeaponFamily

    wf = data.get("weapon_family")
    if not wf:
        return False
    hands = (await db.execute(select(WeaponFamily.hands).where(WeaponFamily.code == wf))).scalar_one_or_none()
    return hands == 2


async def equip(
    db: AsyncSession, *, character: Character, instance_id: int, slot: str | None, actor_id: int
) -> dict[str, Any]:
    """Atomic: row-locks the item and the current loadout; swaps the displaced item(s) back to the inventory."""
    cfg = await config(db)
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    if inst.location != "inventory":
        raise ConflictError("Only inventory items can be equipped", code="item_not_in_inventory")
    data = await items.revision_data(db, inst.template_code, inst.template_revision_no)
    if not data.get("slot"):
        raise ValidationFailedError("This item cannot be equipped", code="not_equippable")
    current = await _equipped_map(db, character.id, for_update=True)
    target = rules.pick_slot(cfg, data["slot"], set(current), slot)
    if target is None:
        raise ValidationFailedError("Incompatible equipment slot", code="slot_incompatible")
    unmet = await validate_equip(db, character, inst, data, target)
    if unmet:
        raise ValidationFailedError("Requirements not met", code="requirements_not_met", details=unmet)
    displaced = [current[target]] if target in current else []
    two_handed = await _two_handed(db, data)
    if two_handed and "off_hand" in current:
        displaced.append(current["off_hand"])
    main = current.get("main_hand")
    if target == "off_hand" and main is not None:
        main_data = await items.revision_data(db, main.template_code, main.template_revision_no)
        if await _two_handed(db, main_data):
            slot_def = cfg.slot("off_hand")
            if slot_def is not None and slot_def.blocked_by_two_handed:
                raise ConflictError("A two-handed weapon occupies the off hand", code="two_handed_blocks_off_hand")
    # the equipped item leaves the inventory (frees a slot), displaced items need space
    free = await capacity(db, character, cfg) - (await _count(db, character.id, "inventory") - 1)
    if len(displaced) > free:
        raise ConflictError("Not enough inventory space for the swapped items", code="inventory_full")
    for d in displaced:
        d.location, d.equipped_slot = "inventory", None
    await db.flush()
    inst.location, inst.equipped_slot = "equipped", target
    if data.get("bind_policy") == "on_equip" and not inst.bound:
        inst.bound = True
        await _provenance(db, inst, "bound", f"bind:{inst.id}", character.id, {"reason": "on_equip"})
    await db.flush()
    await audit.record(
        db,
        actor_id=actor_id,
        action="item.equip",
        entity_type="item_instance",
        entity_id=inst.id,
        meta={"slot": target, "displaced": [d.id for d in displaced], "character_id": character.id},
    )
    return {"slot": target, "displaced": [d.id for d in displaced]}


async def unequip(db: AsyncSession, *, character: Character, slot: str, actor_id: int) -> dict[str, Any]:
    current = await _equipped_map(db, character.id, for_update=True)
    inst = current.get(slot)
    if inst is None:
        raise NotFoundError("Nothing equipped in that slot", code="slot_empty")
    if await _count(db, character.id, "inventory") >= await capacity(db, character):
        raise ConflictError("Inventory is full", code="inventory_full")
    inst.location, inst.equipped_slot = "inventory", None
    await db.flush()
    await audit.record(
        db,
        actor_id=actor_id,
        action="item.unequip",
        entity_type="item_instance",
        entity_id=inst.id,
        meta={"slot": slot},
    )
    return {"slot": slot, "instance_id": inst.id}


async def equip_preview(db: AsyncSession, character: Character, instance_id: int) -> dict[str, Any]:
    """Derived-stat delta if this item were equipped (same calculator as the live sheet; nothing persisted)."""
    cfg = await config(db)
    inst = await items.get_owned_instance(db, character.id, instance_id)
    data = await items.revision_data(db, inst.template_code, inst.template_revision_no)
    current = await _equipped_map(db, character.id)
    target = rules.pick_slot(cfg, data["slot"], set(current), None) if data.get("slot") else None
    unmet = await validate_equip(db, character, inst, data, target) if target else [{"kind": "not_equippable"}]
    prog_cfg = await progression.load_config(db)
    alloc = await progression.get_allocation(db, character.id)
    base_contribs = [allocation_contribution(alloc.as_dict())]
    for provider in progression.CONTRIBUTION_PROVIDERS:
        if provider is not items.equipment_contributions:
            base_contribs.extend(await provider(db, character))
    loadout_now = list(current.values())
    loadout_new = [i for s, i in current.items() if s != target] + ([inst] if target else [])
    if target and await _two_handed(db, data):
        loadout_new = [i for i in loadout_new if i.equipped_slot != "off_hand"]
    now_fx = await items.equipment_effects(db, character, loadout_now)
    new_fx = await items.equipment_effects(db, character, loadout_new)
    before = compute_stat_sheet(
        prog_cfg, character.level, [*base_contribs, contribution_from_effects("equipment", "x", now_fx)]
    ).finals()
    after = compute_stat_sheet(
        prog_cfg, character.level, [*base_contribs, contribution_from_effects("equipment", "x", new_fx)]
    ).finals()
    deltas = {k: round(after[k] - before.get(k, 0), 3) for k in after if abs(after[k] - before.get(k, 0)) > 1e-9}
    return {
        "slot": target,
        "replaces": current[target].id if target and target in current else None,
        "unmet": unmet,
        "equippable": not unmet,
        "deltas": dict(sorted(deltas.items())),
    }


# --------------------------------------------------------------------------- views / mailbox / destroy
async def inventory_view(
    db: AsyncSession, character: Character, locale: str, *, location: str, after_id: int | None, limit: int
) -> dict[str, Any]:
    cfg = await config(db)
    rows = await items.list_instances(db, character.id, location=location, after_id=after_id, limit=limit)
    views = [await items.instance_view(db, r, locale, character) for r in rows]
    return {
        "items": views,
        "labels": await _labels(db, views, locale),
        "next_after_id": rows[-1].id if len(rows) == limit else None,
        "used": await _count(db, character.id, "inventory"),
        "capacity": await capacity(db, character, cfg),
        "mailbox": await _count(db, character.id, "mail"),
        "mailbox_capacity": cfg.mailbox_capacity,
        "mailbox_warn": await _count(db, character.id, "mail") >= cfg.mailbox_capacity * cfg.mailbox_warn_pct / 100,
    }


async def equipment_view(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    cfg = await config(db)
    current = await _equipped_map(db, character.id)
    sheet = await progression.stat_sheet(db, character)
    slots: list[dict[str, Any]] = [
        {
            "code": s.code,
            "accepts": list(s.accepts),
            "item": await items.instance_view(db, current[s.code], locale, character) if s.code in current else None,
        }
        for s in cfg.equipment_slots
    ]
    finals = sheet.finals()
    labels = await _labels(
        db, [x["item"] for x in slots if x["item"]], locale, extra=[f"stat.{k.lower()}.name" for k in finals]
    )
    return {
        "slots": slots,
        "labels": labels,
        "derived": {k: round(v, 3) for k, v in finals.items() if not k.isupper()},
        "primary": {k: round(v, 3) for k, v in finals.items() if k.isupper()},
    }


async def _labels(
    db: AsyncSession, views: list[dict[str, Any]], locale: str, extra: list[str] | None = None
) -> dict[str, str]:
    keys: set[str] = set(extra or [])
    for v in views:
        keys |= stat_label_keys(v["effects"])
    return await resolve_text_map(db, sorted(keys), locale) if keys else {}


async def claim_mail(db: AsyncSession, character: Character, *, actor_id: int) -> dict[str, int]:
    cfg = await config(db)
    free = await capacity(db, character, cfg) - await _count(db, character.id, "inventory")
    rows = list(
        (
            await db.execute(
                select(ItemInstance)
                .where(ItemInstance.owner_character_id == character.id, ItemInstance.location == "mail")
                .order_by(ItemInstance.id)
                .limit(max(0, free))
                .with_for_update()
            )
        ).scalars()
    )
    for r in rows:
        r.location = "inventory"
    await db.flush()
    await audit.record(
        db,
        actor_id=actor_id,
        action="item.mail_claim",
        entity_type="character",
        entity_id=character.id,
        meta={"moved": len(rows)},
    )
    return {"moved": len(rows), "remaining": await _count(db, character.id, "mail")}


async def destroy(db: AsyncSession, *, character: Character, instance_id: int, actor_id: int) -> None:
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    if inst.location not in ("inventory", "mail"):
        raise ConflictError("Unequip the item first", code="item_equipped")
    inst.location = "destroyed"
    await _provenance(db, inst, "destroyed", f"destroy:{inst.id}", character.id, {"by": actor_id})
    await audit.record(db, actor_id=actor_id, action="item.destroy", entity_type="item_instance", entity_id=inst.id)


# --------------------------------------------------------------------------- AFK integrations
async def _pool_template(db: AsyncSession, drop: dict[str, Any], seed: int) -> ItemTemplate | None:
    stmt = select(ItemTemplate).where(
        ItemTemplate.status == "published",
        ItemTemplate.deleted_at.is_(None),
        ItemTemplate.tier == drop["tier"],
        ItemTemplate.slot.is_not(None),
    )
    if drop.get("rarity"):
        stmt = stmt.where(ItemTemplate.rarity == drop["rarity"])
    if drop.get("category"):
        stmt = stmt.where(ItemTemplate.category == drop["category"])
    options = list((await db.execute(stmt.order_by(ItemTemplate.code))).scalars())
    if not options:
        return None
    return options[Rng(seed).randint(0, len(options) - 1)]


async def grant_afk_loot(
    db: AsyncSession, character: Character, drops: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    """AFK LOOT_GRANTER: resolve drops to templates, apply the player's loot filter, place or sell."""
    cfg = await config(db)
    profile = await afk_profiles.get_profile(db, character)
    lf = rules.LootFilter.model_validate(
        {
            **profile.loot_filter,
            "categories": tuple(profile.loot_filter.get("categories", ())),
            "class_tags": tuple(profile.loot_filter.get("class_tags", ())),
        }
    )
    out: list[dict[str, Any]] = []
    for i, d in enumerate(drops):
        count = int(d.get("qty", 1))
        if d["kind"] == "item_pool":
            picks = [await _pool_template(db, d, zlib.crc32(f"{key}:{i}:{n}".encode())) for n in range(count)]
            groups: dict[str, int] = {}
            for p in picks:
                if p is not None:
                    groups[p.code] = groups.get(p.code, 0) + 1
            targets = list(groups.items())
            if not targets:
                out.append({"drop": d, "placed": "none", "reason": "no_matching_template"})
        elif d["kind"] in ("item", "material") and d.get("ref"):
            targets = [(d["ref"], count)]
        else:
            continue
        for code, qty in targets:
            tpl = (await db.execute(select(ItemTemplate).where(ItemTemplate.code == code))).scalar_one_or_none()
            if tpl is None or tpl.status != "published":
                out.append({"drop": d, "placed": "none", "reason": "unknown_template"})
                continue
            tdata = {"category": tpl.category, "rarity": tpl.rarity, "tier": tpl.tier, "class_tags": tpl.class_tags}
            action = rules.evaluate_filter(lf, tdata, salvage_available=SALVAGE_AVAILABLE)
            sub = f"{key}:{i}:{code}"
            if action == "keep":
                out += await add_item(
                    db,
                    character=character,
                    template_code=code,
                    quantity=qty,
                    source_type="afk",
                    source_id=key,
                    key=sub,
                    seed=zlib.crc32(sub.encode()),
                )
            else:
                gold = tpl.vendor_value * qty * cfg.filtered_sell_pct // 100
                if gold:
                    await wallet.change_gold(
                        db,
                        character_id=character.id,
                        delta=gold,
                        reason="loot_filter_sell",
                        idempotency_key=f"{sub}:filter",
                        ref_type="item_template",
                        ref_id=code,
                    )
                out.append({"template_code": code, "qty": qty, "placed": "sold", "gold": gold, "reason": "loot_filter"})
    return out


async def _potion_stacks(db: AsyncSession, character: Character, *, for_update: bool = False) -> list[ItemInstance]:
    stmt = (
        select(ItemInstance)
        .join(ItemTemplate, ItemTemplate.code == ItemInstance.template_code)
        .where(
            ItemInstance.owner_character_id == character.id,
            ItemInstance.location == "inventory",
            ItemTemplate.category == "consumable",
            ItemTemplate.subcategory == "potion",
        )
        .order_by(ItemInstance.id)
    )
    if for_update:
        stmt = stmt.with_for_update(of=ItemInstance)
    return list((await db.execute(stmt)).scalars())


async def potion_count(db: AsyncSession, character: Character) -> int:
    return sum(s.quantity for s in await _potion_stacks(db, character))


async def consume_potions(db: AsyncSession, character: Character, qty: int, key: str) -> None:
    left = qty
    for st in await _potion_stacks(db, character, for_update=True):
        if left <= 0:
            break
        take = min(left, st.quantity)
        if not await _provenance(db, st, "consumed", f"{key}:{st.id}", character.id, {"qty": take}):
            left -= take
            continue
        left -= take
        if take == st.quantity:
            st.location = "destroyed"
        else:
            st.quantity -= take
    await db.flush()


async def apply_durability_loss(db: AsyncSession, character: Character, loss_pct: float, key: str) -> None:
    for inst in (await _equipped_map(db, character.id, for_update=True)).values():
        if not inst.durability_max:
            continue
        loss = max(1, round(inst.durability_max * loss_pct / 100))
        if await _provenance(db, inst, "durability_loss", f"{key}:{inst.id}", character.id, {"loss": loss}):
            inst.durability = max(0, inst.durability - loss)
    await db.flush()


afk.LOOT_GRANTERS.append(grant_afk_loot)
afk.POTION_CONSUMERS.append(consume_potions)
afk.DURABILITY_HANDLERS.append(apply_durability_loss)
afk_profiles.POTION_PROVIDERS.append(potion_count)
