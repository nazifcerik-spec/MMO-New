# PHASE 04 — Core content schema, versioning, effect registry
Status: complete

## Done
- `ContentMixin` (immutable code, l10n keys, status draft/published/disabled/archived, optimistic version,
  revision_no, created_by/updated_by, published_at, soft delete) + `content_releases`, immutable
  `content_revisions` (JSON snapshot + SHA-256), `content_drafts` (pending edits of live entities),
  first concrete type `balance_configs`. Migration `0004`. ADR-0008.
- Generic lifecycle service (`services/content/service.py`): create, draft update with 409 + current data,
  validate (schema + per-type validators, error/warning issues), atomic publish bundles under one release
  (advisory-locked version counter), disable/archive/restore, delete-only-if-unpublished, history, revision
  fetch, flattened diff (revision↔revision or revision↔working copy), rollback-as-new-revision. All audited.
- `ContentType` registry: new content = model + schema + validators + permissions (no bespoke CRUD).
- Effect registry (`game_engine/effects.py`): 21 types incl. all 17 required (STAT_FLAT … PROFESSION_YIELD_MOD)
  + DAMAGE, HEAL, PROGRESSION_MODIFIER, STACK_GAIN; `effect_type + schema_version + strict params`;
  shared `Condition` DSL (metric/op/value); nested trigger effects validated recursively with depth limit;
  JSON schemas exported for admin form generation. Stat/damage-type vocabulary in `game_engine/stats.py`.
- Balance schema registry; canonical `afk` config seeded (3 h cap, 100/80/50/25 bands) via idempotent
  create+publish seeding that never clobbers tuned live data.
- APIs: admin `/admin/content/types|effects/registry|releases|{type}|{type}/{code}[/validate|status|history|
  revisions/{n}|diff|rollback|draft]`; public `/content/version` (published only).

## Gate
ruff/format/mypy · pytest 71 (effect validation incl. unknown type/extra keys/injection strings/nesting,
RBAC denials, full draft→publish→edit→409→publish→history→diff→rollback, validation-blocked publish,
atomic bundle, archive read-only, duplicate/invalid codes, canonical AFK config) · drift none · frontend gate green.

## Next
- Phase 05 registers the `progression` balance schema and the stat calculator.
- Generic history viewer UI arrives with Item Studio / Content Studio (Phases 15/24).
