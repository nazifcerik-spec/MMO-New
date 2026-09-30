# ADR-0009 — Deterministic combat engine
Status: Accepted (Phase 09)

## Decision
- Pure module `backend/app/game_engine/combat/` (no HTTP/DB). Input: `CombatInput` (combatant snapshots, strategy,
  seed, context pve|pvp, content version). Output: `CombatResult` (outcome, elapsed, per-combatant totals, procs,
  kills, compact structured log). Balance values come from the published `combat` config (`CombatConfig`).
- Next-event stepping with a heap (`ACT`, `TICK`, `REGEN`); ties broken by insertion sequence. No wall-clock,
  no per-millisecond loop.
- Randomness only from our xoshiro256** `Rng` (SplitMix64-seeded) — never Python's global `random`.
  Same snapshot + seed ⇒ byte-identical result (golden SHA-256 tests).
- Static stat effects are baked into snapshot stats by the stat calculator; the engine resolves dynamic effects
  (procs by trigger, thresholds, every-N, stacks, timed buffs/debuffs, auras, scaling, cooldown/cost modifiers,
  shields, DoT/HoT, threat, death). Solo Accord is applied at snapshot time for solo fights.
- One core for passive-only and Active Tactics: an injectable `ActionSelector` returns an ability or `None`
  (basic attack). Enemies use the same primitives.
- Log events are localization-free (`{event_type, actor_id, target_id, ability_code, amount}`), capped by
  `log_limit`; UI renders them per locale.
- PvE/PvP separation via a coefficient layer (`coefficients.pve|pvp`), keeping PvE numbers untouched.
