# Phase 14 — Item Domain Model

## Result
- Migration 0012: `item_templates` (all listed template fields: localized keys, category/subcategory/family,
  slot, weapon/armor family FKs, tier, min level, rarity, stack size, bind policy, trade/sell flags, vendor value,
  durability, sockets, class tags, allowed/blocked classes & races, requirement profile + stat/profession
  requirements, base stats, fixed effects, affix pool rules, unique effect, set FK, salvage, icon, sources;
  content status/version/revisions), `affix_definitions`, `item_sets`, `item_instances` (owner, template code +
  revision, rolled affixes/values, durability, sockets/gems, bind, quality, upgrade, location/slot, quantity,
  roll seed, provenance UUID, source, optimistic version), `item_provenance` (append-only, idempotency key).
- `balance/item_rules.yaml`: canonical T0–T10 gates (levels, rarity band, suggested requirement totals), rarity
  affix budgets (common 0–1 … mythic 5–6, legendary unique, mythic unique + mastery scaling, relic fixed),
  requirement profiles (heavy/finesse/caster weapon, healing focus, heavy/light/cloth armor, support relic).
- Pure engine `game_engine/items.py`: distributable stat budget, requirement warning (>60%) / error (>70%,
  unreachable single stat), suggested requirements (profile scaled, clamped to tier band), deterministic affix
  roll (weighted, exclusive groups, ≤1 class-tag affix, tier value bands), sockets, instance effects (base ×
  upgrade, fixed, affixes, unique, gems), requirement check (level/stats/class/race).
- Publish validators: tier level gate, rarity band, slot/category/family consistency, stacking rules, affix
  budget/pool/relic rules, unique + mastery requirements, sockets, durability, requirement budget + tier band,
  class/race/set/salvage references, effects; affix roll-band gaps; set bonus uniqueness.
- Service: revision-pinned idempotent grants with provenance; equipment providers wired into stat sheet
  (static stats) and combat snapshot (dynamic effects, weapon family) incl. set bonuses; broken gear inert.
- API: catalog (filters, cursor, localized), template detail, character items list/detail (requirement check),
  staff grant (`economy.grant`, idempotency key, audit), roll preview (`item.edit`).
- Sample content: 12 affixes, 1 set, 3 materials, 1 potion, 12 equipment templates (worn → relic), 4 locales;
  zero publish errors. ADR-0004 amended.

## Tests
- `tests/test_items.py`: canonical gates/budgets/profiles, requirement thresholds, deterministic + idempotent
  grants with provenance, stack limits, RBAC, roll budgets over seeds (class-tag cap, relic fixed), revision
  pinning after republish, requirement checks, equipment stats + set bonus + broken gear, validators, catalog.
- Gate: `scripts/check.sh` ALL CHECKS PASSED (pytest 205); `scripts/e2e.sh` 32/32 (no UI change this phase).

## Risks
- Equip/unequip flows, capacity and loot granting arrive in Phase 16; gems/upgrades are data-ready only.
