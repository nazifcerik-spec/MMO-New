#!/usr/bin/env bash
# Run Playwright E2E against a locally started backend (uvicorn) + production frontend build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export MMO_DATABASE_URL="${E2E_DATABASE_URL:-postgresql+asyncpg://mmo:mmo@localhost:5432/mmo_e2e}"
export MMO_ENV=dev MMO_LOG_LEVEL=WARNING
cd "$ROOT/backend"
uv run python -m scripts.reset_db --url "$MMO_DATABASE_URL"
uv run alembic upgrade head >/dev/null
uv run python -m scripts.seed >/dev/null
uv run uvicorn app.main:app --port 8000 >/tmp/e2e-backend.log 2>&1 &
BACK=$!
cd "$ROOT/frontend"
[ -n "${E2E_SKIP_BUILD:-}" ] || npm run build >/dev/null
BACKEND_URL=http://localhost:8000 npx next start -p 3000 >/tmp/e2e-frontend.log 2>&1 &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf http://localhost:3000 >/dev/null && curl -sf http://localhost:8000/health >/dev/null && break; sleep 1; done
PW_CHROMIUM_PATH="${PW_CHROMIUM_PATH:-}" npx playwright test "$@"
