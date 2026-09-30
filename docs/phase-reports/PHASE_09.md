# PHASE 09 — Combat engine core
Status: complete

## Done
- `game_engine/rng.py`: platform-independent SplitMix64 + xoshiro256** PRNG (golden values, derive_seed streams,
  unbiased randint, weighted choice). No global `random` in game logic.
- `game_engine/combat/models.py`: immutable `CombatantSnapshot`, `EncounterSnapshot` (players/enemies in
  `CombatInput`), `CombatStrategy`, `CombatConfig`, `CombatResult` (JSON-serializable for AFK snapshots).
- `game_engine/combat/engine.py`: next-event stepping (heap of ACT/TICK/REGEN), attack interval from attack speed,
  hit/accuracy vs dodge with level difference and hit floor, crit (cap), block (physical), armor/magic resist
  mitigation with penetration, physical/magic/elemental/true damage, variance, damage multipliers/reduction
  (capped), vulnerability/weaken/slow/freeze debuffs, shields, DoT/HoT with stacking, buffs/auras (party scope),
  stacks with per-stack effects, procs by trigger with internal cooldowns, thresholds (modifier while true /
  instant on transition, once-per-combat), every-N-hits, scaling bonuses, cooldown & resource-cost modifiers,
  resources/regen/decay, threat tables (enemies target highest threat), lifesteal (cap), potions hook, death,
  win/loss/timeout. Injectable `ActionSelector` → same core for passive-only and Active Tactics.
  PvE/PvP coefficient layer. Compact localization-free structured log.
- Published `combat` balance config (math constants, coefficients, stances). ADR-0009.
- `services/combat_snapshot.py`: DB → CharacterCombatSnapshot (baked stat sheet, dynamic effects from race/class/
  branch/spec/awakening/mastery/rank-scaled talents, unlocked actives, resources, power stat) + Solo Accord for
  solo fights; provider hooks for equipment effects/weapon family (Phase 16).

## Gate
ruff/format/mypy · pytest 154 (RNG golden/distribution; engine: 3 golden SHA-256 digests, determinism, seed
sensitivity, event count ≪ tick loop, loss/timeout, dodge floor, shields, DoT/HoT, freeze, threat targeting,
lifesteal, DR cap, guaranteed crit/every-N, once-per-combat threshold, stacks, armor + PvP coefficient, ability
costs/cooldowns/triggers; benchmark 300 encounters < 6 s (~2 ms/fight); real-content robustness: all 40
specializations build snapshots and simulate; Solo Accord only when solo) · drift none · frontend gate green.
