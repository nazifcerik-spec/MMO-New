# ADR-0002 — Deterministic AFK resolution
Status: Accepted (Phase 00)

## Decision
- An AFK session (max 3 h) is a row, not a running loop. On start we persist an immutable snapshot:
  character build (level, effective stats, race/class/spec/awakening/talent effects, equipment effects),
  strategy/tactics profile, zone + enemy pool stats, risk profile, balance/content release ids,
  daily-efficiency allotment, consumable policy, server-generated 64-bit seed, `started_at`, `ends_at` (UTC).
- Resolution (at claim, or earlier by a sweeper after `ends_at`) runs a deterministic simulation from the
  snapshot only: sample a bounded number of encounters with the seeded PRNG and extrapolate by aggregation
  (no per-second ticks). Result JSON + result hash stored once.
- Claim is a single DB transaction guarded by row lock + unique claim record + idempotency key; rewards
  are granted exactly once and written to the economy ledger.
- Live balance/content changes never affect existing sessions (they read only their snapshot).

## Consequences
Same snapshot + seed ⇒ identical result (golden tests). Replay/debug tooling re-runs from stored inputs.
Engine RNG is our own seeded PRNG (not `random` global state); money/XP math uses integers.
