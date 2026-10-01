# Phase 25 — Balance Simulator, Bot Profiles, Telemetry

## Delivered
- `afk.build_snapshot` extracted from AFK start (unchanged behaviour) and reused by the simulator.
- `balance/simulator.yaml` + `app/game_engine/simulator.py`: synthetic tier gear from generator curves,
  greedy valid talent builds, limits, checker thresholds (racial 3–5%, support band 70–80%, dominance 15%).
- `app/services/simulator.py`: runs in a rolled-back SAVEPOINT sandbox with a throwaway account; params
  level/race/class/spec/talents/gear tier+budget/zone/risk/duration/iterations/seed/gathering node; metrics
  kills/XP/gold/loot value/potions per hour, death probability, DPS/HPS, effective damage taken, support
  contribution, profession yield/hour; JSON/CSV export. Checker: support solo speed vs DPS, racial advantage,
  dominant specializations and talent trees, item tier outliers and impossible requirements. Report only.
- `app/services/telemetry.py`: aggregate-only (sessions, completion/abandonment, deaths/fight, zone choice,
  profession usage, onboarding funnel), computed from game tables, buckets <3 folded into "other", no PII.
- API `POST /admin/balance/simulate[?format=csv]`, `POST /admin/balance/check`, `GET /admin/telemetry`
  (balance.simulate, audited); CLI `python -m scripts.simulate [--check]`.
- Admin `/admin/balance` lab: simulator form + KPI tiles, single-series bar charts (hover + table view,
  reference band), checker warnings, telemetry; 4 locales.
- Layout fix: game screens now respond to the shell content width (container queries) — the inventory bag
  column no longer collapses inside the shell; page max width 7xl.

## Tests
- `tests/test_balance_sim.py` (4); unit `balance-lab.test.tsx`; E2E `balance-lab.spec.ts`.
- Gate: pytest 276, vitest 53, build; E2E 67 passed.

## Findings (decision input, not auto-applied)
- Lv120: cleric/shaman ≈62–64%, bard ≈49% of pure DPS solo speed (target 70–80%); beastkin mage +8% racial.
- Remaining TR combat-log strings for training enemy / basic attack / proc ids are untranslated.
