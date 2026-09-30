# Dev / CI commands

## One-command dev stack
```bash
cp .env.example .env
docker compose up --build          # postgres, redis, backend :8000, frontend :3000
# behind an HTTPS egress proxy with custom CA: EXTRA_CA=/path/ca.pem scripts/docker-build-proxy.sh
```

## Without Docker (local services)
```bash
scripts/dev-services.sh                                  # postgres + redis, dbs mmo / mmo_test
cd backend && uv sync && uv run alembic upgrade head && uv run python -m scripts.seed
uv run uvicorn app.main:app --reload                     # :8000
cd frontend && npm ci && npm run dev                     # :3000 (proxies /api -> :8000)
```

## Quality gate (CI runs exactly these) — `scripts/check.sh`
| Area | Command (cwd) |
|---|---|
| Backend lint | `uv run ruff check .` (backend) |
| Backend format | `uv run ruff format --check .` |
| Backend types | `uv run mypy app` |
| Backend tests | `uv run pytest -q` (drops+migrates `mmo_test` from empty) |
| Migration drift | `uv run python -m scripts.check_migrations` |
| Frontend lint | `npm run lint` (frontend) |
| Frontend types | `npm run typecheck` |
| Frontend unit | `npm test` |
| Frontend build | `npm run build` |
| E2E | `scripts/e2e.sh` (starts backend + frontend, runs Playwright desktop+mobile) |

## API types
`npm run gen:api` regenerates `frontend/src/types/api.d.ts` from the backend OpenAPI schema.
