#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${ROUNDTABLE_STANDALONE_IMAGE:-roundtable-standalone:latest}"
PORT="${ROUNDTABLE_STANDALONE_PORT:-5055}"
HOST_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

docker run --rm -it \
  -p "${PORT}:5055" \
  -v "${HOST_CODEX_HOME}:/root/.codex:ro" \
  -v "${REPO_ROOT}/round_table_work:/app/round_table_work" \
  --name "roundtable-standalone-$(date +%s)" \
  "${IMAGE_TAG}"
