"""Class system services: creation options, promotion (Lv100), specialization (Lv300), milestone unlocks
(Awakening Lv600, Capstone Lv850, Mastery Lv1000), path changes, class titles and stat contributions.
All class identity comes from content data; there is no class-name branching."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.game_engine.progression import XpResult
from app.game_engine.stat_calculator import Contribution, contribution_from_effects
from app.localization.service import resolve_text_map
from app.models.character import Character
from app.models.classes import (
    BaseClass,
    CharacterClassProgression,
    ClassBranch,
    ClassProgressionRequirement,
    Specialization,
)
from app.services import audit, character_options, characters, progression, wallet
from app.services.content.types.balance import get_published_balance
from app.services.content.types.classes import ClassPathConfig
from app.services.races import stat_label_keys

STAGES = ("promotion", "specialization", "awakening", "capstone", "mastery")
MILESTONE_FIELDS = {"awakening": "awakened_at", "capstone": "capstone_unlocked_at", "mastery": "mastery_at"}


def _now() -> datetime:
    return datetime.now(UTC)


async def published_classes(db: AsyncSession) -> list[BaseClass]:
    return list(
        (
            await db.execute(
                select(BaseClass)
                .where(BaseClass.status == "published", BaseClass.deleted_at.is_(None))
                .order_by(BaseClass.sort_order)
            )
        ).scalars()
    )


async def class_tree(db: AsyncSession) -> dict[str, Any]:
    """All published classes → branches → specializations (codes), for validation and UI trees."""
    classes = await published_classes(db)
    branches = list(
        (
            await db.execute(
                select(ClassBranch).where(ClassBranch.status == "published").order_by(ClassBranch.sort_order)
            )
        ).scalars()
    )
    specs = list(
        (
            await db.execute(
                select(Specialization).where(Specialization.status == "published").order_by(Specialization.sort_order)
            )
        ).scalars()
    )
    return {"classes": classes, "branches": branches, "specs": specs}


async def requirements(db: AsyncSession, base_class_code: str) -> dict[str, dict[str, Any]]:
    rows = list(
        (
            await db.execute(
                select(ClassProgressionRequirement).where(
                    (ClassProgressionRequirement.base_class_code.is_(None))
                    | (ClassProgressionRequirement.base_class_code == base_class_code)
                )
            )
        ).scalars()
    )
    out: dict[str, dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: r.base_class_code is not None):  # class override wins
        out[r.stage] = {"min_level": r.min_level, "required_quest_code": r.required_quest_code}
    missing = set(STAGES) - set(out)
    if missing:
        raise NotFoundError(f"class progression requirements missing for {sorted(missing)}")
    return out


def _effect_labels(effect_lists: list[list[dict[str, Any]]]) -> set[str]:
    keys: set[str] = set()
    for effects in effect_lists:
        keys |= stat_label_keys(effects)
    return keys


async def class_cards(db: AsyncSession, locale: str) -> list[dict[str, Any]]:
    tree = await class_tree(db)
    keys: set[str] = set()
    for c in tree["classes"]:
        keys |= {
            c.name_key,
            c.description_key or "",
            c.role_key,
            f"passive.{c.base_passive_code}.name",
            f"passive.{c.base_passive_code}.description",
            f"class_category.{c.category}.name",
        }
        keys |= {f"resource.{r}.name" for r in c.resources} | {f"weapon_family.{w}.name" for w in c.weapon_families}
        keys |= {f"armor_family.{a}.name" for a in c.armor_families}
        keys |= {f"stat.{s.lower()}.name" for s in (c.primary_stat, c.secondary_stat, c.utility_stat)}
        keys |= _effect_labels([c.base_effects])
    for b in tree["branches"]:
        keys |= {b.name_key, b.role_key}
    for s in tree["specs"]:
        keys |= {s.name_key, s.role_key}
    text = await resolve_text_map(db, sorted(k for k in keys if k), locale)
    cards = []
    for c in tree["classes"]:
        branches = [b for b in tree["branches"] if b.base_class_code == c.code]
        cards.append(
            {
                "id": c.id,
                "code": c.code,
                "name": text[c.name_key],
                "description": text.get(c.description_key or ""),
                "role": text[c.role_key],
                "category": c.category,
                "category_name": text[f"class_category.{c.category}.name"],
                "stat_weights": {"primary": c.primary_stat, "secondary": c.secondary_stat, "utility": c.utility_stat},
                "resources": [text[f"resource.{r}.name"] for r in c.resources],
                "weapons": [text[f"weapon_family.{w}.name"] for w in c.weapon_families],
                "armor": [text[f"armor_family.{a}.name"] for a in c.armor_families],
                "trait_name": text[f"passive.{c.base_passive_code}.name"],
                "trait_description": text[f"passive.{c.base_passive_code}.description"],
                "effects": [e for e in c.base_effects if e["effect_type"] != "STAT_FLAT"],
                "solo_accord": c.solo_accord,
                "branches": [
                    {
                        "code": b.code,
                        "name": text[b.name_key],
                        "role": text[b.role_key],
                        "specializations": [
                            {"code": s.code, "name": text[s.name_key], "role": text[s.role_key]}
                            for s in tree["specs"]
                            if s.branch_code == b.code
                        ],
                    }
                    for b in branches
                ],
                "labels": {k: text[k] for k in _effect_labels([c.base_effects]) if k in text},
            }
        )
    return cards


async def get_progression_row(
    db: AsyncSession, character: Character, *, for_update: bool = False
) -> CharacterClassProgression:
    stmt = select(CharacterClassProgression).where(CharacterClassProgression.character_id == character.id)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        base = await db.get(BaseClass, character.base_class_id)
        if base is None:
            raise NotFoundError("Base class not found")
        row = CharacterClassProgression(character_id=character.id, base_class_code=base.code)
        db.add(row)
        await db.flush()
        await sync_milestones(db, character, row)
    return row


async def init_progression(db: AsyncSession, character: Character) -> None:
    await get_progression_row(db, character)


async def sync_milestones(
    db: AsyncSession, character: Character, row: CharacterClassProgression | None = None
) -> list[str]:
    row = row or await get_progression_row(db, character, for_update=True)
    req = await requirements(db, row.base_class_code)
    unlocked = []
    for stage, field in MILESTONE_FIELDS.items():
        if (
            getattr(row, field) is None
            and character.level >= req[stage]["min_level"]
            and (stage != "awakening" or row.specialization_code is not None)
        ):
            setattr(row, field, _now())
            unlocked.append(stage)
    return unlocked


async def _on_level(db: AsyncSession, character: Character, _res: XpResult) -> None:
    await sync_milestones(db, character)


async def _check_gate(db: AsyncSession, character: Character, req: dict[str, Any], stage: str) -> None:
    need = req[stage]
    if character.level < need["min_level"]:
        raise ValidationFailedError(
            f"Requires level {need['min_level']}",
            code="level_too_low",
            details={"required_level": need["min_level"], "level": character.level},
        )
    # Quest-gated promotions (class data `required_quest_code` or the goals config) are enforced by the quest
    # system through this hook; with no requirement, level alone is sufficient.
    for check in QUEST_GATE_CHECKS:
        await check(db, character, stage, need["required_quest_code"])


QUEST_GATE_CHECKS: list[Any] = []  # async (db, character, stage, required_quest_code | None) -> None


async def promote(
    db: AsyncSession, *, character: Character, branch_code: str, actor_id: int
) -> CharacterClassProgression:
    row = await get_progression_row(db, character, for_update=True)
    if row.branch_code is not None:
        raise ConflictError("Already promoted", code="already_promoted")
    await _check_gate(db, character, await requirements(db, row.base_class_code), "promotion")
    branch = (
        await db.execute(select(ClassBranch).where(ClassBranch.code == branch_code, ClassBranch.status == "published"))
    ).scalar_one_or_none()
    if branch is None or branch.base_class_code != row.base_class_code:
        raise ValidationFailedError("Branch does not belong to your class", code="invalid_branch")
    row.branch_code, row.promoted_at = branch.code, _now()
    await audit.record(
        db,
        actor_id=actor_id,
        action="class.promote",
        entity_type="character",
        entity_id=character.id,
        after={"branch": branch.code},
    )
    await db.flush()
    return row


async def specialize(
    db: AsyncSession, *, character: Character, spec_code: str, actor_id: int
) -> CharacterClassProgression:
    row = await get_progression_row(db, character, for_update=True)
    if row.specialization_code is not None:
        raise ConflictError("Already specialized", code="already_specialized")
    if row.branch_code is None:
        raise ValidationFailedError("Choose a Lv100 path first", code="promotion_required")
    await _check_gate(db, character, await requirements(db, row.base_class_code), "specialization")
    spec = (
        await db.execute(
            select(Specialization).where(Specialization.code == spec_code, Specialization.status == "published")
        )
    ).scalar_one_or_none()
    if spec is None or spec.branch_code != row.branch_code:
        raise ValidationFailedError("Specialization is not under your path", code="invalid_specialization")
    row.specialization_code, row.specialized_at = spec.code, _now()
    await sync_milestones(db, character, row)
    await audit.record(
        db,
        actor_id=actor_id,
        action="class.specialize",
        entity_type="character",
        entity_id=character.id,
        after={"specialization": spec.code},
    )
    await db.flush()
    return row


async def path_change_quote(db: AsyncSession, character: Character) -> dict[str, Any]:
    cfg = await get_published_balance(db, "class_path", ClassPathConfig)
    row = await get_progression_row(db, character)
    free = cfg.first_change_free and row.path_changes == 0
    ready_at = (row.last_path_change_at + timedelta(hours=cfg.cooldown_hours)) if row.last_path_change_at else None
    return {
        "branch_change_gold": 0 if free else cfg.branch_change_gold_per_level * character.level,
        "spec_change_gold": 0 if free else cfg.spec_change_gold_per_level * character.level,
        "free": free,
        "cooldown_ready_at": ready_at,
        "path_changes": row.path_changes,
    }


async def change_path(
    db: AsyncSession,
    *,
    character: Character,
    branch_code: str | None,
    spec_code: str | None,
    idempotency_key: str,
    actor_id: int,
) -> CharacterClassProgression:
    """Re-choose branch (resets spec) or only spec. Charged via the wallet ledger; cooldown enforced."""
    row = await get_progression_row(db, character, for_update=True)
    quote = await path_change_quote(db, character)
    if quote["cooldown_ready_at"] and quote["cooldown_ready_at"] > _now():
        raise ConflictError(
            "Path change on cooldown",
            code="path_change_cooldown",
            details={"ready_at": quote["cooldown_ready_at"].isoformat()},
        )
    before = {"branch": row.branch_code, "specialization": row.specialization_code}
    if branch_code and branch_code != row.branch_code:
        if row.branch_code is None:
            raise ValidationFailedError("Use promotion for the first choice", code="promotion_required")
        cost = quote["branch_change_gold"]
        row.branch_code, row.specialization_code, row.specialized_at, row.awakened_at = None, None, None, None
        await promote_inner(db, character, row, branch_code)
    elif spec_code and spec_code != row.specialization_code:
        if row.specialization_code is None:
            raise ValidationFailedError("Use specialization for the first choice", code="promotion_required")
        cost = quote["spec_change_gold"]
        row.specialization_code = None
    else:
        raise ValidationFailedError("Nothing to change", code="no_change")
    if cost:
        await wallet.change_gold(
            db,
            character_id=character.id,
            delta=-cost,
            reason="class_path_change",
            idempotency_key=f"path:{idempotency_key}",
            ref_type="character",
            ref_id=str(character.id),
        )
    if spec_code:
        spec = (await db.execute(select(Specialization).where(Specialization.code == spec_code))).scalar_one_or_none()
        if spec is None or spec.branch_code != row.branch_code:
            raise ValidationFailedError("Specialization is not under your path", code="invalid_specialization")
        row.specialization_code, row.specialized_at = spec.code, _now()
    row.path_changes += 1
    row.last_path_change_at = _now()
    await sync_milestones(db, character, row)
    await audit.record(
        db,
        actor_id=actor_id,
        action="class.path_change",
        entity_type="character",
        entity_id=character.id,
        before=before,
        after={"branch": row.branch_code, "specialization": row.specialization_code},
        meta={"gold": cost},
    )
    await db.flush()
    return row


async def promote_inner(
    db: AsyncSession, character: Character, row: CharacterClassProgression, branch_code: str
) -> None:
    branch = (
        await db.execute(select(ClassBranch).where(ClassBranch.code == branch_code, ClassBranch.status == "published"))
    ).scalar_one_or_none()
    if branch is None or branch.base_class_code != row.base_class_code:
        raise ValidationFailedError("Branch does not belong to your class", code="invalid_branch")
    row.branch_code, row.promoted_at = branch.code, _now()


async def class_contributions(db: AsyncSession, character: Character) -> list[Contribution]:
    row = await get_progression_row(db, character)
    base = await db.get(BaseClass, character.base_class_id)
    out: list[Contribution] = []
    if base:
        out.append(contribution_from_effects("class", base.code, base.base_effects))
    if row.branch_code:
        b = (await db.execute(select(ClassBranch).where(ClassBranch.code == row.branch_code))).scalar_one()
        out.append(contribution_from_effects("class", b.code, b.effects))
    if row.specialization_code:
        s = (
            await db.execute(select(Specialization).where(Specialization.code == row.specialization_code))
        ).scalar_one()
        out.append(contribution_from_effects("class", s.code, s.effects))
    return out


async def stat_tokens(db: AsyncSession, character: Character) -> dict[str, str]:
    base = await db.get(BaseClass, character.base_class_id)
    if base is None:
        return {}
    return {
        "main": base.primary_stat,
        "secondary": base.secondary_stat,
        "utility": base.utility_stat,
        "main_damage": base.main_damage_stat,
    }


async def class_title_parts(
    db: AsyncSession, character: Character, row: CharacterClassProgression
) -> tuple[str, str | None]:
    """(name_key, pattern_key) following Base → Branch → Spec → Awakened → Ascendant → Eternal <noun>."""
    if row.specialization_code:
        spec_key = f"spec.{row.specialization_code}.name"
        if row.mastery_at:
            return f"spec.{row.specialization_code}.mastery_noun", "class_title.pattern.eternal.name"
        if row.capstone_unlocked_at:
            return spec_key, "class_title.pattern.ascendant.name"
        if row.awakened_at:
            return spec_key, "class_title.pattern.awakened.name"
        return spec_key, None
    if row.branch_code:
        return f"branch.{row.branch_code}.name", None
    return f"class.{row.base_class_code}.name", None


async def class_view(db: AsyncSession, character: Character, locale: str) -> dict[str, Any]:
    row = await get_progression_row(db, character)
    req = await requirements(db, row.base_class_code)
    cards = {c["code"]: c for c in await class_cards(db, locale)}
    card = cards.get(row.base_class_code)
    name_key, pattern_key = await class_title_parts(db, character, row)
    keys = [name_key, *(k for k in [pattern_key] if k), *(f"class_stage.{s}.name" for s in STAGES)]
    text = await resolve_text_map(db, keys, locale)
    title = text[pattern_key].replace("{name}", text[name_key]) if pattern_key else text[name_key]
    done_at = {
        "promotion": row.promoted_at,
        "specialization": row.specialized_at,
        "awakening": row.awakened_at,
        "capstone": row.capstone_unlocked_at,
        "mastery": row.mastery_at,
    }
    return {
        "character_id": character.id,
        "level": character.level,
        "base_class": card,
        "class_title": title,
        "branch_code": row.branch_code,
        "specialization_code": row.specialization_code,
        "stages": [
            {
                "stage": s,
                "name": text[f"class_stage.{s}.name"],
                "min_level": req[s]["min_level"],
                "requires_quest": req[s]["required_quest_code"],
                "completed_at": done_at[s],
                "unlocked": character.level >= req[s]["min_level"],
            }
            for s in STAGES
        ],
        "can_promote": row.branch_code is None and character.level >= req["promotion"]["min_level"],
        "can_specialize": row.branch_code is not None
        and row.specialization_code is None
        and character.level >= req["specialization"]["min_level"],
        "path_change": await path_change_quote(db, character),
        "version": row.version,
    }


async def _class_option_provider(db: AsyncSession, locale: str) -> list[dict[str, Any]]:
    return await class_cards(db, locale)


character_options.CLASS_OPTION_PROVIDERS.append(_class_option_provider)
progression.CONTRIBUTION_PROVIDERS.append(class_contributions)
progression.STAT_TOKEN_PROVIDERS.append(stat_tokens)
progression.POST_LEVEL_HOOKS.append(_on_level)
characters.POST_CREATE_HOOKS.append(init_progression)
