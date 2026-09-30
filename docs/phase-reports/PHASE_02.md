# PHASE 02 — Localization core (en / tr / zh-CN / es)
Status: complete

## Done
- DB: `localization_keys` (key unique, namespace, context, max_length, soft delete) + `localization_values`
  (unique `(key_id, locale)`, locale/status CHECKs, optimistic `version` via SQLAlchemy version_id_col,
  `updated_by`, timestamps). Migration `0002`.
- `app/localization/locales.py`: canonical locale set, Accept-Language parsing (q-weights, zh-* → zh-CN),
  NFC normalization + control-char stripping, safe internal label from key.
- `app/localization/service.py`: one-query bulk resolution with fallback selected → en → safe label;
  admin all-locale view; `set_value` with optimistic concurrency (409 `version_conflict` + current value);
  idempotent `seed_values` never overwriting reviewed/published; per-locale completeness stats.
- API: `GET /api/v1/i18n/locales`, `GET /api/v1/i18n/texts?keys=` (max 200 keys),
  `PUT /api/v1/i18n/preference` (cookie). Locale dependency: `?locale` (invalid → 422) → cookie → Accept-Language → en.
- Seed pipeline: `app/content/seed.py` + `scripts/seed.py` (idempotent), stat names/short/descriptions in 4 locales.
- Frontend: 60+ static UI keys × 4 catalogs (en fallback merge), header `LanguageSwitcher` (cookie + API, `router.refresh`),
  reusable accessible `LocalizedFieldEditor` (tabs, arrow keys, missing badges, status, fallback preview, NFC).
  CJK-friendly font stack + `overflow-wrap:anywhere`.
- ADR-0003 addendum: player-visible statuses include `draft`; seeds don't overwrite reviewed/published.

## Deferred (explicit)
- Admin localization endpoints need RBAC → wired in Phase 03 (service functions ready and tested).

## Gate
ruff/format/mypy strict · pytest 16 (fallback, invalid locale, missing translation, concurrency, seed protection,
cookie/header resolution) · drift none · eslint/tsc · vitest 13 · next build · Playwright 18 (locale switch
persistence over reload for all 4 locales, Accept-Language, no horizontal overflow zh-CN/tr/es, desktop+mobile).
