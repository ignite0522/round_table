#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${1:-roundtable-standalone:latest}"

docker build \
  -f "${REPO_ROOT}/docker/roundtable-standalone/Dockerfile" \
  -t "${IMAGE_TAG}" \
  "${REPO_ROOT}"

echo "Built ${IMAGE_TAG}"
