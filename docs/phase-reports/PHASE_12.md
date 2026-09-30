# Phase 12 — Zones, Enemies, Encounters, Bosses, Drop Sources

## Result
- Migration 0010: `zone_tiers`, `zones`, `enemy_templates`, `enemy_ability_profiles`, `encounter_templates`,
  `boss_templates`, `drop_tables` (ContentMixin; FKs on codes; CHECKs for levels/danger/boss chance/ranks).
- Zones: recommended/min/max level, danger 1–10, environment tags, profession nodes, weighted encounter pool,
  boss pool + boss chance, loot modifiers, drop table, requirements (min_level/zone_cleared/class_stage/quest),
  4-locale names. Risk profiles remain numeric config (`balance/risk_profiles.yaml`, 85/100/120/135 + rare bonus).
- Separate scaling configs: `balance/enemy_scaling.yaml` (per level, ranks, archetypes, sanity reference) and
  `zone_tiers.scaling`; tiers T0–T10 follow canonical level bands.
- Pure engine `game_engine/world.py`: enemy stats, boss phase/enrage effects, weighted encounter/boss rolls,
  pack rolls, drop rolls (boss_only, rare bonus), enemy ability-profile selector, immutable `ZoneBundle`.
- Publish validators: unknown/archived/unpublished references, empty encounter/boss pool, empty encounter,
  invalid level range (schema + tier bounds), circular prerequisites, unreachable zones (disabled prereq, prereq
  above max level, level requirement above max), impossible enemy stats (TTK/survival/dodge-cap warnings),
  damage types, ability-profile rule references.
- Sample world (dev/test, not final content): 11 zones (one per tier), 33 enemies, 11 bosses, 33 encounters,
  4 ability profiles, 22 drop tables — expanded idempotently from `world/sample_world.yaml`; zero publish warnings.
- API: `GET /zones` (cursor pagination, per-character eligibility), `GET /zones/{code}`,
  `POST /characters/{id}/zones/{code}/preview` (AFK profile vs real encounter pool, enemy ability rules).
- Frontend `/game/characters/[id]/zones`: zone list with lock reasons, detail (enemies, bosses, drops, risk
  table), zone preview; 4 locales.
- Fixes: content create now checks duplicates explicitly and maps other integrity errors to
  `constraint_violation`; `balance_probe.py` supports `--zone/--boss`; ranger default profile retargeted.
- ADR-0010.

## Tests
- `tests/test_world.py`: tier coverage + canonical risk values, separate scaling layers, deterministic
  encounters/boss adds/level clamp/bundle round-trip, drop determinism/boss_only/rare bonus, list pagination/
  eligibility/access, localized detail, zone preview, all publish validators + RBAC denial.
- Frontend unit `zone-browser.test.tsx`; E2E zone browser flow.
- Gate: `scripts/check.sh` ALL CHECKS PASSED (pytest 184, vitest 26); `scripts/e2e.sh` 30/30.

## Risks
- Tier 8+ zones are hard without gear (shadow damage vs low magic resist; mage/monk ~70–80% win, ranger ~50% at
  Lv780). Items (Phase 14/16) and the Phase 25 simulator must re-balance.
