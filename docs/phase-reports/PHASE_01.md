# PHASE 01 — Monorepo, Docker, backend/frontend skeleton
Status: complete

## Done
- Monorepo: `backend/`, `frontend/`, `docs/`, `scripts/`, `infra/` (+ root `docker-compose.yml`).
- Backend (Python 3.12, uv): FastAPI app factory `app/main.py`, pydantic-settings config (`MMO_*` env),
  async SQLAlchemy engine/session, Redis client, Alembic (async env, naming conventions, rev `0001` baseline).
  Layers: api, domain, services, repositories, models, schemas, game_engine, localization, content.
- Health: `/health/live`, `/health`, `/health/ready`, `/api/v1/health` — DB and Redis reported separately (503 if degraded).
- Structured JSON logging with correlation id (pure ASGI middleware, `X-Correlation-ID` echo/generation),
  security headers, standard error envelope `{error:{code,message,details,correlation_id}}`, no stack traces in prod.
- Frontend: Next.js 16 App Router + TS + Tailwind v4 + TanStack Query + next-intl (cookie/Accept-Language locale),
  route shells `/`, `/login`, `/game`, `/admin`; `/api/*` rewrite to backend (same-origin cookies);
  dirs app, components, features, lib/api, lib/i18n, types. Health widget proves frontend→backend reachability.
- Docker: multi-stage non-root backend/frontend images; compose with healthchecks; `.env.example`; no secrets committed.
  `scripts/docker-build-proxy.sh` builds behind an egress proxy with a custom CA (BuildKit secret).
- CI: `.github/workflows/ci.yml`; commands documented in `docs/dev/COMMANDS.md`; `scripts/check.sh` gate;
  `scripts/e2e.sh`; migration drift checker `backend/scripts/check_migrations.py`; safe `reset_db` (refuses prod).

## Gate
ruff + format + mypy strict clean · pytest 4 passed · no migration drift · eslint/tsc clean · vitest 8 passed ·
next build ok · `docker compose up` all healthy, `/health` ok, frontend→backend proxy ok ·
Playwright smoke 8 passed (desktop + mobile) against the compose stack and against local processes.

## Notes / risks
- Sandbox egress blocks ghcr.io; images build via PyPI/npm with proxy CA secret (normal envs use `docker compose up --build`).
