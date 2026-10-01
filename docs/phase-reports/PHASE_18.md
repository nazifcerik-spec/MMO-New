# Phase 18 — Gathering, Crafting, Recipes, Quality, Enchanting

## Delivered
- Content types (validated, revisioned, localized): `gathering_node`, `recipe`, `imbue` (`app/services/content/types/crafting.py`); sample content `app/content/data/professions/crafting_content.yaml` (14 materials, 14 nodes matching zone nodes, 7 recipes incl. scroll-unlocked, 2 imbues, gadgets).
- Balance: `balance/crafting.yaml` (queue 2 jobs, batch ≤50, failure XP 25%, gathering/salvage/enchanting costs, workstations); `afk.yaml` `loot_modifier_caps`; `item_rules.yaml` `quality_stat_bonus_pct`.
- Migration `0015_crafting` — nodes, recipes, imbues, character_recipes, craft_jobs (start/claim keys, recipe snapshot, seed), enchant_events ledger, `item_instances.enchantments`.
- Engine `app/game_engine/crafting.py`: fail chance, deterministic batch resolution (quality per unit, partial ingredient return), aggregated gathering over AFK efficiency segments, reroll/salvage rolls.
- Service `app/services/crafting.py` + API `app/api/crafting.py`:
  - recipe list (known/level/tool/workstation/material counts/max craftable), scroll learning;
  - craft start consumes materials under row locks (idempotent on key), cancel refunds, exactly-once claim from snapshot+seed, profession XP;
  - AFK gathering = profession task on the shared 3h AFK session (validator + resolver hooks), `material_yield` gadget mods capped;
  - enchanting: safe reroll inside tier band (never destroys), single imbue slot, salvage (template + loot-filter handler), all in `enchant_events` with seed/before/after/cost, idempotent.
- Quality (common→mythic_crafted) is an instance property separate from rarity; scales base stats.
- AFK: `LOOT_MODIFIER` gadgets (xp/gold/drop/rare) applied with per-scope caps; profession sessions skip combat.
- Frontend: crafting panel (recipes, batch qty, server-timed queue with claim/cancel), gathering panel (AFK node start), inventory enchant/imbue/salvage/learn actions, quality + imbue in tooltip; EN/TR/ZH-CN/ES strings.

## Tests
- `tests/test_crafting.py` (8): determinism, loot-mod caps, reservation + idempotent claim, cancel refund/queue limit/ownership, scroll learning, quality vs rarity, AFK gathering + replay, enchant ledger.
- Gate: ruff/mypy, pytest 235, migrations, vitest 40, build — green. E2E 40 passed (crafting flow added).

## Risks / follow-ups
- Workstations are global (no housing/city gating yet).
- Launch-scale recipe catalog arrives with Phase 19 item generation.
