# PHASE 03 — Auth, RBAC, account and character shell
Status: complete

## Done
- Models + migration `0003`: users (lowercased unique email, status, lockout, 2FA extension column), user_settings,
  permissions/roles/role_permissions/user_roles, auth_sessions (token+CSRF hashes, expiry, revocation, step-up),
  audit_logs (actor/action/entity/before/after/meta/correlation id/ip, indexed), characters (level/xp/points with
  CHECKs, casefold name key unique among live rows, soft delete, optimistic version), character_settings.
  `localization_values.updated_by` → FK users.
- ADR-0007: opaque server-side cookie sessions (HttpOnly/SameSite=Lax/Secure in prod), double-submit CSRF bound to
  session + Origin check, argon2id, rate limits + temporary lockout, deny-by-default RBAC, no default credentials.
- RBAC data `content/data/system/rbac.yaml` (7 roles, 17 permissions), seeded idempotently; `require(perm)` deps;
  role grant/revoke limited to lower ranks; `player` role not revocable; all grants audited.
- APIs: `/auth/register|login|logout|me|me/settings`, `/characters` (list/create/get/delete, name-check),
  `/content/character-options` (content-driven, empty until Phases 06/07 → `content_unavailable`),
  admin: `/admin/localization/keys|completeness` (search, missing-locale/status filters, optimistic edits,
  review permission split), `/admin/users` (+roles), `/admin/audit` (keyset pagination).
- Name policy: NFKC, 3–16 letters (Unicode incl. CJK), ≤2 single separators, reserved exact/substring list, casefold uniqueness.
- `scripts.create_admin` bootstrap (password from env or prompt).
- Frontend: login/register form with localized error codes, header session state + logout, server-side guards for
  `/game` (redirect) and `/admin` (403 panel for non-staff), character list, 4-step create wizard shell
  (name check → race → class → confirm) rendering API options only. 50+ new keys × 4 locales.

## Gate
ruff/format/mypy · pytest 52 (credential/name validation, register/login/logout, CSRF + origin, lockout,
rate limit 429, settings, RBAC denial paths, rank escalation guard, translation review split, 409 conflicts,
audit entries) · drift none · eslint/tsc · vitest 13 · build · Playwright 24 (auth smoke, redirects, localized
error, wizard, player-vs-staff admin guard; desktop+mobile).

## Notes
- Behind reverse proxies set uvicorn `--forwarded-allow-ips` so rate limits see real client IPs (Phase 29 runbook).
