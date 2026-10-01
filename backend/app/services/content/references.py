"""Content dependency graph: which entities reference a given entity (published data and pending drafts).

References are discovered generically from field names (e.g. `weapon_family`, `template_code`, `prerequisites`,
`ability_code`) so new content types participate without bespoke code. Used to block hard deletes of
referenced content and to show impact before archiving."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentDraft
from app.services.content.registry import CONTENT_TYPES

# field name -> referenced content type
FIELD_TARGETS: dict[str, str] = {
    "ability": "ability",
    "ability_code": "ability",
    "abilities": "ability",
    "unlock_ability": "ability",
    "resource": "class_resource",
    "resources": "class_resource",
    "weapon_family": "weapon_family",
    "weapon_families": "weapon_family",
    "allowed_weapon_families": "weapon_family",
    "armor_family": "armor_family",
    "armor_families": "armor_family",
    "base_class_code": "base_class",
    "class_codes": "base_class",
    "allowed_classes": "base_class",
    "blocked_classes": "base_class",
    "branch_code": "class_branch",
    "specialization_code": "specialization",
    "tree_code": "talent_tree",
    "node_code": "gathering_node",
    "template_code": "item_template",
    "scroll_template_code": "item_template",
    "set_code": "item_set",
    "profession": "profession",
    "profession_code": "profession",
    "zone": "zone",
    "zone_code": "zone",
    "zone_codes": "zone",
    "tier_code": "zone_tier",
    "enemy_code": "enemy",
    "boss_code": "boss",
    "encounter_code": "encounter",
    "drop_table": "drop_table",
    "drop_table_code": "drop_table",
    "ability_profile": "enemy_ability_profile",
    "ability_profile_code": "enemy_ability_profile",
    "prerequisites": "quest",
    "allowed_races": "race",
    "blocked_races": "race",
    "passive_profile": "passive_profile",
}
ITEM_KINDS = ("item", "material")


def extract(data: Any, out: set[tuple[str, str]] | None = None) -> set[tuple[str, str]]:
    """All (entity_type, code) pairs referenced anywhere inside a content data document."""
    out = set() if out is None else out
    if isinstance(data, dict):
        for k, v in data.items():
            target = FIELD_TARGETS.get(k)
            if target is not None:
                for code in v if isinstance(v, list) else [v]:
                    if isinstance(code, str) and code and not code.startswith("group:"):
                        out.add((target, code))
            if k == "pool" and isinstance(v, list):
                out |= {("affix", c) for c in v if isinstance(c, str) and not c.startswith("group:")}
            if k == "ref" and data.get("kind") in ITEM_KINDS and isinstance(v, str):
                out.add(("item_template", v))
            extract(v, out)
    elif isinstance(data, list):
        for v in data:
            extract(v, out)
    return out


async def incoming(db: AsyncSession, entity_type: str, code: str, *, limit: int = 200) -> dict[str, Any]:
    """Entities whose published data or pending draft references (entity_type, code)."""
    target = (entity_type, code)
    found: list[dict[str, Any]] = []
    for ct in CONTENT_TYPES.values():
        fields = list(ct.data_schema.model_fields)
        rows: Any = (await db.execute(select(ct.model).where(ct.model.deleted_at.is_(None)))).scalars()
        ids: dict[int, Any] = {}
        for row in rows:
            if ct.entity_type == entity_type and row.code == code:
                continue
            ids[row.id] = row
            if target in extract({f: getattr(row, f, None) for f in fields}):
                found.append(
                    {"entity_type": ct.entity_type, "code": row.code, "status": row.status, "via": "published"}
                )
        drafts = (await db.execute(select(ContentDraft).where(ContentDraft.entity_type == ct.entity_type))).scalars()
        for d in drafts:
            row = ids.get(d.entity_id)
            if (
                row is not None
                and target in extract(d.data)
                and not any(f["entity_type"] == ct.entity_type and f["code"] == row.code for f in found)
            ):
                found.append({"entity_type": ct.entity_type, "code": row.code, "status": row.status, "via": "draft"})
    by_type: dict[str, int] = {}
    for f in found:
        by_type[f["entity_type"]] = by_type.get(f["entity_type"], 0) + 1
    return {"entity_type": entity_type, "code": code, "total": len(found), "by_type": by_type, "items": found[:limit]}


async def outgoing(db: AsyncSession, data: dict[str, Any]) -> list[dict[str, str]]:
    return [{"entity_type": t, "code": c} for t, c in sorted(extract(data)) if t in CONTENT_TYPES]
