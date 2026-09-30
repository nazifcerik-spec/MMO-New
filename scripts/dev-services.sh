#!/usr/bin/env bash
# Start local Postgres + Redis without Docker (container/CI convenience) and create dev/test databases.
set -euo pipefail
service postgresql start >/dev/null 2>&1 || true
pgrep -x redis-server >/dev/null || redis-server --daemonize yes >/dev/null
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='mmo'\"" | grep -q 1 || \
  su postgres -c "psql -q -c \"CREATE ROLE mmo LOGIN PASSWORD 'mmo' CREATEDB\""
for db in mmo mmo_test; do
  su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='$db'\"" | grep -q 1 || \
    su postgres -c "psql -q -c 'CREATE DATABASE $db OWNER mmo'"
done
echo "postgres+redis ready"
