#!/usr/bin/env bash
# Full local quality gate (same commands CI runs). Requires local Postgres + Redis (see docs/dev/COMMANDS.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== backend: lint/format/type =="
cd "$ROOT/backend"
uv run ruff check .
uv run ruff format --check .
uv run mypy app

echo "== backend: tests (migrates test DB from empty) =="
uv run pytest -q

echo "== backend: migration drift =="
uv run python -m scripts.check_migrations

echo "== frontend: lint/type/unit/build =="
cd "$ROOT/frontend"
npm run lint
npm run typecheck
npm test
npm run build
echo "ALL CHECKS PASSED"
