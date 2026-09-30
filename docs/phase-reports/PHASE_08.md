# PHASE 08 — Skills, passives, talents, awakening engine
Status: complete

## Done
- Models (migration `0008`): `ability_definitions` (types ACTIVE/PASSIVE/ULTIMATE/STANCE/AURA/PROC; owner
  class/branch/spec/global; unlock level; target rule; tags; `ranks` = AbilityRank list with cost/cooldown/
  cast time/AbilityEffects; `trigger` = PassiveTrigger class), `talent_trees`, `talent_nodes` (tier, max rank,
  required tree points, level, capstone flag, `requires` = TalentEdges, per-rank effects), `awakening_definitions`
  (1 per specialization), `mastery_definitions` (1 per class, Lv1000 small horizontal bonus + cosmetic),
  `character_talent_allocations`; class progression gets talent reset counters + points spent (optimistic version).
- Canonical data: 95 abilities (per class 5 actives + 1 ultimate + core passives from GDD §06–07), 30 trees with
  canonical names/capstones (Defense/Arms/Blood … Totem/Ancestor/Element), 300 nodes built deterministically
  from a shared layout (`balance/talents.yaml`) + per-tree focus, 40 awakenings, 10 masteries; all 4 locales.
- Pure engine `game_engine/talents.py`: point schedule (45 by Lv978, 25/tree), allocation validation (rank
  bounds, budget, tree cap, tier gating by lower-tier points, prerequisites, Lv850 capstone, ≤1 capstone),
  tree-graph validation (circular dependency, missing/foreign prerequisite, unreachable node, duplicate
  capstone, capstone rule, capacity), per-rank effect scaling, reset quote (free <300, gold 300–599,
  gold + rare material 600+).
- Validators (content publish): effect params, owners, ≤5 core actives + ≤1 ultimate per specialization
  (`ability_limits` config), 3 trees/class, node graph rules. No specialization-name branching anywhere.
- Services/APIs: `GET/POST /characters/{id}/talents` (add-only plan, optimistic version), `POST .../talents/reset`
  (Idempotency-Key, gold via ledger, material via inventory consumer hook — rejected with
  `material_system_unavailable` until inventory lands in Phase 16), `GET /characters/{id}/abilities` (+awakening).
  Talent, awakening and mastery effects feed the stat calculator (sources `talent`/`class`).
- UI: talent page (3 trees, tiers, capstone styling, rank +, lock hints, points, reset quote), ability list
  with localized effect text on the class page.

## Gate
ruff/format/mypy · pytest 128 (budget, allocation & graph rules, 30 trees/30 capstones canonical, spec kit limits,
allocation flow incl. tier lock/409/decrease/tree cap/second capstone, Lv850 capstone gate, reset costs, abilities +
awakening localized, admin publish validation: cycle/duplicate capstone/invalid effect/6th active, full 4-locale
completeness of class content) · drift none · eslint/tsc · vitest 20 · build · Playwright 26 (talent learned via UI).

## Notes
- Rare-material talent resets (Lv600+) become payable once inventory consumers register (Phase 16).
