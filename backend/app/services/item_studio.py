"""Admin Item Studio service: server-side filtered listing, inspector (working data + translations +
validation + reverse references), clone, test-character preview, safe bulk edit, bulk translation status,
CSV/JSON export/import with dry-run, and the Item Generator Wizard (dry-run → validated atomic draft batch)."""

import csv
import io
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.names import name_key as normalize_name
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.game_engine import item_generator as gen
from app.game_engine import items as item_rules_engine
from app.game_engine.stat_calculator import compute_stat_sheet, contribution_from_effects
from app.localization import service as l10n
from app.localization.locales import SUPPORTED_LOCALES
from app.models.character import Character
from app.models.classes import BaseClass, WeaponFamily
from app.models.content import ContentDraft
from app.models.items import ItemTemplate
from app.models.localization import LocalizationKey, LocalizationValue
from app.models.race import Race
from app.models.world import BossTemplate, DropTable, Zone
from app.services import audit, items, progression
from app.services.content import service as content
from app.services.content.types.balance import get_published_balance
from app.services.content.types.items import ITEM_TEMPLATE_TYPE, item_rules

CT = ITEM_TEMPLATE_TYPE
TEXT_FIELDS = ("name", "description", "short_description", "lore")
SORTS = {
    "code": ItemTemplate.code,
    "tier": ItemTemplate.tier,
    "min_level": ItemTemplate.min_level,
    "rarity": ItemTemplate.rarity,
    "category": ItemTemplate.category,
    "updated_at": ItemTemplate.updated_at,
    "status": ItemTemplate.status,
}
SAFE_BULK_FIELDS = (
    "vendor_value",
    "tradeable",
    "sellable",
    "bind_policy",
    "class_tags",
    "icon",
    "sources",
    "durability",
)
MAX_LIST = 200
MAX_IMPORT = 2000


def text_key(code: str, field: str) -> str:
    return f"item.{code}.{field}"


async def studio_config(db: AsyncSession) -> gen.ItemStudioConfig:
    return await get_published_balance(db, "item_studio", gen.ItemStudioConfig)


# --------------------------------------------------------------------------- listing
class ListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=100)
    category: str | None = None
    tier: int | None = Field(default=None, ge=0, le=10)
    rarity: str | None = None
    slot: str | None = None
    family: str | None = None
    class_tag: str | None = None
    status: str | None = None
    translation: Literal["complete", "incomplete"] | None = None
    missing_locale: str | None = None
    sort: str = "code"
    order: Literal["asc", "desc"] = "asc"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=MAX_LIST)


def _name_value_exists(locale: str | None = None) -> Any:
    conds = [
        LocalizationKey.key == func.concat("item.", ItemTemplate.code, ".name"),
        LocalizationValue.key_id == LocalizationKey.id,
        LocalizationValue.value != "",
    ]
    if locale:
        conds.append(LocalizationValue.locale == locale)
    return exists().where(and_(*conds))


def _complete_expr() -> Any:
    return and_(*(_name_value_exists(loc) for loc in SUPPORTED_LOCALES))


async def list_items(db: AsyncSession, f: ListFilters) -> dict[str, Any]:
    conds: list[Any] = [ItemTemplate.deleted_at.is_(None)]
    if f.q:
        like = f"%{f.q.lower()}%"
        name_match = exists().where(
            and_(
                LocalizationKey.key == func.concat("item.", ItemTemplate.code, ".name"),
                LocalizationValue.key_id == LocalizationKey.id,
                func.lower(LocalizationValue.value).like(like),
            )
        )
        conds.append(or_(ItemTemplate.code.ilike(like), name_match))
    for field in ("category", "rarity", "slot", "status"):
        if getattr(f, field):
            conds.append(getattr(ItemTemplate, field) == getattr(f, field))
    if f.tier is not None:
        conds.append(ItemTemplate.tier == f.tier)
    if f.family:
        conds.append(
            or_(
                ItemTemplate.family == f.family,
                ItemTemplate.weapon_family == f.family,
                ItemTemplate.armor_family == f.family,
            )
        )
    if f.class_tag:
        conds.append(ItemTemplate.class_tags.contains([f.class_tag]))
    if f.translation == "complete":
        conds.append(_complete_expr())
    elif f.translation == "incomplete":
        conds.append(~_complete_expr())
    if f.missing_locale:
        conds.append(~_name_value_exists(f.missing_locale))
    col = SORTS.get(f.sort)
    if col is None:
        raise ValidationFailedError("Unknown sort field", code="invalid_sort")
    order = col.desc() if f.order == "desc" else col.asc()
    total = (await db.execute(select(func.count()).select_from(ItemTemplate).where(*conds))).scalar_one()
    rows = list(
        (
            await db.execute(
                select(ItemTemplate).where(*conds).order_by(order, ItemTemplate.id).offset(f.offset).limit(f.limit)
            )
        ).scalars()
    )
    keys = [text_key(r.code, "name") for r in rows]
    values = await l10n.get_all_locales(db, keys)
    pending = set(
        (
            await db.execute(
                select(ContentDraft.entity_id).where(
                    ContentDraft.entity_type == CT.entity_type, ContentDraft.entity_id.in_([r.id for r in rows])
                )
            )
        ).scalars()
    )
    return {
        "items": [
            {
                "code": r.code,
                "name": values[text_key(r.code, "name")]["en"]["value"] or r.code,
                "category": r.category,
                "slot": r.slot,
                "family": r.weapon_family or r.armor_family or r.family,
                "tier": r.tier,
                "min_level": r.min_level,
                "rarity": r.rarity,
                "status": r.status,
                "revision_no": r.revision_no,
                "has_pending_changes": r.id in pending or r.revision_no == 0,
                "class_tags": r.class_tags,
                "translations": {loc: v["status"] for loc, v in values[text_key(r.code, "name")].items()},
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "offset": f.offset,
        "limit": f.limit,
    }


# --------------------------------------------------------------------------- inspector / references
async def references(db: AsyncSession, code: str) -> dict[str, list[dict[str, Any]]]:
    """Reverse references: drop tables (by ref or matching item pool), zones/bosses using those tables,
    other items salvaging into this one."""
    row = (await db.execute(select(ItemTemplate).where(ItemTemplate.code == code))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Item not found", code="item_not_found")
    tables = []
    for t in (await db.execute(select(DropTable).where(DropTable.deleted_at.is_(None)))).scalars():
        for e in t.entries:
            direct = e.get("ref") == code
            pool = (
                e["kind"] == "item_pool"
                and e.get("tier") == row.tier
                and e.get("rarity") in (None, row.rarity)
                and (e.get("category") in (None, row.category))
            )
            if direct or pool:
                tables.append(
                    {"code": t.code, "match": "direct" if direct else "pool", "chance_pct": e.get("chance_pct", 100)}
                )
                break
    table_codes = [t["code"] for t in tables]
    zones = [
        {"code": z.code, "via": z.drop_table_code}
        for z in (await db.execute(select(Zone).where(Zone.drop_table_code.in_(table_codes)))).scalars()
    ]
    bosses = [
        {"code": b.code, "via": b.drop_table_code}
        for b in (await db.execute(select(BossTemplate).where(BossTemplate.drop_table_code.in_(table_codes)))).scalars()
    ]
    salvaged_from = [
        {"code": c}
        for c in (
            await db.execute(select(ItemTemplate.code).where(ItemTemplate.salvage.contains([{"template_code": code}])))
        ).scalars()
    ]
    return {"drop_tables": tables, "zones": zones, "bosses": bosses, "salvaged_from": salvaged_from, "recipes": []}


async def inspector(db: AsyncSession, code: str) -> dict[str, Any]:
    row = await content.get_row(db, CT, code)
    view = await content.working_view(db, CT, row)
    keys = [text_key(code, f) for f in TEXT_FIELDS]
    texts = await l10n.get_all_locales(db, keys)
    issues = await content.validate(db, CT, code, view["data"])
    rules = await item_rules(db)
    reqs = view["data"].get("requirements", {}).get("stats", {})
    budget = item_rules_engine.distributable_budget(rules, view["data"]["min_level"])
    return {
        **view,
        "texts": {f: texts[text_key(code, f)] for f in TEXT_FIELDS},
        "issues": [i.as_dict() for i in issues],
        "requirement_budget": {
            "budget": budget,
            "required": sum(reqs.values()),
            "percent": round(100 * sum(reqs.values()) / budget, 1) if budget else 0,
            "warn_pct": rules.requirement_warn_pct,
            "error_pct": rules.requirement_error_pct,
        },
        "rarity_budget": rules.rarity_budgets[view["data"]["rarity"]].model_dump(),
        "tier_gate": rules.gate(view["data"]["tier"]).model_dump(),
        "references": await references(db, code),
    }


# --------------------------------------------------------------------------- clone / texts
async def seed_texts(db: AsyncSession, code: str, texts: dict[str, dict[str, str]], *, actor_id: int | None) -> None:
    for field, per_locale in texts.items():
        if field not in TEXT_FIELDS:
            continue
        key = text_key(code, field)
        await l10n.ensure_key(db, key, "item")
        current = (await l10n.get_all_locales(db, [key]))[key]
        for loc, value in per_locale.items():
            if loc not in SUPPORTED_LOCALES or not value:
                continue
            await l10n.set_value(
                db,
                key=key,
                locale=loc,
                value=value,
                status="draft",
                expected_version=current[loc]["version"] or None,
                actor_id=actor_id,
            )


async def set_text(
    db: AsyncSession,
    code: str,
    field: str,
    locale: str,
    value: str,
    status: str,
    expected_version: int | None,
    *,
    actor_id: int,
    can_review: bool,
) -> dict[str, Any]:
    """Edit one localized item text (creates the key on first use) with optimistic concurrency."""
    if status in ("reviewed", "published") and not can_review:
        raise PermissionDeniedError("Reviewing translations requires localization.review")
    await content.get_row(db, CT, code)
    key = text_key(code, field)
    await l10n.ensure_key(db, key, "item")
    before = (await l10n.get_all_locales(db, [key]))[key][locale]
    row = await l10n.set_value(
        db, key=key, locale=locale, value=value, status=status, expected_version=expected_version, actor_id=actor_id
    )
    after = {"value": row.value, "status": row.status, "version": row.version}
    await audit.record(
        db, actor_id=actor_id, action="localization.update", entity_type="localization",
        entity_id=f"{key}:{locale}", before=before, after=after,
    )  # fmt: skip
    return {"key": key, "locale": locale, **after}


async def clone(db: AsyncSession, code: str, new_code: str, *, actor_id: int) -> dict[str, Any]:
    src = await content.get_row(db, CT, code)
    data = (await content.working_view(db, CT, src))["data"]
    row = await content.create(db, CT, code=new_code, data=data, actor_id=actor_id)
    texts = await l10n.get_all_locales(db, [text_key(code, f) for f in TEXT_FIELDS])
    await seed_texts(
        db,
        new_code,
        {f: {loc: v["value"] for loc, v in texts[text_key(code, f)].items() if v["value"]} for f in TEXT_FIELDS},
        actor_id=actor_id,
    )
    await audit.record(
        db, actor_id=actor_id, action="item.clone", entity_type="item_template", entity_id=new_code, meta={"from": code}
    )
    return await content.working_view(db, CT, row)


# --------------------------------------------------------------------------- preview on test characters
async def preview(db: AsyncSession, code: str, profile_code: str, *, actor_id: int, seed: int = 1) -> dict[str, Any]:
    cfg = await studio_config(db)
    profile = next((p for p in cfg.preview_profiles if p.code == profile_code), None)
    if profile is None:
        raise ValidationFailedError("Unknown preview profile", code="invalid_preview_profile")
    row = await content.get_row(db, CT, code)
    data = (await content.working_view(db, CT, row))["data"]
    rolled = await items.roll(db, data, seed)
    rules = await item_rules(db)
    effects = item_rules_engine.instance_effects(data, {"affixes": rolled["affixes"]}, rules)
    base = (await db.execute(select(BaseClass).where(BaseClass.code == profile.class_))).scalar_one()
    race = (await db.execute(select(Race).where(Race.code == profile.race))).scalar_one()
    prog_cfg = await progression.load_config(db)
    savepoint = await db.begin_nested()
    try:
        name = "Pv" + uuid.uuid4().hex[:10]
        ch = Character(
            user_id=actor_id,
            name=name,
            name_normalized=normalize_name(name),
            race_id=race.id,
            base_class_id=base.id,
            level=profile.level,
            xp=0,
            unspent_stat_points=(profile.level - 1) * prog_cfg.stat_points_per_level,
        )
        db.add(ch)
        await db.flush()
        plan = await progression.template_points(db, ch, profile.stat_profile, ch.unspent_stat_points)
        await progression.allocate(
            db,
            character=ch,
            points=plan,
            expected_version=ch.version,
            idempotency_key=uuid.uuid4().hex,
            mode="template",
        )
        contributions = await progression.contributions(db, ch)
        before = compute_stat_sheet(prog_cfg, ch.level, contributions).finals()
        after = compute_stat_sheet(
            prog_cfg, ch.level, [*contributions, contribution_from_effects("equipment", code, effects)]
        ).finals()
        unmet = item_rules_engine.requirement_check(
            data,
            level=ch.level,
            stats={k: v for k, v in before.items() if k.isupper()},
            class_code=base.code,
            race_code=race.code,
        )
    finally:
        await savepoint.rollback()
    deltas = {k: round(after[k] - before.get(k, 0), 3) for k in after if abs(after[k] - before.get(k, 0)) > 1e-9}
    return {
        "profile": profile.model_dump(by_alias=True),
        "requirements_met": not unmet,
        "unmet": unmet,
        "rolled_affixes": rolled["affixes"],
        "deltas": dict(sorted(deltas.items())),
        "before": {k: round(v, 3) for k, v in sorted(before.items()) if k in deltas},
    }


# --------------------------------------------------------------------------- bulk operations
async def bulk_edit(
    db: AsyncSession, codes: list[str], patch: dict[str, Any], expected: dict[str, int], *, actor_id: int
) -> list[dict[str, Any]]:
    """Safe-field bulk edit; all-or-nothing, optimistic version per item."""
    bad = [k for k in patch if k not in SAFE_BULK_FIELDS]
    if bad:
        raise ValidationFailedError(f"Fields not allowed in bulk edit: {bad}", code="unsafe_bulk_field")
    out = []
    for code in codes:
        row = await content.get_row(db, CT, code)
        data = (await content.working_view(db, CT, row))["data"]
        if code not in expected:
            raise ValidationFailedError(f"Missing expected version for {code}", code="version_required")
        view = await content.update(
            db, CT, code=code, data={**data, **patch}, expected_version=expected[code], actor_id=actor_id
        )
        out.append({"code": code, "edit_version": view["edit_version"]})
    await audit.record(
        db,
        actor_id=actor_id,
        action="item.bulk_edit",
        entity_type="item_template",
        meta={"codes": codes, "patch": patch},
    )
    return out


async def bulk_translation_status(
    db: AsyncSession, codes: list[str], locale: str, status: str, *, actor_id: int, can_review: bool
) -> int:
    if status in ("reviewed", "published") and not can_review:
        raise PermissionDeniedError("Reviewing translations requires localization.review")
    keys = [text_key(c, f) for c in codes for f in TEXT_FIELDS]
    values = await l10n.get_all_locales(db, keys)
    changed = 0
    for key, per in values.items():
        v = per[locale]
        if not v["value"] or v["status"] == status:
            continue
        await l10n.set_value(
            db,
            key=key,
            locale=locale,
            value=v["value"],
            status=status,
            expected_version=v["version"],
            actor_id=actor_id,
        )
        changed += 1
    await audit.record(
        db,
        actor_id=actor_id,
        action="item.bulk_translation_status",
        entity_type="item_template",
        meta={"codes": codes, "locale": locale, "status": status, "changed": changed},
    )
    return changed


# --------------------------------------------------------------------------- export / import
EXPORT_SIMPLE = (
    "category", "subcategory", "family", "slot", "weapon_family", "armor_family", "tier", "min_level", "rarity",
    "stack_size", "bind_policy", "tradeable", "sellable", "vendor_value", "requirement_profile", "set_code", "icon",
)  # fmt: skip


async def export_rows(db: AsyncSession, f: ListFilters) -> list[dict[str, Any]]:
    f = f.model_copy(update={"offset": 0, "limit": MAX_LIST})
    rows: list[dict[str, Any]] = []
    while True:
        page = await list_items(db, f)
        for item in page["items"]:
            row = await content.get_row(db, CT, item["code"])
            view = await content.working_view(db, CT, row)
            texts = await l10n.get_all_locales(db, [text_key(item["code"], x) for x in TEXT_FIELDS])
            rows.append(
                {
                    "code": item["code"],
                    "status": view["status"],
                    "edit_version": view["edit_version"],
                    "data": view["data"],
                    "l10n": {
                        x: {loc: v["value"] for loc, v in texts[text_key(item["code"], x)].items() if v["value"]}
                        for x in TEXT_FIELDS
                    },
                }
            )
        if len(page["items"]) < f.limit:
            return rows
        f = f.model_copy(update={"offset": f.offset + f.limit})


def to_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    complex_fields = [k for k in (rows[0]["data"] if rows else {}) if k not in EXPORT_SIMPLE]
    header = ["code", "edit_version", *EXPORT_SIMPLE, *complex_fields]
    header += [f"{x}_{loc}" for x in ("name", "description") for loc in SUPPORTED_LOCALES]
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        line: dict[str, Any] = {"code": r["code"], "edit_version": r["edit_version"]}
        for k, v in r["data"].items():
            line[k] = (
                json.dumps(v, ensure_ascii=False, sort_keys=True)
                if k not in EXPORT_SIMPLE
                else ("" if v is None else v)
            )
        for x in ("name", "description"):
            for loc in SUPPORTED_LOCALES:
                line[f"{x}_{loc}"] = r["l10n"].get(x, {}).get(loc, "")
        w.writerow(line)
    return buf.getvalue()


def _cell(v: str) -> Any:
    return None if v == "" else v


def parse_csv(text: str) -> list[dict[str, Any]]:
    """Inverse of to_csv. Complex columns are JSON; simple ones are coerced by the pydantic schema."""
    out = []
    for raw in csv.DictReader(io.StringIO(text)):
        data: dict[str, Any] = {}
        l10n_texts: dict[str, dict[str, str]] = {}
        for k, v in raw.items():
            if k in ("code", "edit_version") or k is None:
                continue
            if (
                "_" in k
                and k.rsplit("_", 1)[-1] in SUPPORTED_LOCALES
                and k.rsplit("_", 1)[0] in ("name", "description")
            ):
                field, loc = k.rsplit("_", 1)
                if v:
                    l10n_texts.setdefault(field, {})[loc] = v
                continue
            if k in EXPORT_SIMPLE:
                data[k] = _cell(v)
            elif v:
                try:
                    data[k] = json.loads(v)
                except json.JSONDecodeError as exc:
                    raise ValidationFailedError(f"Column {k} is not valid JSON", code="invalid_import") from exc
        for bool_field in ("tradeable", "sellable"):
            if isinstance(data.get(bool_field), str):
                data[bool_field] = data[bool_field].lower() in ("true", "1", "yes")
        out.append(
            {
                "code": raw["code"],
                "edit_version": int(raw["edit_version"]) if raw.get("edit_version") else None,
                "data": data,
                "l10n": l10n_texts,
            }
        )
    return out


async def import_items(db: AsyncSession, rows: list[dict[str, Any]], *, dry_run: bool, actor_id: int) -> dict[str, Any]:
    """Validate every row (schema, publish validators, duplicates, version); commit atomically only when clean."""
    if len(rows) > MAX_IMPORT:
        raise ValidationFailedError(f"At most {MAX_IMPORT} rows per import", code="import_too_large")
    report: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        code = str(r.get("code", ""))
        entry: dict[str, Any] = {"code": code, "action": None, "issues": []}
        if not content.CODE_RE.match(code):
            entry["issues"].append({"level": "error", "code": "invalid_code", "message": "invalid code"})
        if code in seen:
            entry["issues"].append({"level": "error", "code": "duplicate_code", "message": "duplicate in file"})
        seen.add(code)
        existing = (await db.execute(select(ItemTemplate).where(ItemTemplate.code == code))).scalar_one_or_none()
        if existing is None:
            entry["action"] = "create"
        else:
            entry["action"] = "update"
            current = (await content.working_view(db, CT, existing))["edit_version"]
            if r.get("edit_version") is None or r["edit_version"] != current:
                entry["issues"].append(
                    {"level": "error", "code": "version_conflict", "message": f"edit_version must be {current}"}
                )
        entry["issues"] += [i.as_dict() for i in await content.validate(db, CT, code, r.get("data") or {})]
        report.append(entry)
    errors = sum(1 for e in report for i in e["issues"] if i["level"] == "error")
    summary = {
        "rows": len(report),
        "creates": sum(e["action"] == "create" for e in report),
        "updates": sum(e["action"] == "update" for e in report),
        "errors": errors,
        "warnings": sum(1 for e in report for i in e["issues"] if i["level"] == "warning"),
        "dry_run": dry_run,
        "committed": False,
    }
    if not dry_run and errors == 0:
        for r, e in zip(rows, report, strict=True):
            if e["action"] == "create":
                await content.create(db, CT, code=r["code"], data=r["data"], actor_id=actor_id)
            else:
                await content.update(
                    db, CT, code=r["code"], data=r["data"], expected_version=r["edit_version"], actor_id=actor_id
                )
            await seed_texts(db, r["code"], r.get("l10n") or {}, actor_id=actor_id)
        summary["committed"] = True
    await audit.record(
        db, actor_id=actor_id, action="item.import", entity_type="item_template", meta={"summary": summary}
    )
    return {"summary": summary, "report": report}


# --------------------------------------------------------------------------- generator wizard
async def generator(
    db: AsyncSession, params: gen.GeneratorParams, *, commit: bool, confirm_non_dev: bool, actor_id: int
) -> dict[str, Any]:
    cfg = await studio_config(db)
    if params.count > cfg.generator.max_batch:
        raise ValidationFailedError(f"At most {cfg.generator.max_batch} items per batch", code="batch_too_large")
    rules = await item_rules(db)
    family = params.weapon_family or params.armor_family
    kind = None
    if params.weapon_family:
        kind = (
            await db.execute(select(WeaponFamily.kind).where(WeaponFamily.code == params.weapon_family))
        ).scalar_one_or_none()
    fam_key = f"{'weapon_family' if params.weapon_family else 'armor_family'}.{family}.name" if family else None
    fam_texts = (await l10n.get_all_locales(db, [fam_key]))[fam_key] if fam_key else {}
    family_names = {loc: v["value"] for loc, v in fam_texts.items() if v["value"]}
    rarity_names: dict[str, dict[str, str]] = {}
    rows = gen.generate(
        params, rules, cfg.generator, weapon_kind=kind, family_names=family_names, rarity_names=rarity_names
    )
    codes = [r["code"] for r in rows]
    existing = set((await db.execute(select(ItemTemplate.code).where(ItemTemplate.code.in_(codes)))).scalars())
    report = []
    seen: set[str] = set()
    for r in rows:
        issues = [i.as_dict() for i in await content.validate(db, CT, r["code"], r["data"])]
        if not r["code_valid"]:
            issues.append(
                {"level": "error", "code": "invalid_code", "message": "generated code is invalid", "path": "code"}
            )
        if r["code"] in existing or r["code"] in seen:
            issues.append(
                {"level": "error", "code": "duplicate_code", "message": "code already exists", "path": "code"}
            )
        seen.add(r["code"])
        missing = [loc for loc in SUPPORTED_LOCALES if loc not in r["l10n"]["name"]]
        if missing:
            issues.append(
                {
                    "level": "warning",
                    "code": "translation_missing",
                    "message": f"no name pattern for {missing}",
                    "path": "l10n",
                }
            )
        report.append(
            {
                "code": r["code"],
                "name": r["l10n"]["name"].get("en"),
                "tier": r["data"]["tier"],
                "rarity": r["data"]["rarity"],
                "min_level": r["data"]["min_level"],
                "base_stats": r["data"]["base_stats"],
                "requirements": r["data"]["requirements"]["stats"],
                "issues": issues,
            }
        )
    errors = sum(1 for e in report for i in e["issues"] if i["level"] == "error")
    warnings = sum(1 for e in report for i in e["issues"] if i["level"] == "warning")
    summary = {
        "count": len(rows),
        "errors": errors,
        "warnings": warnings,
        "committed": False,
        "env": get_settings().env,
    }
    if commit:
        if errors:
            raise ValidationFailedError(
                "Generator batch has validation errors", code="generator_invalid", details=summary
            )
        if get_settings().env == "prod" and not confirm_non_dev:
            raise ConflictError("Production content batch requires explicit confirmation", code="confirmation_required")
        for r in rows:
            await content.create(db, CT, code=r["code"], data=r["data"], actor_id=actor_id)
            await seed_texts(db, r["code"], r["l10n"], actor_id=actor_id)
        summary["committed"] = True
    await audit.record(
        db,
        actor_id=actor_id,
        action="item.generator",
        entity_type="item_template",
        meta={"params": params.model_dump(), "summary": summary, "codes": codes},
    )
    return {"summary": summary, "rows": report}


async def compare(db: AsyncSession, a: str, b: str) -> dict[str, Any]:
    va = (await content.working_view(db, CT, await content.get_row(db, CT, a)))["data"]
    vb = (await content.working_view(db, CT, await content.get_row(db, CT, b)))["data"]
    return {"a": a, "b": b, "diff": content.diff_data(va, vb)}


async def meta(db: AsyncSession) -> dict[str, Any]:
    """Dropdown data for the editor (codes only; labels are localized client-side or via keys)."""
    from app.game_engine.items import CATEGORIES, EQUIP_SLOTS, RARITY_ORDER, SLOTS_BY_CATEGORY
    from app.game_engine.stats import DAMAGE_TYPES, DERIVED_STATS, PRIMARY_STATS
    from app.models.classes import ArmorFamily
    from app.models.items import AffixDefinition, ItemSet
    from app.services.content.types.items import CLASS_TAGS

    def live[T](model: type[T]) -> Any:
        m: Any = model
        return select(model).where(m.deleted_at.is_(None), m.status != "archived").order_by(m.code)

    async def rows[T](model: type[T]) -> list[Any]:
        return list((await db.execute(live(model))).scalars())

    rules = await item_rules(db)
    weapon = await rows(WeaponFamily)
    return {
        "primary_stats": list(PRIMARY_STATS),
        "derived_stats": list(DERIVED_STATS),
        "damage_types": list(DAMAGE_TYPES),
        "categories": list(CATEGORIES),
        "slots": list(EQUIP_SLOTS),
        "slots_by_category": {k: list(v) for k, v in SLOTS_BY_CATEGORY.items()},
        "rarities": list(RARITY_ORDER),
        "class_tags": list(CLASS_TAGS),
        "bind_policies": ["none", "on_pickup", "on_equip", "account"],
        "source_kinds": ["drop", "craft", "vendor", "quest", "event", "starter", "admin"],
        "weapon_families": [{"code": w.code, "kind": w.kind, "hands": w.hands} for w in weapon],
        "armor_families": [a.code for a in await rows(ArmorFamily)],
        "classes": [c.code for c in await rows(BaseClass)],
        "races": [r.code for r in await rows(Race)],
        "affixes": [
            {"code": a.code, "group": a.group, "kind": a.kind, "rarity_min": a.rarity_min, "class_tag": a.class_tag}
            for a in await rows(AffixDefinition)
        ],
        "sets": [{"code": s.code, "bonuses": s.bonuses} for s in await rows(ItemSet)],
        "requirement_profiles": {k: v.model_dump() for k, v in rules.requirement_profiles.items()},
        "rarity_budgets": {k: v.model_dump() for k, v in rules.rarity_budgets.items()},
        "tiers": [t.model_dump() for t in rules.tiers],
        "requirement_warn_pct": rules.requirement_warn_pct,
        "requirement_error_pct": rules.requirement_error_pct,
        "base_stat_value": rules.base_stat_value,
        "points_per_level": rules.points_per_level,
        "max_sockets": rules.max_sockets,
        "max_upgrade_level": rules.max_upgrade_level,
        "upgrade_pct_per_level": rules.upgrade_pct_per_level,
    }
