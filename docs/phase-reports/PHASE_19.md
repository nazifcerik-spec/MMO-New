# Phase 19 — Loot, Pity, Drop Tables, 1,520-Item Launch Catalog

## Delivered
- `balance/loot.yaml` + `app/game_engine/loot.py`: LUK rare bonus with diminishing returns (max 15%),
  rarity rolls for item pools, drop conditions (zone codes/tags, level, boss), separate configurable pity,
  per-rarity ownership limits (relic 1, mythic 3 → excess auto-sold).
- AFK integration: `LootConfig` snapshotted per session (legacy sessions unchanged), `luck_bonus_pct` in
  results, pity progress signal only for configured content kinds; zone tags in `ZoneBundle`.
- Launch catalog: `catalog/launch_catalog.yaml` + `app/game_engine/catalog.py` + `app/services/catalog.py`:
  exactly 1,520 templates (280/360/120/90/160/240/120/80/70), 4-locale token naming (EN published, others
  draft), class tags, tier T0–T10 coverage, relics T10-only with fixed effects, salvage links to catalog
  materials. Dry-run through real validators: **0 errors, 0 warnings**; stat-budget outlier report.
- `scripts/generate_catalog.py` (dry-run → `docs/content/ITEM_CATALOG_REPORT.md`, `--commit --publish`),
  `catalog` seed step (idempotent, ~35 s first run), admin `GET/POST /admin/items/catalog` (item.edit;
  publish needs item.publish) and an Item Studio catalog panel. ADR-0011.

## Tests
- `tests/test_loot_catalog.py` (7): LUK DR, rarity determinism/modest shift, conditions + pity, exact targets
  & determinism & unique names, real-validator dry-run, idempotent commit + text statuses + relic limit, RBAC.
- `tests/test_afk.py`: loot snapshot, forced pity, legacy snapshot resolution.
- Gate: ruff/mypy, pytest 243, migrations, vitest 40, build — green; E2E 40 passed.

## Risks
- TR/ZH-CN/ES catalog names are machine-assembled drafts (grammar review needed in admin).
- Two T0 cloak outliers (level spread inside T0) are reported, not auto-fixed.
