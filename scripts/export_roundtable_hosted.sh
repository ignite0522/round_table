#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="${1:-roundtable-hosted:latest}"
OUTPUT="${2:-${SCRIPT_DIR}/../dist/roundtable-hosted.tar.gz}"
MAX_BYTES=$((3 * 1024 * 1024 * 1024))

mkdir -p "$(dirname "${OUTPUT}")"
docker image inspect "${IMAGE_TAG}" >/dev/null
docker save "${IMAGE_TAG}" | gzip -6 > "${OUTPUT}"

SIZE_BYTES="$(stat -f '%z' "${OUTPUT}" 2>/dev/null || stat -c '%s' "${OUTPUT}")"
if (( SIZE_BYTES > MAX_BYTES )); then
  echo "Export is larger than TSecBench's 3 GB limit: ${SIZE_BYTES} bytes" >&2
  exit 1
fi

ls -lh "${OUTPUT}"
echo "Upload this archive in TSecBench hosted mode."
