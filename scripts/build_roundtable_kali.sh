#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${1:-roundtable-kali:latest}"
IMAGE_PLATFORM="${ROUNDTABLE_KALI_PLATFORM:-linux/amd64}"

docker build \
  --platform "${IMAGE_PLATFORM}" \
  -f "${REPO_ROOT}/docker/roundtable-kali/Dockerfile" \
  -t "${IMAGE_TAG}" \
  "${REPO_ROOT}/docker/roundtable-kali"
