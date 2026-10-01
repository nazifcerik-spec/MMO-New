# Phase 23 — Player UI, Text-MMO Experience, PWA

## Delivered
- Game shell (`features/shell/game-shell.tsx`, layout for `/game/characters/[id]/*`): identity bar (name,
  selected title with status rarity, class title, level/XP bar, gold, unspent points, AFK state), desktop
  side nav (Character, Adventure, AFK, Inventory, Equipment, Skills/Talents, Class, Professions, Crafting,
  Market, Party, Collections, Settings) with `aria-current`, center context, right column (next goals +
  activity log); mobile bottom nav + "More" drawer (dialog, Escape/backdrop close, focus restore).
- Backend `GET /characters/{id}/summary` (identity/resources/AFK + **next meaningful goals**: AFK claim,
  stat/talent points, class stage, level title, item tier, zone unlock, profession rank) and
  `GET /characters/{id}/activity` (feed from claimed AFK, crafts, quests, achievements, trades, profession
  level-ups — no new write path).
- Readable text logs: activity sentences with visual hierarchy (level-up, rare drops, achievement rarity),
  summary-first + expand; combat preview returns a structured `sample_log` rendered by `CombatLog`
  (summary counts, localized per-event lines with ICU `select` for "You hit / Wolf hits", crit/block/proc/
  death styles).
- AFK screen = session start (zone, risk, duration ≤3 h) + profile (stance, target priority, potion
  threshold, loot filter, passive rules / active tactics) + preview with log.
- PWA: `manifest.webmanifest`, generated PNG icons, `sw.js` (static cache-first; pages & GET API
  network-first with last-good fallback; never caches/replays non-GET; auth/admin bypass), `/offline` page,
  production SW registration. Offline = read-only: banner + `apiFetch` refuses mutations locally.
- Settings page (language, reduced-motion override, sign out); skip link; focus-visible; reduced motion
  (OS + user); contrast tokens fixed (light `legendary`, new `bronze`) after axe findings.
- 4 locales for all new strings.

## Tests
- Backend `tests/test_overview.py` (3). Unit `game-shell.test.tsx` (4: identity/nav/goals/activity, drawer,
  offline banner, combat log). E2E `shell.spec.ts` (shell desktop/mobile, AFK screen + log, skip link, PWA,
  offline read-only, CJK/TR/ES no-overflow on 8 game screens) and `a11y.spec.ts` (axe WCAG 2.1 AA, 8 screens).
- Gate: pytest 267, vitest 49, build; E2E 64 passed (desktop + mobile).

## Risks
- Offline cache holds only previously visited GET responses; it is intentionally read-only.
