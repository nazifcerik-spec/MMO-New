# ADR-0011: Loot rules and the deterministic launch catalog

Status: accepted (Phase 19)

## Decision
- Loot balance lives in `balance/loot.yaml` (`LootConfig`) and is **snapshotted into each AFK session**.
  Sessions without a snapshot (pre-Phase 19) keep the legacy drop path so old results never change.
- LUK → rare bonus is `max × LUK / (LUK + half_point)` (default max 15%, half at 600 LUK): small and
  diminishing, cannot dominate. Risk profile, gadget `rare_chance` (capped) and LUK add up.
- Pity is a separate mechanic (`pity.enabled/threshold_fights`): the first roll of the next qualifying table
  is restricted to rare-capable entries and guaranteed rare. Progress is shown only for content kinds in
  `pity.show_progress_for`.
- Drop entries support `conditions` (zone codes/tags, level range) plus `boss_only`; item pools without a
  fixed rarity roll rarity from `rarity_weights`.
- Ownership limits per rarity (`owned_limits`, e.g. relic 1) are enforced at grant time; excess is auto-sold.
- The 1,520-template launch catalog is generated **deterministically** from `catalog/launch_catalog.yaml`
  (token naming: epithet × tier material × family/noun; stable codes `<line>_t<tier>_<epithet>`), validated by
  the same publish validators as hand-made items, and published by the `catalog` seed step. Existing codes are
  never overwritten. EN names are published; TR/ZH-CN/ES are drafts for translators.
- The test suite disables catalog seeding (`MMO_SEED_LAUNCH_CATALOG=false`) for speed and covers it through
  dedicated generation/validation/commit tests.

## Consequences
Re-running the generator is safe and reproducible; balance edits create new catalog versions rather than
mutating published templates. Curated uniques can replace generated codes later through Item Studio revisions.
