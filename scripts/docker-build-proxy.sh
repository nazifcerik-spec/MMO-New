#!/usr/bin/env bash
# Build images behind an HTTPS egress proxy with a custom CA (e.g. sandboxed CI).
# Usage: EXTRA_CA=/path/ca.pem scripts/docker-build-proxy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CA="${EXTRA_CA:?set EXTRA_CA to a CA bundle path}"
docker build --network host --build-arg HTTPS_PROXY="${HTTPS_PROXY:-}" --secret id=extra_ca,src="$CA" \
  -t oldschool-afk-mmo-backend "$ROOT/backend"
docker build --network host --build-arg HTTPS_PROXY="${HTTPS_PROXY:-}" --secret id=extra_ca,src="$CA" \
  --build-arg BACKEND_URL=http://backend:8000 -t oldschool-afk-mmo-frontend "$ROOT/frontend"
