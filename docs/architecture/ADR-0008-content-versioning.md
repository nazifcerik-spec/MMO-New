# ADR-0008 — Content lifecycle and versioning
Status: Accepted (Phase 04)

## Decision
- Every content table uses `ContentMixin`: immutable `code`, `name_key`/`description_key` (DB localization),
  `status` draft|published|disabled|archived, optimistic `version`, `revision_no`, created_by/updated_by,
  `published_at`, soft delete.
- Typed rows hold the **live** state (fast relational reads for players). Edits to a published entity go to
  `content_drafts` (one pending draft per entity, optimistic version) and never touch live data until publish.
  Never-published entities are edited in place (status `draft`, invisible to players).
- Publish (single or **bundle**) validates schema + registered validators (errors block; warnings need explicit
  acknowledgement), then atomically: allocates a global `content_releases.version_no` (advisory lock), applies
  data, writes an immutable `content_revisions` snapshot (JSON + SHA-256 hash), audits.
- Status changes also create a release + revision. Rollback copies an old revision's data into a draft and
  publishes it as a new revision (history never rewritten). Published content cannot be deleted, only archived.
- AFK/combat snapshots record the release version and embed the resolved values they use, so replays never
  depend on live rows (ADR-0002).
- Player APIs read only `status='published'` rows; admin APIs (`/admin/content/{type}`) see drafts.
- New content types register a `ContentType` (model, data schema, validators, permissions) — no per-type CRUD code.
