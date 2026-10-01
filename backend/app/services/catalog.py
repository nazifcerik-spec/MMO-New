"""Launch item catalog (Phase 19): generate → validate (dry-run) → create drafts → publish, plus the report.

Generation is deterministic from `catalog/launch_catalog.yaml` + published balance; codes are stable, so
re-running is idempotent (existing codes are skipped, never overwritten). EN names are seeded as published,
TR/ZH-CN/ES as drafts for translator review. Nothing is published with validation errors."""

import time
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.loader import load_yaml
from app.core.errors import ValidationFailedError
from app.game_engine import catalog as engine
from app.game_engine.item_generator import ItemStudioConfig
from app.localization import service as l10n
from app.models.items import ItemTemplate
from app.services import audit
from app.services.content import service as content
from app.services.content.types.balance import get_published_balance
from app.services.content.types.items import ITEM_TEMPLATE_TYPE, item_rules

CT = ITEM_TEMPLATE_TYPE
PUBLISH_BATCH = 200


def catalog_config() -> dict[str, Any]:
    cfg: dict[str, Any] = load_yaml("catalog/launch_catalog.yaml")
    return cfg


async def build(db: AsyncSession) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float]]:
    cfg = catalog_config()
    rules = await item_rules(db)
    gen = (await get_published_balance(db, "item_studio", ItemStudioConfig)).generator
    ref = load_yaml("classes/reference.yaml")
    professions = load_yaml("professions/professions.yaml")["professions"]
    rows = engine.generate(
        cfg,
        rules,
        gen,
        weapon_families=ref["weapon_families"],
        armor_families=ref["armor_families"],
        professions=professions,
    )
    return cfg, rows, dict(gen.slot_multipliers)


async def validate_rows(db: AsyncSession, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the real content validators. Salvage links to materials of the same batch are resolved in-batch."""
    batch = {r["code"] for r in rows}
    out = []
    for r in rows:
        issues = []
        for i in await content.validate(db, CT, r["code"], r["data"]):
            if i.code == "unknown_reference" and i.path.startswith("salvage"):
                idx = int(i.path.split("[")[1].rstrip("]"))
                if r["data"]["salvage"][idx]["template_code"] in batch:
                    continue
            issues.append(i.as_dict())
        out.append({"code": r["code"], "issues": issues})
    return out


def _summary(
    cfg: dict[str, Any], rows: list[dict[str, Any]], checks: list[dict[str, Any]], slot_mult: dict[str, float]
) -> dict[str, Any]:
    counts = Counter((i["level"], i["code"]) for c in checks for i in c["issues"])
    dist = engine.distribution(rows)
    return {
        "targets": cfg["targets"],
        "target_total": sum(cfg["targets"].values()),
        "matches_targets": dist["by_category"] == cfg["targets"] and dist["total"] == sum(cfg["targets"].values()),
        "distribution": dist,
        "errors": sum(n for (lvl, _), n in counts.items() if lvl == "error"),
        "warnings": sum(n for (lvl, _), n in counts.items() if lvl == "warning"),
        "issue_codes": {f"{lvl}:{code}": n for (lvl, code), n in sorted(counts.items())},
        "outliers": engine.outliers(cfg, rows, slot_mult),
    }


async def dry_run(db: AsyncSession) -> dict[str, Any]:
    cfg, rows, slot_mult = await build(db)
    checks = await validate_rows(db, rows)
    s = _summary(cfg, rows, checks, slot_mult)
    s["sample_issues"] = [c for c in checks if c["issues"]][:25]
    return s


async def commit(
    db: AsyncSession, *, publish: bool, actor_id: int | None, only: set[str] | None = None
) -> dict[str, Any]:
    """Create missing catalog templates as drafts (+ texts); optionally publish them in validated batches."""
    started = time.monotonic()
    cfg, rows, slot_mult = await build(db)
    existing = set((await db.execute(select(ItemTemplate.code))).scalars())
    todo = [r for r in rows if r["code"] not in existing and (only is None or r["code"] in only)]
    if not todo:
        return {"created": 0, "published": 0, "skipped_existing": len(rows) - len(todo), "seconds": 0.0}
    checks = await validate_rows(db, rows)
    summary = _summary(cfg, rows, checks, slot_mult)
    if summary["errors"]:
        raise ValidationFailedError("Catalog has validation errors", code="catalog_invalid", details=summary)
    created: list[str] = []
    for r in todo:
        await content.create(db, CT, code=r["code"], data=r["data"], actor_id=actor_id)
        await l10n.seed_values(db, f"item.{r['code']}.name", r["l10n"]["name"], namespace="item")
        created.append(r["code"])
    published = 0
    if publish and created:
        for i in range(0, len(created), PUBLISH_BATCH):
            chunk = created[i : i + PUBLISH_BATCH]
            await content.publish(
                db, [(CT, c) for c in chunk], actor_id=actor_id, label=f"launch catalog v{cfg['version']}",
                acknowledge_warnings=True,
            )  # fmt: skip
            published += len(chunk)
    await audit.record(
        db, actor_id=actor_id, action="item.catalog", entity_type="item_template",
        meta={"created": len(created), "published": published, "version": cfg["version"]},
    )  # fmt: skip
    return {
        "created": len(created),
        "published": published,
        "skipped_existing": sum(1 for r in rows if r["code"] in existing),
        "seconds": round(time.monotonic() - started, 1),
        "summary": {k: v for k, v in summary.items() if k != "outliers"},
    }


def report_markdown(summary: dict[str, Any]) -> str:
    d = summary["distribution"]
    cats = list(summary["targets"])
    lines = [
        "# Launch Item Catalog Report",
        "",
        "Generated by `python -m scripts.generate_catalog` from `app/content/data/catalog/launch_catalog.yaml`",
        "(deterministic; stable codes). EN names published, TR/ZH-CN/ES seeded as `draft` for translator review.",
        "",
        f"- Total: **{d['total']}** / target {summary['target_total']} — "
        f"{'matches' if summary['matches_targets'] else 'DOES NOT MATCH'} category targets",
        f"- Validation: {summary['errors']} errors, {summary['warnings']} warnings",
        f"- Duplicate codes: {d['duplicate_codes']}; duplicate names per locale: {d['duplicate_names']}",
        "",
        "## Category targets",
        "",
        "| Category | Target | Generated |",
        "|---|---:|---:|",
        *[f"| {c} | {summary['targets'][c]} | {d['by_category'].get(c, 0)} |" for c in cats],
        "",
        "## Tier × category",
        "",
        "| Category | " + " | ".join(f"T{t}" for t in range(11)) + " |",
        "|---|" + "---:|" * 11,
        *[
            f"| {c} | " + " | ".join(str(d["tier_by_category"].get(c, {}).get(t, 0)) for t in range(11)) + " |"
            for c in cats
        ],
        "",
        "## Rarity",
        "",
        "| Rarity | Count |",
        "|---|---:|",
        *[f"| {r} | {n} |" for r, n in d["by_rarity"].items()],
        "",
        "## Class tags (equipment)",
        "",
        "| Tag | Count |",
        "|---|---:|",
        *[f"| {t} | {n} |" for t, n in d["by_class_tag"].items()],
        "",
        "## Validation issue codes",
        "",
        *([f"- `{k}`: {n}" for k, n in summary["issue_codes"].items()] or ["- none"]),
        "",
        "## Stat budget outliers (slot-normalized power vs family/tier median)",
        "",
    ]
    if summary["outliers"]:
        lines += ["| Code | Category | Family | Tier | Power | Median | Ratio |", "|---|---|---|---:|---:|---:|---:|"]
        lines += [
            "| "
            + " | ".join(str(o[k]) for k in ("code", "category", "family", "tier", "power", "median", "ratio"))
            + " |"
            for o in summary["outliers"]
        ]
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"
