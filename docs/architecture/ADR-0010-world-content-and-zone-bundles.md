# ADR-0010: World content model and immutable zone bundles

Status: accepted (Phase 12)

## Decision
- Zone tiers, zones, enemy templates, enemy ability profiles, encounter templates, boss templates and drop
  tables are ContentMixin entities (draft → validated publish → immutable revisions, ADR-0008).
- Cross-entity single references use FKs on stable codes (zone→tier/drop table, enemy/boss→ability profile,
  boss→drop table). Always-read-together child structures (encounter pools, boss pools, members, drop entries,
  zone requirements, boss phases/adds, profession nodes) are validated JSONB arrays with strict pydantic schemas
  instead of child tables, keeping publish/revision/diff atomic per entity.
- Two scaling layers: per-level `enemy_scaling` balance config (ranks, archetypes, sanity reference) and
  per-tier `zone_tiers.scaling`. Bosses are separate templates (rank `boss`, phases → THRESHOLD_TRIGGER, enrage →
  time-conditioned DAMAGE_MULTIPLIER) and always `is_boss`.
- `world.load_bundle` resolves a published zone into an immutable, JSON-serializable `ZoneBundle` (+ content
  release version). AFK sessions (Phase 13) snapshot the bundle, so later content edits never change an old
  session; encounter/drop generation is pure and seeded (`game_engine/world.py`).
- Requirement checks deny by default; zone clears/quests plug in via provider lists.

## Consequences
- Drop entries reference items/materials by code; reference checkers are registered when those systems exist
  (`DROP_REFERENCE_CHECKERS`).
- Draft data must satisfy DB CHECK constraints; the schema repeats them so users get 422s, and non-unique
  integrity errors map to `constraint_violation` (not `duplicate_code`).
