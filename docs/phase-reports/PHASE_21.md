# Phase 21 — Party, Support Roles, Group AFK

## Delivered
- `balance/party.yaml` + `app/game_engine/party.py`: max size 5 (config), invite TTL, online window, chat
  limits, per-class allowed roles (no fake tank/healer), capped composition bonuses (max 2, small %),
  enemy power +60% per extra member.
- Migration `0017_party`: parties, party_members (one party per character), party_invites (partial unique
  pending), party_messages (idempotent client key), `afk_sessions.group_id`.
- `app/services/party.py` + `app/api/party.py`: create, invite by name (one character per account, full
  check under party row lock), accept/decline/expiry, leave (leadership passes to longest member; empty party
  disbands), kick/promote (leader only, 403 otherwise), role change, view with online (auth activity) and AFK
  state, minimal chat (NFC, control chars stripped, length cap, after-id polling).
- Group AFK (`POST /characters/{id}/party/afk`, leader only, idempotent): every member gets an own
  `AfkSession` whose snapshot freezes their stats + allies' snapshots (Solo Accord off via party size),
  composition bonus effects, shared fight seed and a personal loot salt. Leaving/joining never alters
  running sessions (snapshot hash test).
- Combat core: shields credit `damage_prevented` to the caster; `ally_buff_uptime_s` tracked. AFK samples run
  the full party; result `contribution.per_fight` = damage, healing, shields, damage prevented, ally buff
  uptime, debuffs and **party DPS gained** (counterfactual fight without the member). Solo/legacy sessions
  are unchanged (fields only added for party snapshots); combat golden digests re-baselined for new fields
  only (math verified identical).
- Frontend: party screen (invites, members with role/online/AFK, composition, leader controls, group AFK
  start, chat) and contribution block in the AFK claim summary; 4 locales.

## Tests
- `tests/test_party.py` (5): bonuses cap, lifecycle/roles/limits/leadership/same-account, invite expiry and
  decline, chat contract, group AFK snapshots/seed/salt/leave-immutability/contribution.
- Unit `party-screen.test.tsx` (2); E2E party create + chat. Gate: pytest 258, vitest 43, build; E2E 44.

## Risks
- Party chat is poll-based (10 s); push transport can replace it behind the same contract.
- Counterfactual DPS doubles sample fights for group sessions only (bounded by `sample_fights`).
