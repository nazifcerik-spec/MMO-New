# ADR-0003 — Localization architecture
Status: Accepted (Phase 00)

## Decision
Locales exactly `en`, `tr`, `zh-CN`, `es`; English canonical.
1. Static UI text: frontend message catalogs (`frontend/messages/<locale>.json`) via next-intl; no hardcoded UI strings.
2. Dynamic game content: DB `localization_keys` + `localization_values(key, locale, value, status, version)`,
   unique `(key_id, locale)`; status `missing|draft|reviewed|published`.
Content rows store only translation keys (`name_key`, `description_key`), never display strings.
Resolution: explicit `locale` query param → cookie `locale` → `Accept-Language` → `en`.
Fallback per key: selected locale (published/reviewed) → `en` → safe internal label derived from code.
All text NFC-normalized on write. Admin APIs return all locales; player APIs return resolved values.

## Consequences
Bulk resolution per request (one query per key batch; no N+1). Admin editors use one reusable
`LocalizedFieldEditor`. Machine-seeded non-English values start as `draft`.

## Addendum (Phase 02)
- Player-visible statuses: `draft`, `reviewed`, `published` (non-empty). `missing` (or empty) forces fallback.
  Drafts stay visible so seeded content is playable in all four locales while QA is tracked in admin.
- Seeds never overwrite a value whose status is `reviewed`/`published` unless explicitly forced.
- Locale resolution for API calls: `?locale=` (invalid → 422) → cookie `locale` (invalid ignored) →
  `Accept-Language` → `en`. Logged-in users' saved preference is synced into the cookie by the frontend.
