# CLAUDE.md — Oldschool AFK Text MMORPG

## 1. Purpose
Build the MMORPG defined by this repository autonomously, phase-by-phase, with minimal conversation and minimal token waste.
Priorities: correctness, deterministic game logic, security, data integrity, testability, localization, maintainability.

## 2. Source of Truth
Use this precedence:
1. `CLAUDE.md` — workflow/architecture/quality rules.
2. `docs/game-design/CANONICAL_RULES.md` — canonical gameplay facts after created.
3. `Claude_Code_AFK_Text_MMO_Faz_Promptlari.md` — phase scope and acceptance criteria.
4. `docs/design/Oldschool_AFK_Text_MMO_Game_Design.pdf` — original design reference.
5. ADRs and existing tests/code.

Rules:
- After `CANONICAL_RULES.md` exists, do not reread the full PDF unless a required fact is missing or conflicting.
- Do not duplicate large design documents.
- Do not silently change canonical game rules.
- This file overrides any phase-plan wording that says the user must manually approve or send each next phase.

## 3. Autonomous Phase Execution — No Approval Between Phases
Once implementation starts, execute all mandatory phases automatically.

Never ask:
- “Should I continue?”
- “Do you want me to start the next phase?”
- “Can I proceed?”
- approval for normal reversible repository changes required by the plan.

For each mandatory phase:
1. Read `.claude/state.json` and determine the first incomplete phase.
2. Read only that phase section plus directly necessary shared rules from the phase-plan file.
3. Inspect only relevant existing code/files.
4. Implement the complete phase.
5. Run targeted tests while working.
6. Run the phase quality gate.
7. Fix failures without asking the user to debug routine problems.
8. Write/update `docs/phase-reports/PHASE_XX.md` concisely.
9. Update `.claude/state.json` atomically.
10. Immediately begin the next mandatory phase.

Do not stop merely because a phase finished.

Optional phases:
- Skip without asking by default.
- Run automatically only if `.claude/state.json` has `"run_optional_phases": true` or the user explicitly requested that optional feature.

Only stop for genuinely blocking external input, e.g.:
- required external credential cannot be generated locally;
- irreversible destructive operation would affect non-development/user-owned data;
- canonical requirements directly conflict in a way that materially changes saved/public behavior;
- a mandatory external paid/account choice has no safe local/default option.

For ordinary ambiguity: inspect existing patterns -> choose the safest reversible sensible default -> record a material decision if needed -> continue.

## 4. Token / Conversation Discipline
Implementation is more important than narration.

Do:
- be terse;
- use targeted search/grep/read;
- edit minimal relevant files;
- reuse existing abstractions;
- persist decisions in repository files;
- use targeted tests during development and full gates only at phase end.

Do not:
- repeat requirements already stored in repository docs;
- repeatedly explain architecture;
- print full source files or full successful test logs;
- reread every ADR or the full PDF each phase;
- produce long plans/recaps for routine work;
- list every changed file after every small edit;
- create decorative docs not needed by development;
- ask minor naming/style/library questions.

Chat limits:
- routine progress: 1–3 short lines only when useful;
- phase boundary: at most one short line, then continue;
- final report: preferably <=12 bullets and <=500 words.

## 5. Persistent State
Create `.claude/state.json` if absent:

```json
{
  "project": "oldschool-afk-text-mmorpg",
  "current_phase": "00",
  "completed_phases": [],
  "skipped_optional_phases": [],
  "run_optional_phases": false,
  "last_quality_gate": null,
  "last_updated_utc": null,
  "blocking_issue": null
}
```

Rules:
- Never mark a phase complete while its required gate is failing.
- Resume from state after interruption instead of asking where to continue.
- If state conflicts with repository evidence, verify and repair conservatively.
- Keep phase reports compact (~40 lines preferred).

Durable docs:
- `docs/game-design/CANONICAL_RULES.md` — game facts only.
- `docs/architecture/ADR-*.md` / `docs/decisions/ADR-*.md` — only material decisions.
- `docs/phase-reports/PHASE_XX.md` — concise result, tests, risks.

## 6. Fixed Stack
Unless explicitly changed by the user:

Backend:
- Python 3.12+
- FastAPI
- SQLAlchemy 2 async
- Alembic
- Pydantic
- PostgreSQL
- Redis

Frontend:
- current stable Next.js App Router
- TypeScript
- Tailwind CSS
- accessible headless-component approach
- TanStack Query
- minimal client-only state

Testing/runtime:
- pytest + backend integration tests
- frontend unit/component tests
- Playwright E2E
- Docker Compose for local postgres/redis/backend/frontend
- OpenAPI; generated/reused frontend API types where practical
- server timestamps UTC

Do not replace the stack merely from preference.

## 7. Non-Negotiable Engineering Rules
### Server authority
Server is authoritative for XP, levels, stats, combat, AFK results, loot, currency, crafting, profession gains, market transactions, rewards and item grants.
Never trust client-computed outcomes.

### Data-driven game content
Classes, promotions, specializations, races, professions, skills, passives, talents, items, tiers, rarities, affixes, sets, recipes, enemies, zones, loot tables, titles, balance values and dynamic localization should be data-driven where practical.
Avoid long content-specific `if/else` or `switch` chains.

### Safe effect system
Use controlled `effect_type + schema_version + validated params` registry/DSL.
Never execute arbitrary Python/JS/SQL/shell/admin code from content data.

### Database
- every schema change requires Alembic migration;
- use constraints/FKs/indexes appropriately;
- prefer soft-delete/version/history for player/economy/published content;
- use optimistic versioning where concurrent content/economy edits matter.

### Idempotency
Critical actions must tolerate retries without duplication: AFK claim, reward claim, crafting claim, market purchase, item grant, profession reward, currency transfer.

### Determinism
Use reproducible calculations where audit/replay matters.
Prefer integer/fixed/exact numeric for economy-critical values.
Record RNG seeds for deterministic simulations when needed.

### Time
Use timezone-aware UTC server timestamps. Never trust client clocks for authoritative timers.

## 8. AFK Engine
Maximum single AFK session: 3 hours.

Never run a real combat worker/loop for the whole AFK duration.
At session start persist sufficient immutable/snapshotted data, e.g. build/content versions, stats, equipment/talents, strategy, zone/enemy pool, start/end, deterministic RNG seed and balance version.
Resolve efficiently at claim/end using deterministic/aggregated simulation.

Requirements:
- no double claim;
- old sessions should not change when live balance changes;
- replay/debug should be possible from recorded inputs where practical;
- AFK death causes configured friction/recovery/durability cost, not deletion of hours of progress;
- support classes remain solo-viable through canonical solo-support conversion;
- avoid millions of per-second simulated ticks when mathematically equivalent aggregation exists.

## 9. Localization
Supported locales are exactly:
- `en`
- `tr`
- `zh-CN`
- `es`

Rules:
- English is canonical internal naming language.
- Stable internal IDs/codes/slugs are English and immutable.
- Static UI text uses frontend i18n resources.
- Dynamic game content uses DB-backed localization keys/values.
- Fallback: selected locale -> `en` -> safe internal label.
- All relevant admin editors expose EN/TR/ZH-CN/ES fields through reusable localized components.
- Validate CJK layout, Unicode normalization, search and longer translated strings.
- Do not overwrite reviewed/published translations casually.

## 10. Canonical Game Invariants
After Phase 00, read exact names/graphs/values from `CANONICAL_RULES.md` rather than duplicating them here.
Preserve at minimum:
- character cap 1000;
- profession cap 500;
- class breakpoints 100 / 300 / 600 / 850 / 1000;
- 10 base classes, 40 final Lv300 specializations;
- 8 races;
- 15 priority professions;
- 3 talent trees/class, 45 total points, max 25/tree, Lv850 capstone;
- max 3 active specialist profession licenses;
- stats `STR DEX INT VIT WIS SPI LUK`;
- item tiers T0–T10;
- launch target 1,520+ functional items;
- passive-first combat + optional active tactics;
- post-Lv1000 primarily horizontal progression.

## 11. Active and Passive Combat Must Share One Core
Support both scenarios without building unrelated engines.

Active abilities may use costs, cooldowns, targeting, cast time and tactic priorities.
Passive-only combat may use passives, procs, stances, auras, thresholds, every-N-hit, on-kill/on-crit/on-block/on-dodge/on-heal triggers.

Share the same stats, effects, ability definitions, triggers, logs, balance content and simulation primitives.

## 12. Item Architecture
Separate item template/content definition from player-owned item instance.

Templates may define localized identity, category, tier, rarity, level/stat/class requirements, weapon/armor family, base stats, effects, affix pools, sockets, sets, unique effects, durability, upgrades, trade/bind rules, vendor/salvage values, drop/source and recipe/profession links.

Instances may define owner/location, template/version reference, rolled affixes/values, durability, upgrade level, sockets/gems, bind state and provenance.

Published template edits must not silently reinterpret historical instances.

## 13. Admin Item Studio
Treat Item Studio as a real game-design tool, not a debug form.
Required areas:
- General
- Localization
- Requirements
- Stats & Effects
- Affixes
- Unique / Set
- Sockets / Upgrade
- Sources
- Craft / Salvage
- Preview
- History

Required capabilities:
- create/edit/duplicate/archive/disable/publish;
- safe revision comparison/history and rollback via new revision;
- search/filter/sort and safe bulk edit;
- EN/TR/ZH-CN/ES fields + translation completeness;
- tier/rarity/category/class tags;
- level/stat requirements;
- base stats + validated effect registry editor;
- affix/set/socket/upgrade/drop/recipe/profession/salvage links;
- validated JSON/CSV import/export;
- RBAC + audit history;
- representative character preview with requirement pass/fail and derived-stat deltas;
- controlled batch Item Generator Wizard.

Generated items are drafts and must pass validation before publish. Never bypass validation merely to reach the 1,520-item target.

## 14. Admin / RBAC / Audit
Roles may include: `player`, `support_agent`, `translator`, `item_editor`, `game_designer`, `admin`, `superadmin`.

Rules:
- deny by default;
- authorization is server-side; UI hiding is not security;
- publish/economy/item-grant/role/destructive actions require permissions;
- meaningful admin changes create audit records with actor/action/entity/time and useful version/diff metadata;
- no arbitrary DB console through admin UI.

## 15. Profession Rules
Profession data is localized and data-driven.
Preserve canonical 15 professions and cap 500.
Support progression/ranks, gathering/crafting/service categories, recipes, tools, materials, yield/quality modifiers, specialization, profession effects, specialist-license limits, respec/relicense policy and AFK-compatible profession sessions where designed.
Recipes reference item templates/versions rather than duplicating item definitions.

## 16. Security
Never:
- commit/log secrets;
- trust client prices/rewards/XP/combat/timers;
- concatenate input into SQL;
- disable auth/RBAC to make tests pass;
- expose production stack traces;
- execute content-provided arbitrary code;
- run destructive commands outside intended development scope.

Use secure password/session/token handling, CSRF protection where applicable, validation, rate limiting, parameterized ORM/query patterns, least privilege, structured logs and correlation IDs.

## 17. Performance
Avoid obvious scale traps:
- N+1 queries;
- per-second AFK workers;
- unbounded table scans/list endpoints;
- full inventory/market/catalog loading without pagination;
- frontend request waterfalls;
- enormous tick-by-tick AFK logs;
- unnecessary distributed complexity.

Use indexes, pagination/cursors, batching, aggregate AFK math, cache/locks where justified, and cached published content snapshots where useful.

## 18. Testing / Quality Gate
During work run the smallest relevant tests first.
At phase end run all checks required by that phase, including as applicable:
- backend lint/format/static checks;
- pytest unit/integration;
- frontend lint/typecheck/unit/component;
- production build;
- relevant Playwright E2E;
- migration from clean DB.

Do not skip/disable valid tests merely to obtain green output.
Prioritize invariant tests: caps, stat rules, promotions, exactly 40 specializations, talent limits, tier gates, localization fallback, AFK 3h limit/determinism/double-claim prevention, economy idempotency, admin validation and RBAC denial paths.

A phase is complete only when required scope + migrations/seeds + localization/security obligations + tests/build/gate + concise phase report + state update are complete.

## 19. Migration / Seed Discipline
- DB must build reproducibly from empty state.
- Seeds should be idempotent where practical.
- Separate demo/dev seeds from canonical launch content.
- Stable canonical entities use stable internal codes.
- Large item generation should be reproducible from configuration/seed when needed.
- Published IDs/codes must not randomly change on reseed.

## 20. Decision Rules — Do Not Ask About Routine Choices
When several valid implementations exist, prefer in this order:
1. consistency with existing architecture;
2. secure default;
3. deterministic/reproducible behavior;
4. reversible decision;
5. data-driven balance/content;
6. mature dependency already used by project;
7. fewer dependencies;
8. simpler operational complexity.

Record only material decisions as ADRs, then continue.

## 21. Dependency / Git Discipline
Before adding a dependency, verify an equivalent is not already present. Avoid abandoned or duplicate-purpose packages. Do not perform unrelated major upgrades during gameplay phases.

Git:
- never rewrite shared history or force-push;
- never discard unrelated user work;
- do not ask whether to commit;
- if `AUTO_COMMIT_PHASES=1`, commit once after each successful phase gate;
- otherwise leave changes uncommitted and continue.

## 22. Failure Handling
On routine command/test failure:
1. inspect;
2. fix root cause;
3. rerun the smallest useful test;
4. rerun phase gate when stable;
5. continue.

Do not ask the user to debug ordinary code failures.
For unavailable external dependencies, preserve the production contract, use a safe local test double only when appropriate, record the blocker once and continue unaffected work.

## 23. Completion Behavior
After the final mandatory phase:
- run final regression/build gate;
- mark project state completed;
- create one concise final report containing completed phases, skipped optional phases, test/build status, local run commands, deployment prerequisites and genuine remaining risks;
- stop.

Do not invent extra phases or ask whether to continue after the defined plan is complete.

## 24. Startup Directive
On first implementation run:
1. read this file;
2. inspect repository structure;
3. locate the phase-plan file and design PDF;
4. load/create `.claude/state.json`;
5. determine first incomplete mandatory phase;
6. execute it;
7. continue automatically through mandatory phases after green quality gates.

Do not request the user to paste phases one-by-one.
Do not request phase-transition approval.
Do not spend tokens explaining this procedure; perform it.

### Compact rule
Routine uncertainty: **inspect -> safe default -> implement -> test -> record material decision -> continue.**
Phase complete: **green gate -> concise report -> state update -> next phase.**
Never replace this with **ask -> wait -> ask again**.
