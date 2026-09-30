# PHASE 07 — Classes, promotion, 40 specializations
Status: complete

## Done
- Models (migration `0007`): `class_resources`, `weapon_families` (28 item families), `armor_families`
  (cloth/leather/mail/plate/shield), `base_classes` (category, stat weights, main damage stat, resources,
  allowed weapon families, armor proficiencies, dual-wield, item tags, base passive effects, Solo Accord),
  `class_branches` (Lv100 PromotionPath), `specializations` (Lv300), `class_progression_requirements`
  (stage gates 100/300/600/850/1000 + optional quest, per-class override), `character_class_progressions`
  (branch/spec + promoted/specialized/awakened/capstone/mastery timestamps, path changes, optimistic version);
  `characters.base_class_id` FK. Content types with validators (effects, references, ≤2 branches/class,
  ≤2 specs/branch, supports must define Solo Accord).
- Canonical data `content/data/classes/*.yaml`: 10 classes (5 combat + 5 support), 20 paths, exactly 40
  specializations with base/Lv100/Lv300 passives and Lv600 awakenings encoded only through the effect
  registry (registry extended: BUFF, SCALING_BONUS, WEAPON_FAMILY_BONUS, RESOURCE_COST_MOD, STACK_CAP_MOD,
  SOLO_ACCORD; triggers on_resource_spent/on_crit_heal/on_ability_cast; metrics hit_index, combat_time_s,
  active_hot_count, missing_hp_pct, party_size; derived form/song/trap/aura power). Names, roles, passives,
  mastery nouns in en/tr/zh-CN/es. 12 data-driven resources (Rage … Spirit Charges).
- Solo Accord contract: `SOLO_ACCORD` effect (default 35%, source → target stats per class); combat engine
  applies it outside parties (Phases 09–10/21).
- Services: class cards, promotion (level gate, own-class branch, once), specialization (under chosen branch),
  milestone sync on level-up hook (Awakening needs a spec), generic class title chain
  Base → Branch → Spec → Awakened → Ascendant → Eternal <mastery noun> (localized patterns), class stat
  contributions + stat tokens for templates, path change policy (`class_path` config: first free, gold per
  level, cooldown) charged through the ledger. Character creation now fully content-driven (race + class).
- APIs: `GET /content/classes`, `GET /characters/{id}/class`, `POST .../class/promote|specialize|change-path`.
- UI: wizard class step (category, role, stats, resources, weapons, paths, Solo Accord), class page with
  stage timeline (locked/unlocked/completed), branch→spec tree, promotion/specialization confirmations.

## Gate
ruff/format/mypy · pytest 110 (graph == canonical, exactly 40/20/10, Solo Accord 35% on supports, localized
names, API character creation + name/class validation, early/invalid/duplicate promotion, spec before
promotion / wrong branch, title chain to "Eternal Bastion" (+tr), class stat breakdown, path change free →
cooldown, third branch/spec rejected) · drift none · eslint/tsc · vitest 18 · build ·
Playwright 26 (full create→stats→XP→allocate→promote flow on desktop+mobile).
