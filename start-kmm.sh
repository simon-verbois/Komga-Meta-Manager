#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker and Docker Compose v2 are required." >&2
  exit 1
fi

mkdir -p "$PROJECT_DIR/config"

docker compose \
  --project-name kmm-dev \
  --project-directory "$PROJECT_DIR" \
  -f "$PROJECT_DIR/compose-testing.yml" \
  up --build --detach

echo "KMM development environment started: http://localhost:8765"
echo "Run $PROJECT_DIR/stop-kmm.sh to stop it."
