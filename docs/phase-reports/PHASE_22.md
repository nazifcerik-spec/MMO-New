# Phase 22 — Quests, Promotion Challenges, Titles, Achievements, Prestige

## Delivered
- Content types `quest` (graph via prerequisites, validated acyclic + references; types kill/collect/
  profession/explore/boss/promotion/tutorial; objectives kill/boss/explore/collect/profession/level/action;
  rewards xp/gold/items/title) and `achievement` (counter + threshold + status rarity + points + title).
- Migration `0018_goals`: quests, achievements, character_quests (accepted revision pinned), character_counters,
  character_achievements, character_title_selection.
- `balance/goals.yaml`: promotion quest requirement per stage (default: level alone sufficient), default
  promotion trials, status-rarity mapping (level ladder, class stage Base→Branch→Spec→Awakened→Ascendant→
  Eternal, race, profession, quest), prestige ranks from achievement points + post-cap mastery XP.
- Event bus `app/services/events.py`: one aggregated event per AFK claim / craft claim / trade / equip /
  AFK start / level-up / profession level — no per-combat-event DB writes. `goals.on_event` updates counters
  (upsert add / greatest) and active quest progress; achievements unlock on threshold and award titles.
- Promotion gates: `classes.QUEST_GATE_CHECKS` now async; class `required_quest_code` or config-required
  trial must be claimed. Zone `quest` requirements resolved via `world.QUEST_PROVIDERS`.
- Titles: level ladder, generic class title, race epithet, profession/achievement/quest titles, guild-rank
  extension provider; selection validated server-side; rarity is presentation only.
- Collections: cosmetic/collectible templates ever obtained (provenance), grouped by family.
- API `/characters/{id}/quests|achievements|titles|collections`; Journal UI (quests with objective progress,
  achievements + prestige, title picker, collections); 4 locales; starter content in `goals/goals.yaml`.

## Tests
- `tests/test_goals.py` (6): rules (cycle/progress/rarity/prestige), graph cycle rejection, tutorial chain
  from aggregated events + idempotent claim, collect consumption + repeatable + profession seeding,
  achievements → titles → selection, config-required promotion trial.
- Unit `goals-screen.test.tsx` (2); E2E journal. Gate: pytest 264, vitest 45, build; E2E 46.

## Risks
- Quest objective events cover AFK/craft/trade/equip/level/profession; new systems must emit to count.
