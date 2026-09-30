# PHASE 00 — Contract & architecture decisions
Status: complete

## Done
- `CLAUDE.md` (user-provided) kept as the project contract; not rewritten.
- `docs/game-design/CANONICAL_RULES.md`: codable canonical facts extracted from GDD v1.0 (caps, stats/soft caps,
  titles, 8 races, 10 classes → 20 paths → 40 specs, talent trees/capstones, professions + Lv200 specs + titles,
  tiers/rarity/affix budgets/requirement profiles, AFK/risk/efficiency rules, locales). Stable English codes defined.
- ADRs in `docs/architecture/`: 0001 monorepo/boundaries, 0002 deterministic AFK, 0003 localization,
  0004 item template vs instance, 0005 effect registry DSL, 0006 server-authoritative economy.
- Folders: `docs/phase-reports`, `docs/decisions`, `docs/game-design`.
- No gameplay code written.

## Decisions
- Environment is an ephemeral cloud container: each phase is committed and pushed to the working branch after
  its gate passes (otherwise work would be lost), in place of leaving changes uncommitted.
- Local PostgreSQL 16 + Redis used for tests; Docker daemon not available in this container (compose file
  still delivered in Phase 01, validated by config lint).

## Risks for next phases
- XP curve must hit ~968 h total; needs a parameterized curve + calibration test.
- 1,520 item catalog generation must remain validator-clean (Phase 19).
- Scope is very large; each phase keeps minimal but real, tested implementations.
