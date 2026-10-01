# Phase 24 — General Admin Content Studio

## Delivered
- `/admin/content`: module home (races, classes/branches/specs, skills/passives, talents, professions, world:
  zones/enemies/bosses/encounters, drop tables, recipes, quests, achievements, items → Item Studio, balance)
  with per-status counts, pending drafts and permissions (`GET /admin/content/modules`).
- Generic list (search/status/paging/create) and editor for every registered content type: JSON data with
  server validation, localization tab (reuses `LocalizedFieldEditor` + localization API), workflow,
  dependencies, history (diff to current, rollback via new revision).
- Workflow Draft → Validation → Review → Published → Archived: `content_reviews` (migration 0019) bound to
  (base revision, edit version) so edits invalidate approvals; four-eyes approve/reject with notes;
  `MMO_CONTENT_REVIEW_REQUIRED` enforces approved reviews on API publish (seeds unaffected).
- Dependency graph (`services/content/references.py`): field-driven reference extraction across all types
  (published + drafts); `GET …/references` (incoming by type + outgoing). Referenced content cannot be
  hard-deleted (409 `referenced`); archive/disable of referenced content needs explicit acknowledgement.
- Publish bundle: `GET /admin/content/pending` + bundle page publishing selected drafts atomically under one
  release (existing release mechanism).
- Localization dashboard `/admin/localization`: per-locale present/reviewed %, missing/draft/reviewed/
  published, namespace filter, missing-key worklist, JSON/CSV export (formula-injection safe), validated
  import with dry run that never overwrites reviewed/published text unless a reviewer asks.
- Audit records for review request/decision, imports, publishes (existing).

## Tests
- `tests/test_content_studio.py` (5): reference extraction, modules + graph + RBAC, delete/archive
  protection, four-eyes review + stale approval + atomic bundle, localization dashboard/export/import.
- Unit `content-studio.test.tsx` (3); E2E `content-studio.spec.ts` (2, desktop).
- Gate: pytest 272, vitest 52, build; E2E 67 passed.

## Risks
- Reference discovery is field-name based; new reference fields must use the shared names (documented in
  `FIELD_TARGETS`).
