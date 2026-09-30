# PHASE 06 — Race system and 8 launch races
Status: complete

## Done
- `races` content table (ContentMixin + sort_order, identity, trait/title l10n keys, informational affinity,
  validated effects JSON); `characters.race_id` FK. Migration `0006`. Registered as content type `race`
  (drafts, publish, history, rollback via Phase 04 backbone).
- Canonical data `content/data/races/races.yaml`: Human/Adaptable/Diplomat … Revenant/Undying Will/Deathless,
  effects expressed only through the effect registry (STAT_PERCENT/FLAT, THRESHOLD_TRIGGER→DAMAGE_MULTIPLIER,
  HEAL_MULTIPLIER hot, LOOT_MODIFIER xp, PROGRESSION_MODIFIER respec_cost/death_penalty, PROFESSION_YIELD_MOD).
  Names, descriptions, traits, trait text and race titles in en/tr/zh-CN/es.
- Racial balance validator (`game_engine/race_balance.py`, config `race_balance`): estimates combat advantage
  (condition uptime weighting, non-combat effects excluded); >5% warning (publish needs acknowledgement),
  >7% error. Canonical races score 0–4.5%.
- No race-specific code paths: providers feed racial STAT effects into the stat calculator (breakdown source
  `race`) and the Human respec discount into the respec quote. Provider registration centralized in
  `services/plugins.py`.
- APIs: `GET /content/races` (localized cards + stat labels), character options now list the 8 races.
- UI: wizard race step with localized cards (trait, race title, effect summary, informational affinity,
  "any race can play any class"); reusable `EffectList`/`useEffectText` rendering structured effects in 4 locales.

## Gate
ruff/format/mypy · pytest 101 (exactly 8 canonical races/traits/titles, 4-locale names, no class lock,
racial breakdown in stats, Human discount, validator warning/ack/error + invalid effect, canonical races
clean) · drift none · eslint/tsc · vitest 18 · build · Playwright 24 (wizard shows 8 localized race cards).
