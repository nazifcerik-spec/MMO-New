# Phase 17 — Profession Progression & 15 Professions

## Result
- Content (migration 0014): `professions` (type, tool kind, canonical relevant stats, title key, effects) and
  `profession_specializations` (exactly two per profession; effects limited to `PROFESSION_YIELD_MOD` for their
  own profession — validated on publish). Seeded 15 canonical professions × 2 specializations, rank names and
  grandmaster titles in 4 locales (`professions/professions.yaml`).
- `balance/professions.yaml` + pure `game_engine/professions.py`: cap 500, ranks Apprentice 1 · Journeyman
  100 · Expert 200 · Artisan 300 · Master 400 · Grandmaster 500; XP curve independent of character XP;
  unlicensed professions stop at 199 (no XP banking above); license rules (max 3 active, first 3 free, 7-day
  cooldown + level-banded gold for later changes, respecialization cost); stat influence on speed/quality only
  (capped, never hard-locks); tool-tier yield (heavy loss below node tier, small capped bonus above; no tool =
  tier −1); node access by profession level (50/tier); crafting quality chain common→fine→superior→masterwork→
  mythic_crafted with deterministic rolls and over-level/quality bonuses.
- Character state: `character_professions` (level, xp, specialization, license, optimistic version),
  `character_profession_meta` (activations, last change), `profession_xp_events` (exactly-once XP ledger),
  `character_titles` (grandmaster titles; reused by Phase 22).
- Service: profession modifiers are aggregated from the effect registry (race effects, equipped gear incl.
  tools, licensed specialization, provider hook) — no combat code involvement; XP grants apply the `xp` kind;
  node check exposes access/tool/stat/modifier data for Phase 18 gathering/crafting.
- API: public catalog, character professions view, license activate/revoke, specialize, node check, staff XP
  grant (`economy.grant`, audited, idempotent).
- Frontend `/game/characters/[id]/professions`: license summary/cooldown, type filter, 15 cards (rank, level/cap,
  XP bar, stats & bonuses, modifiers, title), license toggle with cost confirmation, specialization picker at
  200+; 4 locales.

## Tests
- `tests/test_professions.py`: ranks/curve/cap/tool yield/node levels; deterministic quality roll with skill
  scaling; canonical catalog + localization; XP independence, unlicensed cap, licensed 500 + title, idempotent
  replay, RBAC; license limit/cooldown/cost (+insufficient funds); specialization gates and respec cost; registry
  modifiers (dwarf mining speed, tool yield +5%, tool tier yields).
- Frontend unit `professions.test.tsx`; E2E license activate/revoke with racial modifier.
- Gate: `scripts/check.sh` ALL CHECKS PASSED (pytest 227, vitest 39); `scripts/e2e.sh` 38 passed.

## Risks
- Recipe knowledge, gathering/crafting yields and AFK profession tasks are implemented on these rules in Phase 18.
