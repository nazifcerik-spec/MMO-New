# Phase 13 — 3-Hour AFK Session Engine

## Result
- Migration 0011: `afk_sessions` (immutable JSONB snapshot + canonical hash, 62-bit server seed, started/ends,
  stopped_at, result + hash, claim key/result; CHECK ends ≤ start + 3 h; partial unique index = one unclaimed
  session per character), `afk_daily_usage` (account × player-day seconds), `character_afk_stats` (pity, totals).
- Snapshot at start (`game_engine/afk.AfkSnapshot`): level/xp, effective stats + race/class/spec/awakening/talent
  and equipment-provider effects (combat snapshot), passive/tactics rules for normal and boss fights, strategy,
  potion hold (providers), immutable `ZoneBundle`, risk profile, combat + AFK config, XP-per-unit from the
  progression curve, over-level penalty, rested bonus (extension point, disabled), pity start, profession task
  (validator hook; rejected until Phase 17), efficiency segments, content version, build summary.
- Resolution (no real-time loop): 24 normal + 4 boss full combat samples, then a seeded fight-by-fight walk
  (encounter composition, outcome from sampled win rate × risk death factor, drops, downtime/rest). Death =
  20 min recovery (lost efficiency), durability loss, small gold cost; never loss of earned progress.
  CPU work runs off the event loop.
- Daily efficiency: per account player-day (UTC reset hour), bands 100/80/50/25 sliced at start across band and
  day boundaries; planned seconds reserved under row locks and trued-up to actual on claim (early stop refunds).
- Claim: Redis lock (fast-fail), DB row lock, unique claim key replay, idempotent XP (`progression_events`) and
  gold (`economy_ledger`, reason `afk_reward`); loot/potion/durability/profession hooks for later phases (drops
  reported as pending until inventory exists); audit records. Sweeper (`scripts.afk_sweeper`, compose service,
  `POST /admin/afk/sweep`) pre-resolves with SKIP LOCKED; `POST /admin/afk/{id}/replay` verifies result and
  snapshot hashes.
- 3-Hour Satisfaction Rule: claim summary always has signals (level up, XP % of level, boss kills, rare drops,
  gold, pity progress).
- API: start/current/stop/claim/history under `/characters/{id}/afk`.
- Frontend: AFK panel on the character page — start form (eligible zones, 5 min–3 h, risk), server-offset
  countdown, snapshot + efficiency band summary, stop early, claim screen with localized signals; 4 locales.

## Tests
- Engine: fresh day, band crossing, player-day boundary reset, used-by-day, 3 h schema cap, over-level penalty.
- API: validation/cap/zone lock/idempotent start/single active/early claim/ownership; claim once + replay +
  ledger + history; 4 concurrent claims → exactly one grant; mid-session build/profile/level change doesn't alter
  snapshot, replay hash matches (RBAC 403 for players); band crossing + early-stop true-up; deterministic
  resolve (same seed equal, other seed differs, shorter elapsed smaller); sweeper; death friction.
- Frontend unit (helpers, start payload + idempotency key, claim summary); E2E start→countdown→stop→claim.
- Gate: `scripts/check.sh` ALL CHECKS PASSED (pytest 197, vitest 29); `scripts/e2e.sh` 32/32.

## Risks
- Item/material drops are pending until inventory (Phase 16); XP/gold calibration to be reviewed by the
  Phase 25 simulator.
