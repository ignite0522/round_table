#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${ROUNDTABLE_KALI_IMAGE:-roundtable-kali:latest}"
WORKSPACE_DIR="${1:-${REPO_ROOT}/round_table_work}"
shift || true

HOST_CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"

mkdir -p "${WORKSPACE_DIR}"

docker run --rm -it \
  --platform linux/amd64 \
  --name "roundtable-kali-$(date +%s)" \
  -e HOST_CODEX_HOME=/host-codex-home \
  -v "${REPO_ROOT}:/opt/roundtable" \
  -v "${WORKSPACE_DIR}:/workspace" \
  -v "${HOST_CODEX_HOME}:/host-codex-home:ro" \
  -w /opt/roundtable \
  "${IMAGE_TAG}" \
  "$@"
