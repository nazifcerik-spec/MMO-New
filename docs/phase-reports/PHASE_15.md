# Phase 15 — Admin Item Studio

## Result
- Backend `app/services/item_studio.py` + `app/api/admin/items.py`: server-side filtered/sorted list (code +
  localized-name search, translation completeness, class tag, family, status), inspector (working data, 4-locale
  texts, validation, requirement/rarity/tier budgets, reverse references to drop tables/zones/bosses/salvage),
  text editing (creates keys, optimistic versions), clone, compare, test-character preview (transient character
  in a rolled-back savepoint: requirement pass/fail + derived-stat deltas), safe-field bulk edit, bulk
  translation status (review permission enforced), CSV/JSON export ↔ import round-trip with dry-run report and
  atomic commit, Item Generator Wizard (pure deterministic `game_engine/item_generator.py`: tier spread,
  largest-remainder rarity allocation, level spread, stat curves, localized name patterns; duplicate/validation
  checks; atomic draft batch; audit report), meta endpoint.
- Config `balance/item_studio.yaml`: preview profiles (Warrior Lv100/600, Rogue 300, Mage 850, Cleric 400,
  Paladin 1000), generator curves/multipliers/vendor/durability formulas.
- Content service fix: non-duplicate integrity errors no longer masquerade as duplicates (Phase 12) — reused.
- Frontend: `/admin/items` three-pane studio (virtualized table, saved filters, bulk bar, import panel),
  `/admin/items/[code]` 11-tab editor (schema-driven effect forms + advanced JSON, requirement builder with
  budget meter, affix pool table, unique/set, sockets/upgrade curve, sources + reverse refs, salvage, 4-locale
  tooltip preview + test-character deltas, history/diff/rollback), `/admin/items/generator` wizard; toasts,
  unsaved guard, Ctrl+S, confirmations; 4 locales. Docs: `docs/admin/ITEM_STUDIO.md`.

## Tests
- `tests/test_item_studio.py`: RBAC matrix, filters/search/sort/translation state, inspector, clone,
  concurrent edit conflict (409 with current data), invalid effect schema, archive, rollback-as-new-revision,
  compare, translation fallback + bulk status, safe bulk edit (unsafe/stale rejected atomically), CSV/JSON
  export→import dry-run/atomic commit/version conflicts, generator dry-run/commit/duplicate prevention/
  invalid pattern/unique-required, preview profiles.
- Frontend unit `item-studio.test.tsx` (schema form, nested effects, raw JSON guard, budget formula, list +
  inspector); E2E `item-studio.spec.ts` (clone→edit→Ctrl+S→texts→preview→publish→history; generator).
- Gate: `scripts/check.sh` ALL CHECKS PASSED (pytest 213, vitest 34); `scripts/e2e.sh` 34 passed (Item Studio
  specs skip on phone viewport by design).

## Risks
- Recipes/crafting links arrive in Phase 18 (reverse `recipes` list is empty until then).
