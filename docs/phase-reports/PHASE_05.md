# PHASE 05 — Stats, level, XP, titles, progression engine
Status: complete

## Done
- Pure engine `game_engine/progression.py`: published `progression` balance config (schema-validated):
  cap 1000, 3 points/level (2,997 total), breakpoints 100/300/600/850/1000, soft-cap bands
  1.0/0.70/0.45/0.25, 13-step title ladder, config-driven XP curve (per-segment hour targets with linear
  ramp × reference XP/hour ^ exponent) calibrated to exactly 968 h (8/48/209/277/193/233) and
  non-decreasing per level; multi-level `apply_xp`, hard cap with overflow → `mastery_xp` (horizontal).
- Central stat calculator `game_engine/stat_calculator.py`: sources base/race/class/allocated/equipment/
  talent/buff kept separate with full breakdown; soft caps then % bonuses; derived stats from data formulas
  and caps. Providers hooks for race/class/equipment/talent contributions (Phases 06–16).
- Data-driven stat profiles (tank, physical_dps, caster_dps, healer, hybrid_support) with class-token
  resolution (`main`, `utility`, `A|B` splits) and deterministic largest-remainder distribution.
- Respec contract: level-banded gold cost, free <Lv100, discount hook (Human first-300-points, Phase 06),
  cooldown; charged through the new integer `wallets` + append-only `economy_ledger` (idempotent keys).
- DB (migration `0005`): character_stat_allocations, progression_events (unique idempotency per character),
  wallets, economy_ledger, `characters.mastery_xp`.
- APIs: `GET /characters/{id}/progression` (+localized labels), `POST .../stats/allocate|auto|respec`
  (Idempotency-Key required, optimistic character version), `GET .../stats/respec-quote`,
  `GET /content/stat-profiles`, admin `POST /admin/characters/{id}/xp` (economy.grant, audited).
- Localization: 13 titles, 5 profiles, 35 derived stat names × 4 locales (DB).
- UI `/game/characters/[id]`: XP bar, title/next title/next breakpoint, +/- allocation bounded by unspent
  points, template apply, respec quote, primary/derived stats with expandable per-source breakdown.

## Gate
ruff/format/mypy · pytest 94 (soft caps, 968 h calibration, cap 1000 + overflow, multi-level + points,
breakpoints, titles, distribution, respec bands/discount/insufficient funds, breakdown order, caps,
allocation validation, idempotent replay, 409 stale version, concurrent same-key XP applied once, RBAC) ·
drift none · eslint/tsc · vitest 15 · build.

## Notes
- Progression E2E needs a creatable character; covered once race/class content lands (Phase 07).
