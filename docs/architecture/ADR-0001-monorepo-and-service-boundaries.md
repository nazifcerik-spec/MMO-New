# ADR-0001 — Monorepo and service boundaries
Status: Accepted (Phase 00)

## Decision
Single repository:
- `backend/` — one FastAPI service (modular monolith). Layers: `api` (HTTP only) → `services` (transactions,
  orchestration) → `domain` + `game_engine` (pure, HTTP/DB-free, deterministic) ; `repositories` (queries),
  `models` (SQLAlchemy), `schemas` (Pydantic I/O), `localization`, `content` (data files + loaders/validators).
- `frontend/` — Next.js App Router (player UI `/game`, admin UI `/admin`) talking only to backend REST/OpenAPI.
- `infra/` Docker/Compose/deploy, `scripts/` dev tooling, `docs/` durable docs.
- PostgreSQL = source of truth; Redis = cache, locks, rate limits (never sole guard for correctness).

## Rationale
One deployable backend keeps transactions/ledgers simple; pure engine modules stay unit-testable and replayable.
Split into services only when a measured bottleneck justifies it.

## Consequences
`game_engine` must not import `api`, `models`, or DB sessions. Services map DB rows → engine snapshots.
