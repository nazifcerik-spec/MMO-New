"""Crafting, recipe knowledge, AFK gathering tasks and enchanting (reroll / imbue / salvage).

Transaction safety: ingredients/materials are consumed under row locks in the same transaction that creates the
job or event; cancellations refund via idempotent grants; claims are exactly-once (job status + key); every
enchanting action is written to the deterministic `enchant_events` ledger."""

import secrets
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.game_engine import crafting as engine
from app.game_engine import professions as prof_rules
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.content import ContentRevision
from app.models.crafting import CharacterRecipe, CraftJob, EnchantEvent, GatheringNode, ImbueDefinition, Recipe
from app.models.items import AffixDefinition, ItemInstance, ItemProvenance, ItemTemplate
from app.services import afk, audit, inventory, items, professions, wallet
from app.services.content.types.balance import get_published_balance

MAX_HISTORY = 50


def now_utc() -> datetime:
    return datetime.now(UTC)


async def config(db: AsyncSession) -> engine.CraftingConfig:
    return await get_published_balance(db, "crafting", engine.CraftingConfig)


# --------------------------------------------------------------------------- inventory helpers
async def count_in_bag(db: AsyncSession, character_id: int, template_code: str) -> int:
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(ItemInstance.quantity), 0)).where(
                    ItemInstance.owner_character_id == character_id,
                    ItemInstance.template_code == template_code,
                    ItemInstance.location == "inventory",
                )
            )
        ).scalar_one()
    )


async def consume(
    db: AsyncSession, character: Character, template_code: str, qty: int, key: str
) -> list[dict[str, Any]]:
    """Consume `qty` of a template from the bag under row locks (oldest stacks first). All-or-nothing."""
    stacks = list(
        (
            await db.execute(
                select(ItemInstance)
                .where(
                    ItemInstance.owner_character_id == character.id,
                    ItemInstance.template_code == template_code,
                    ItemInstance.location == "inventory",
                )
                .order_by(ItemInstance.id)
                .with_for_update()
            )
        ).scalars()
    )
    if sum(s.quantity for s in stacks) < qty:
        raise ConflictError(
            "Not enough materials", code="missing_materials", details={"template_code": template_code, "needed": qty}
        )
    taken: list[dict[str, Any]] = []
    left = qty
    for st in stacks:
        if left <= 0:
            break
        take = min(left, st.quantity)
        db.add(
            ItemProvenance(
                instance_id=st.id,
                provenance_id=st.provenance_id,
                event="consumed",
                character_id=character.id,
                idempotency_key=f"{key}:{st.id}",
                details={"qty": take},
            )
        )
        if take == st.quantity:
            st.location = "destroyed"
        else:
            st.quantity -= take
        left -= take
        taken.append({"instance_id": st.id, "template_code": template_code, "qty": take})
    await db.flush()
    return taken


async def _revision(db: AsyncSession, entity_type: str, code: str, revision_no: int) -> dict[str, Any]:
    data: dict[str, Any] = (
        await db.execute(
            select(ContentRevision.data).where(
                ContentRevision.entity_type == entity_type,
                ContentRevision.entity_code == code,
                ContentRevision.revision_no == revision_no,
            )
        )
    ).scalar_one()
    return dict(data["data"])


# --------------------------------------------------------------------------- recipes
async def _recipe(db: AsyncSession, code: str) -> Recipe:
    r = (
        await db.execute(
            select(Recipe).where(Recipe.code == code, Recipe.status == "published", Recipe.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Recipe not found", code="recipe_not_found")
    return r


async def known_codes(db: AsyncSession, character_id: int) -> set[str]:
    return set(
        (
            await db.execute(select(CharacterRecipe.recipe_code).where(CharacterRecipe.character_id == character_id))
        ).scalars()
    )


def is_known(recipe: Recipe, learned: set[str]) -> bool:
    return recipe.unlock.get("kind") == "auto" or recipe.code in learned


async def learn_from_scroll(
    db: AsyncSession, *, character: Character, instance_id: int, actor_id: int
) -> dict[str, Any]:
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    recipe = (
        await db.execute(
            select(Recipe).where(Recipe.scroll_template_code == inst.template_code, Recipe.status == "published")
        )
    ).scalar_one_or_none()
    if recipe is None or inst.location != "inventory":
        raise ValidationFailedError("This item does not teach a recipe", code="not_a_recipe_scroll")
    if recipe.code in await known_codes(db, character.id):
        raise ConflictError("Recipe already known", code="recipe_known")
    await consume(db, character, inst.template_code, 1, f"learn:{recipe.code}")
    await db.execute(
        insert(CharacterRecipe)
        .values(character_id=character.id, recipe_code=recipe.code, source="scroll")
        .on_conflict_do_nothing(index_elements=["character_id", "recipe_code"])
    )
    await audit.record(
        db,
        actor_id=actor_id,
        action="recipe.learn",
        entity_type="character",
        entity_id=character.id,
        meta={"recipe": recipe.code},
    )
    return {"recipe": recipe.code}


async def recipes_view(
    db: AsyncSession, character: Character, locale: str, profession: str | None
) -> list[dict[str, Any]]:
    cfg = await config(db)
    stmt = select(Recipe).where(Recipe.status == "published", Recipe.deleted_at.is_(None))
    if profession:
        stmt = stmt.where(Recipe.profession_code == profession)
    recipes = list(
        (await db.execute(stmt.order_by(Recipe.profession_code, Recipe.required_level, Recipe.code))).scalars()
    )
    learned = await known_codes(db, character.id)
    progress = await professions.rows(db, character.id)
    codes = {r.output["template_code"] for r in recipes} | {i["template_code"] for r in recipes for i in r.ingredients}
    text = await resolve_text_map(db, [r.name_key for r in recipes] + [f"item.{c}.name" for c in codes], locale)
    out = []
    for r in recipes:
        level = progress[r.profession_code].level
        ingredients = [
            {
                **i,
                "name": text[f"item.{i['template_code']}.name"],
                "have": await count_in_bag(db, character.id, i["template_code"]),
            }
            for i in r.ingredients
        ]
        tool_ok = r.tool_kind is None or (await professions.tool_tier(db, character, r.tool_kind)) is not None
        known = is_known(r, learned)
        out.append(
            {
                "code": r.code,
                "name": text[r.name_key],
                "profession": r.profession_code,
                "required_level": r.required_level,
                "recipe_rarity": r.recipe_rarity,
                "unlock": r.unlock,
                "known": known,
                "ingredients": ingredients,
                "output": {**r.output, "name": text[f"item.{r.output['template_code']}.name"]},
                "tool_kind": r.tool_kind,
                "tool_ok": tool_ok,
                "workstation": r.workstation,
                "craft_time_s": r.craft_time_s,
                "xp": r.xp,
                "quality_applies": r.quality_applies,
                "fail_chance_pct": engine.fail_chance(cfg, r.fail_chance_pct, level, r.required_level),
                "max_craftable": min([i["have"] // i["qty"] for i in ingredients] + [cfg.max_batch])
                if ingredients
                else 0,
                "craftable": known and level >= r.required_level and tool_ok,
            }
        )
    return out


async def imbues_view(db: AsyncSession, locale: str) -> list[dict[str, Any]]:
    rows = list(
        (
            await db.execute(
                select(ImbueDefinition)
                .where(ImbueDefinition.status == "published", ImbueDefinition.deleted_at.is_(None))
                .order_by(ImbueDefinition.required_level, ImbueDefinition.code)
            )
        ).scalars()
    )
    text = await resolve_text_map(db, [r.name_key for r in rows], locale)
    return [
        {
            "code": r.code,
            "name": text[r.name_key],
            "required_level": r.required_level,
            "categories": r.categories,
            "slots": r.slots,
            "effects": r.effects,
            "gold_cost": r.gold_cost,
            "materials": r.materials,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- craft queue
async def start_craft(
    db: AsyncSession, *, character: Character, recipe_code: str, quantity: int, key: str, now: datetime | None = None
) -> CraftJob:
    existing = (
        await db.execute(select(CraftJob).where(CraftJob.character_id == character.id, CraftJob.start_key == key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    cfg = await config(db)
    if not 1 <= quantity <= cfg.max_batch:
        raise ValidationFailedError(f"Batch must be 1-{cfg.max_batch}", code="invalid_quantity")
    recipe = await _recipe(db, recipe_code)
    if not is_known(recipe, await known_codes(db, character.id)):
        raise ConflictError("Recipe not known", code="recipe_unknown")
    row = (await professions.rows(db, character.id))[recipe.profession_code]
    if row.level < recipe.required_level:
        raise ConflictError(
            f"Requires {recipe.profession_code} level {recipe.required_level}", code="profession_level_low"
        )
    if recipe.tool_kind and (await professions.tool_tier(db, character, recipe.tool_kind)) is None:
        raise ConflictError("Equip the required profession tool", code="tool_required")
    if recipe.workstation and recipe.workstation not in cfg.workstations:
        raise ConflictError("Workstation unavailable", code="workstation_required")
    active = (
        await db.execute(
            select(func.count())
            .select_from(CraftJob)
            .where(CraftJob.character_id == character.id, CraftJob.status == "running")
        )
    ).scalar_one()
    if active >= cfg.max_active_jobs:
        raise ConflictError("Craft queue is full", code="craft_queue_full")
    snapshot = await _revision(db, "recipe", recipe.code, recipe.revision_no)
    check = await professions.node_check(db, character, recipe.profession_code, 0)
    speed = check["stat_bonuses"]["speed"] + check["modifiers"]["speed"]
    quality_bonus = check["stat_bonuses"]["quality"] + check["modifiers"]["quality"]
    consumed: list[dict[str, Any]] = []
    for ing in recipe.ingredients:
        consumed += await consume(
            db, character, ing["template_code"], ing["qty"] * quantity, f"craft:{key}:{ing['template_code']}"
        )
    started = now or now_utc()
    duration = recipe.craft_time_s * quantity / (1 + speed / 100)
    job = CraftJob(
        character_id=character.id,
        recipe_code=recipe.code,
        recipe_revision_no=recipe.revision_no,
        recipe_snapshot={
            **snapshot,
            "profession_level": row.level,
            "quality_bonus_pct": quality_bonus,
            "speed_pct": speed,
        },
        quantity=quantity,
        status="running",
        started_at=started,
        ends_at=started + timedelta(seconds=duration),
        seed=secrets.randbits(62),
        consumed=consumed,
        start_key=key,
    )
    db.add(job)
    await db.flush()
    await audit.record(
        db, actor_id=character.user_id, action="craft.start", entity_type="craft_job", entity_id=job.id,
        meta={"recipe": recipe.code, "quantity": quantity},
    )  # fmt: skip

    return job


async def _job(db: AsyncSession, character_id: int, job_id: int) -> CraftJob:
    job = (
        await db.execute(
            select(CraftJob).where(CraftJob.id == job_id, CraftJob.character_id == character_id).with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("Craft job not found", code="craft_job_not_found")
    return job


async def cancel_craft(db: AsyncSession, *, character: Character, job_id: int) -> dict[str, Any]:
    job = await _job(db, character.id, job_id)
    if job.status != "running":
        raise ConflictError("Job is not running", code="craft_not_running")
    if now_utc() >= job.ends_at:
        raise ConflictError("Job already finished; claim it", code="craft_finished")
    refunds: dict[str, int] = {}
    for c in job.consumed:
        refunds[c["template_code"]] = refunds.get(c["template_code"], 0) + c["qty"]
    placed = []
    for code, qty in sorted(refunds.items()):
        placed += await inventory.add_item(
            db, character=character, template_code=code, quantity=qty, source_type="craft_refund",
            source_id=str(job.id), key=f"craft_refund:{job.id}:{code}",
        )  # fmt: skip
    job.status = "cancelled"
    await db.flush()
    return {"job_id": job.id, "refunded": placed}


async def claim_craft(db: AsyncSession, *, character: Character, job_id: int, key: str) -> dict[str, Any]:
    job = await _job(db, character.id, job_id)
    if job.status == "claimed":
        if job.claim_key == key and job.result is not None:
            return {**job.result, "replayed": True}
        raise ConflictError("Already claimed", code="craft_claimed")
    if job.status != "running":
        raise ConflictError("Job is not claimable", code="craft_not_running")
    if now_utc() < job.ends_at:
        raise ConflictError("Still crafting", code="craft_not_finished", details={"ends_at": job.ends_at.isoformat()})
    cfg = await config(db)
    prof_cfg = await professions.config(db)
    snap = job.recipe_snapshot
    res = engine.resolve_craft(
        cfg,
        prof_cfg,
        snap,
        quantity=job.quantity,
        seed=job.seed,
        profession_level=snap["profession_level"],
        quality_bonus_pct=snap["quality_bonus_pct"],
    )
    placed: list[dict[str, Any]] = []
    tpl = await items.published_template(db, res["output_template"])
    stackable = tpl.stack_size > 1
    for quality, count in res["outputs"].items():
        placed += await inventory.add_item(
            db,
            character=character,
            template_code=res["output_template"],
            quantity=count * res["output_per_success"],
            source_type="craft",
            source_id=str(job.id),
            key=f"craft:{job.id}:{quality}",
            seed=zlib.crc32(f"{job.seed}:{quality}".encode()),
            quality=None if stackable or not snap.get("quality_applies", True) else quality,
        )
    for r in res["returned"]:
        placed += await inventory.add_item(
            db, character=character, template_code=r["template_code"], quantity=r["qty"], source_type="craft_return",
            source_id=str(job.id), key=f"craft_return:{job.id}:{r['template_code']}",
        )  # fmt: skip
    xp = await professions.grant_xp(
        db, character=character, profession_code=snap["profession_code"], amount=res["xp"],
        idempotency_key=f"craft:{job.id}", source_type="craft",
    )  # fmt: skip
    result = {"job_id": job.id, "recipe": job.recipe_code, **res, "placed": placed, "profession_xp": xp}
    job.status, job.claim_key, job.result = "claimed", key, result
    await db.flush()
    await audit.record(
        db, actor_id=character.user_id, action="craft.claim", entity_type="craft_job", entity_id=job.id,
        meta={"successes": res["successes"], "failures": res["failures"], "outputs": res["outputs"]},
    )  # fmt: skip
    return {**result, "replayed": False}


async def jobs_view(db: AsyncSession, character: Character) -> list[dict[str, Any]]:
    rows = list(
        (
            await db.execute(
                select(CraftJob)
                .where(CraftJob.character_id == character.id, CraftJob.status == "running")
                .order_by(CraftJob.ends_at)
            )
        ).scalars()
    )
    now = now_utc()
    return [
        {
            "id": j.id,
            "recipe": j.recipe_code,
            "quantity": j.quantity,
            "started_at": j.started_at.isoformat(),
            "ends_at": j.ends_at.isoformat(),
            "remaining_s": max(0, round((j.ends_at - now).total_seconds())),
            "claimable": now >= j.ends_at,
        }
        for j in rows
    ]


# --------------------------------------------------------------------------- AFK gathering
async def validate_gathering_task(db: AsyncSession, character: Character, task: dict[str, Any]) -> dict[str, Any]:
    from app.models.world import Zone

    node_code = str(task.get("node_code", ""))
    zone = (await db.execute(select(Zone).where(Zone.code == task.get("zone_code")))).scalar_one_or_none()
    if zone is None or node_code not in {n["node_code"] for n in zone.profession_nodes}:
        raise ValidationFailedError("That node is not in this zone", code="invalid_gathering_node")
    node = (
        await db.execute(
            select(GatheringNode).where(GatheringNode.code == node_code, GatheringNode.status == "published")
        )
    ).scalar_one_or_none()
    if node is None:
        raise ValidationFailedError("Unknown gathering node", code="invalid_gathering_node")
    check = await professions.node_check(db, character, node.profession_code, node.tier)
    if not check["accessible"]:
        raise ConflictError(
            f"Requires {node.profession_code} level {check['required_level']}", code="profession_level_low"
        )
    cfg = await config(db)
    return {
        "kind": "gathering",
        "node_code": node.code,
        "profession_code": node.profession_code,
        "tier": node.tier,
        "entries": node.entries,
        "actions_per_hour": node.actions_per_hour or cfg.gathering.default_actions_per_hour,
        "speed_pct": check["stat_bonuses"]["speed"] + check["modifiers"]["speed"],
        "yield_pct": check["tool_yield_pct"] * (1 + check["modifiers"]["yield"] / 100),
        "rare_find_pct": check["modifiers"]["rare_find"],
        "tool_tier": check["tool_tier"],
        "profession_level": check["level"],
    }


async def resolve_gathering_task(
    db: AsyncSession, character: Character, snapshot: dict[str, Any], result: dict[str, Any], key: str
) -> dict[str, Any]:
    task = snapshot["profession_task"]
    cfg = await config(db)
    elapsed = float(result["elapsed_s"])
    segments = [
        (max(0.0, min(s["end_s"], elapsed) - s["start_s"]), s["percent"] / 100)
        for s in snapshot["segments"]
        if s["start_s"] < elapsed
    ]
    economy = 1.0
    for e in snapshot["player"]["effects"]:
        if e.get("effect_type") == "LOOT_MODIFIER" and e["params"]["scope"] == "material_yield":
            economy += float(e["params"]["percent"]) / 100
    cap = snapshot["afk"].get("loot_modifier_caps", {}).get("material_yield")
    if cap is not None:
        economy = min(economy, 1 + cap / 100)
    out = engine.resolve_gathering(
        cfg,
        entries=task["entries"],
        node_tier=task["tier"],
        actions_per_hour=task["actions_per_hour"],
        segments=segments,
        speed_pct=task["speed_pct"],
        yield_pct=task["yield_pct"] * economy,
        rare_find_pct=task["rare_find_pct"],
        seed=zlib.crc32(key.encode()),
    )
    placed: list[dict[str, Any]] = []
    for code, qty in out["materials"].items():
        placed += await inventory.add_item(
            db, character=character, template_code=code, quantity=qty, source_type="gathering", source_id=key,
            key=f"{key}:{code}",
        )  # fmt: skip
    xp = await professions.grant_xp(
        db, character=character, profession_code=task["profession_code"], amount=out["xp"],
        idempotency_key=key, source_type="gathering",
    )  # fmt: skip
    return {**out, "placed": placed, "profession_xp": xp, "node_code": task["node_code"]}


# --------------------------------------------------------------------------- enchanting
async def _enchant_prior(db: AsyncSession, character_id: int, key: str) -> EnchantEvent | None:
    return (
        await db.execute(
            select(EnchantEvent).where(EnchantEvent.character_id == character_id, EnchantEvent.idempotency_key == key)
        )
    ).scalar_one_or_none()


async def _enchant_level_ok(
    db: AsyncSession, character: Character, cfg: engine.CraftingConfig, tier: int, needed: int | None = None
) -> int:
    level = (await professions.rows(db, character.id))["enchanting"].level
    need = needed if needed is not None else max(1, tier * cfg.enchanting.level_per_tier)
    if level < need:
        raise ConflictError(f"Requires Enchanting level {need}", code="profession_level_low")
    return level


async def reroll_affix(
    db: AsyncSession, *, character: Character, instance_id: int, affix_index: int, key: str
) -> dict[str, Any]:
    """Safe reroll: re-rolls one affix value inside its tier band; never destroys or downgrades the item."""
    prior = await _enchant_prior(db, character.id, key)
    if prior is not None:
        return {"event_id": prior.id, "after": prior.after, "cost": prior.cost, "replayed": True}
    cfg = await config(db)
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    if inst.location != "inventory":
        raise ConflictError("Unequip the item first", code="item_equipped")
    data = await items.revision_data(db, inst.template_code, inst.template_revision_no)
    if not 0 <= affix_index < len(inst.affixes) or inst.affixes[affix_index].get("kind") == "fixed":
        raise ValidationFailedError("Invalid affix", code="invalid_affix")
    await _enchant_level_ok(db, character, cfg, data["tier"])
    affix = inst.affixes[affix_index]
    definition = (await db.execute(select(AffixDefinition).where(AffixDefinition.code == affix["code"]))).scalar_one()
    count = (
        await db.execute(
            select(func.count())
            .select_from(EnchantEvent)
            .where(EnchantEvent.instance_id == inst.id, EnchantEvent.action == "reroll")
        )
    ).scalar_one()
    seed = zlib.crc32(f"reroll:{inst.provenance_id}:{affix_index}:{count}".encode())
    value = engine.reroll_value(definition.rolls, data["tier"], seed)
    if value is None:
        raise ConflictError("No roll band for this tier", code="invalid_affix")
    ec = cfg.enchanting
    gold = ec.reroll_gold_base + ec.reroll_gold_per_tier * data["tier"]
    mat_qty = ec.reroll_material_qty_base + ec.reroll_material_qty_per_tier * data["tier"]
    await consume(db, character, ec.reroll_material, mat_qty, f"reroll:{key}")
    await wallet.change_gold(
        db, character_id=character.id, delta=-gold, reason="enchant_reroll", idempotency_key=f"reroll:{key}",
        ref_type="item_instance", ref_id=str(inst.id),
    )  # fmt: skip
    before = dict(affix)
    new_effect = {**affix["effect"], "params": {**affix["effect"]["params"], definition.effect["value_param"]: value}}
    affixes = list(inst.affixes)
    affixes[affix_index] = {**affix, "value": value, "effect": new_effect}
    inst.affixes = affixes
    cost = {"gold": gold, "materials": {ec.reroll_material: mat_qty}}
    ev = EnchantEvent(
        character_id=character.id, instance_id=inst.id, action="reroll", idempotency_key=key, seed=seed,
        before=before, after=affixes[affix_index], cost=cost,
    )  # fmt: skip
    db.add(ev)
    await db.flush()
    await professions.grant_xp(
        db, character=character, profession_code="enchanting", amount=ec.reroll_xp, idempotency_key=f"reroll:{key}",
        source_type="enchanting",
    )  # fmt: skip
    return {"event_id": ev.id, "after": ev.after, "cost": cost, "replayed": False}


async def imbue(
    db: AsyncSession, *, character: Character, instance_id: int, imbue_code: str, key: str
) -> dict[str, Any]:
    prior = await _enchant_prior(db, character.id, key)
    if prior is not None:
        return {"event_id": prior.id, "after": prior.after, "cost": prior.cost, "replayed": True}
    cfg = await config(db)
    definition = (
        await db.execute(
            select(ImbueDefinition).where(ImbueDefinition.code == imbue_code, ImbueDefinition.status == "published")
        )
    ).scalar_one_or_none()
    if definition is None:
        raise NotFoundError("Imbue not found", code="imbue_not_found")
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    if inst.location != "inventory":
        raise ConflictError("Unequip the item first", code="item_equipped")
    data = await items.revision_data(db, inst.template_code, inst.template_revision_no)
    if data["category"] not in definition.categories or (definition.slots and data["slot"] not in definition.slots):
        raise ValidationFailedError("This imbue does not fit the item", code="imbue_incompatible")
    await _enchant_level_ok(db, character, cfg, data["tier"], definition.required_level)
    for m in definition.materials:
        await consume(db, character, m["template_code"], m["qty"], f"imbue:{key}:{m['template_code']}")
    if definition.gold_cost:
        await wallet.change_gold(
            db, character_id=character.id, delta=-definition.gold_cost, reason="enchant_imbue",
            idempotency_key=f"imbue:{key}", ref_type="item_instance", ref_id=str(inst.id),
        )  # fmt: skip
    before = {"enchantments": inst.enchantments}
    inst.enchantments = [{"code": definition.code, "effects": definition.effects}]  # one imbue slot; replaces
    cost = {"gold": definition.gold_cost, "materials": {m["template_code"]: m["qty"] for m in definition.materials}}
    ev = EnchantEvent(
        character_id=character.id, instance_id=inst.id, action="imbue", idempotency_key=key, seed=0,
        before=before, after={"enchantments": inst.enchantments}, cost=cost,
    )  # fmt: skip
    db.add(ev)
    await db.flush()
    await professions.grant_xp(
        db, character=character, profession_code="enchanting", amount=cfg.enchanting.reroll_xp * 2,
        idempotency_key=f"imbue:{key}", source_type="enchanting",
    )  # fmt: skip
    return {"event_id": ev.id, "after": ev.after, "cost": cost, "replayed": False}


async def _salvage_template(
    db: AsyncSession, character: Character, template_code: str, qty: int, key: str
) -> list[dict[str, Any]]:
    cfg = await config(db)
    tpl = (await db.execute(select(ItemTemplate).where(ItemTemplate.code == template_code))).scalar_one()
    data = await items.revision_data(db, tpl.code, tpl.revision_no)
    mods = prof_rules.yield_modifiers(await professions.profession_effects(db, character), cfg.salvage.profession)
    placed: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    for i in range(qty):
        for code, n in engine.salvage_outputs(
            data["salvage"], zlib.crc32(f"{key}:{i}".encode()), 100 + mods["yield"]
        ).items():
            totals[code] = totals.get(code, 0) + n
    for code, n in sorted(totals.items()):
        placed += await inventory.add_item(
            db, character=character, template_code=code, quantity=n, source_type="salvage", source_id=template_code,
            key=f"{key}:{code}",
        )  # fmt: skip
    xp = round((cfg.salvage.xp_per_item_base + cfg.salvage.xp_per_item_per_tier * tpl.tier) * qty)
    await professions.grant_xp(
        db, character=character, profession_code=cfg.salvage.profession, amount=xp, idempotency_key=f"{key}:xp",
        source_type="salvage",
    )  # fmt: skip
    return placed or [{"template_code": template_code, "qty": qty, "placed": "salvaged", "outputs": {}}]


async def salvage(db: AsyncSession, *, character: Character, instance_id: int, key: str) -> dict[str, Any]:
    prior = await _enchant_prior(db, character.id, key)
    if prior is not None:
        return {"event_id": prior.id, "after": prior.after, "replayed": True}
    inst = await items.get_owned_instance(db, character.id, instance_id, for_update=True)
    if inst.location != "inventory":
        raise ConflictError("Only bag items can be salvaged", code="item_equipped")
    data = await items.revision_data(db, inst.template_code, inst.template_revision_no)
    if not data.get("salvage"):
        raise ValidationFailedError("This item cannot be salvaged", code="not_salvageable")
    qty = inst.quantity
    inst.location = "destroyed"
    await db.flush()
    placed = await _salvage_template(db, character, inst.template_code, qty, f"salvage:{key}")
    ev = EnchantEvent(
        character_id=character.id, instance_id=inst.id, action="salvage", idempotency_key=key,
        seed=zlib.crc32(key.encode()), before={"template": inst.template_code, "qty": qty},
        after={"placed": placed}, cost={},
    )  # fmt: skip
    db.add(ev)
    await db.flush()
    return {"event_id": ev.id, "after": ev.after, "replayed": False}


afk.PROFESSION_TASK_VALIDATORS.append(validate_gathering_task)
afk.PROFESSION_TASK_RESOLVERS.append(resolve_gathering_task)
inventory.SALVAGE_HANDLERS.append(_salvage_template)
