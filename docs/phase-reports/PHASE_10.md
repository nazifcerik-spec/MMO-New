# Phase 10 — Passive-Only Combat

## Result
- Strategy layer on the shared combat core (ADR-0009): stance (aggressive/guarded/efficient), target priority,
  potion threshold/limit/cooldown, risk level (`balance/risk_profiles.yaml`), loot filter contract, class passive profile.
- Passive layers map to engine primitives: base attack → basic swings; stance → `combat.yaml` stance mods;
  trigger/threshold/cycle passives → `PROC_CHANCE` / `THRESHOLD_TRIGGER` / `EVERY_N_HITS`;
  target rule → `target_priority`; consumable rule → potion strategy.
- Rules DSL (`game_engine/combat/rules.py`): ordered priority rules (max 6, max 4 conditions) with 12 whitelisted
  condition kinds; validated with pydantic, no code execution.
- Class identity is pure data: `profiles/passive_profiles.yaml` (20 profiles, 2 per class, `sort_order`) with rules +
  extra effects (block counter, execute, rage stack, poison/trap procs, element cycle, heal thresholds, HoT refresh,
  songs, totems/spirit procs). No class-name branches in code.
- `character_afk_profiles` (migration 0009): preset or advanced settings, optimistic `version`, audit on change.
- API: `GET/PUT /characters/{id}/afk-profile`, `POST /characters/{id}/combat/preview` (deterministic seeds,
  training pack by level + risk, optional boss; win/death rate, duration, DPS, potions, per-rule usage).
- HYBRID mode = passive profile for trash, Active Tactics only in boss encounters (Phase 11 fills tactics).
- Engine fix: procs can no longer trigger procs (`proc_depth` guard) — a 100% on-hit damage proc previously
  recursed without bound. Golden digests unchanged.
- Frontend `/game/characters/[id]/afk`: preset cards (radiogroup) + advanced editor (mode, passive profile, stance,
  target, risk, potion slider, loot filter) + training preview; 4-locale strings.

## Balance (scripts/balance_probe.py, 20 fights vs training pack)
Support kill speed vs pure DPS / net damage taken % (DPS avg 60–67%):
| class | L100 | L500 | L900 |
|---|---|---|---|
| cleric | 0.70 / 31 | 0.69 / 34 | 0.70 / 34 |
| paladin | 0.82 / 15 | 0.77 / 17 | 0.78 / 20 |
| druid | 0.74 / 30 | 0.73 / 32 | 0.71 / 39 |
| bard | 0.70 / 44 | 0.73 / 47 | 0.81 / 46 |
| shaman | 0.72 / 40 | 0.71 / 57 | 0.67 / 49 |
All classes 100% win rate at balanced risk.

## Tests
- `tests/engine/test_passive_rules.py`: priority ordering, threshold firing, every-N cycle, deterministic procs +
  proc rate, no proc chaining, potion limit/cooldown, DSL rejection paths.
- `tests/test_afk_profiles_api.py`: defaults + localized options, preset → advanced edit, 409 conflict,
  validation denials, ownership 404, deterministic preview, support (cleric/bard/shaman) passive-only solo viability.
- Frontend unit `afk-profile-editor.test.tsx`; E2E character flow extended (preset, advanced save, preview).
- Gate: `scripts/check.sh` ALL CHECKS PASSED; `scripts/e2e.sh` 26/26.

## Risks / follow-ups
- Loot filter is stored/validated only; applied at AFK claim (Phase 13/16). Potions come from inventory providers
  (Phase 16); preview uses an explicit count until then.
- Paladin L100 and bard L900 slightly above 0.80 band; revisit with Phase 25 balance simulator.
