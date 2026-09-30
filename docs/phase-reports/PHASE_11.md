# Phase 11 — Optional Active Tactics

## Result
- Active Tactics reuse the Phase 10 rule DSL/engine (one combat core): 1–6 ordered priority rules, up to 4
  conditions each, closed condition registry (HP_PERCENT, RESOURCE_PERCENT, TARGET_TYPE, ENEMY_COUNT, TARGET_HP,
  BUFF_PRESENT, DEBUFF_PRESENT, COOLDOWN_READY, ALLY_HP_BELOW, STACK_COUNT, COMBAT_TIME, EVERY_N_ACTIONS), enumerated
  ops; basic attack is the implicit fallback. No expressions/code are evaluated.
- `app/services/tactics.py` validator (registered in `afk_profiles.TACTICS_VALIDATORS`): DSL shape, abilities must be
  published + unlocked + owned by the class path, tags must exist in the kit, and referenced abilities respect
  `ability_limits` (5 core actives + 1 ultimate; duplicates count once).
- `balance/combat_modes.yaml` (`CombatModes` schema): default mode HYBRID, enabled modes, decision encounters
  (boss, arena), max rules, canonical priority template (defensive/heal <35% → boss finisher → AoE ≥3 → spender
  ≥70% → buff/debuff on cooldown). Template is instantiated per kit by tag.
- HYBRID: ordinary AFK stays passive-first; player tactics only drive configured decision encounters — no
  constant input.
- Preview accepts an unsaved draft (`tactics`) and pack size (`enemies` 1–5) or boss; reports per-rule uses.
- `combat_snapshot.usable_abilities` shared by snapshot + validator + options.
- Frontend `TacticsEditor` (inside AFK advanced settings when mode ≠ PASSIVE_ONLY): add/remove/reorder rules,
  ability or tag target, condition rows per kind, recommended template, sample-encounter simulation, save;
  4-locale strings + error codes.
- Repo hygiene: removed accidentally tracked `dump.rdb`, ignored it.

## Tests
- `tests/test_tactics.py`: options/registry/template, canonical save, unsafe/foreign rule rejection (unknown
  ability, locked ultimate, missing tag, >6 rules, unknown kind/op, injection strings, extra keys), loadout limit,
  draft preview per scenario (AoE only vs packs, finisher only vs boss), HYBRID decision-encounter routing, all
  3 modes selectable.
- Frontend unit: tactics editor (template, reorder, draft preview payload, save, rule cap).
- E2E: priority editor flow (add, retarget, reorder, simulate, save, persists after reload).
- Gate: `scripts/check.sh` ALL CHECKS PASSED (pytest 176, vitest 25); `scripts/e2e.sh` 28/28.

## Risks
- Arena encounters don't exist yet; the config value is honored once Phase 12/21 content provides them.
