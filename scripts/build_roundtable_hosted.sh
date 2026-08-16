#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${1:-roundtable-hosted:latest}"
ALPINE_VERSION="${ALPINE_VERSION:-3.24.1}"
ROOTFS_URL="https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/alpine-minirootfs-${ALPINE_VERSION}-x86_64.tar.gz"
ROOTFS_DIR="${REPO_ROOT}/.cache/base-images"
ROOTFS_PATH="${ROOTFS_DIR}/alpine-minirootfs-${ALPINE_VERSION}-x86_64.tar.gz"
BASE_IMAGE="roundtable-alpine-base:${ALPINE_VERSION}-amd64"
TMP_NAME="roundtable-hosted-build-$$"

cleanup() {
  docker rm -f "${TMP_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

map_proxy_for_container() {
  local raw="${1:-}"
  if [[ -z "${raw}" ]]; then
    return 0
  fi
  raw="${raw/127.0.0.1/host.docker.internal}"
  raw="${raw/localhost/host.docker.internal}"
  printf '%s' "${raw}"
}

HTTP_PROXY_CONTAINER="$(map_proxy_for_container "${HTTP_PROXY:-${http_proxy:-}}")"
HTTPS_PROXY_CONTAINER="$(map_proxy_for_container "${HTTPS_PROXY:-${https_proxy:-}}")"
ALL_PROXY_CONTAINER="$(map_proxy_for_container "${ALL_PROXY:-${all_proxy:-}}")"

mkdir -p "${ROOTFS_DIR}"
if [[ ! -f "${ROOTFS_PATH}" ]]; then
  curl -L --fail --retry 5 --retry-delay 2 -o "${ROOTFS_PATH}" "${ROOTFS_URL}"
fi

if ! docker image inspect "${BASE_IMAGE}" >/dev/null 2>&1; then
  gunzip -c "${ROOTFS_PATH}" | docker import --platform linux/amd64 - "${BASE_IMAGE}" >/dev/null
fi

docker create \
  --platform linux/amd64 \
  --name "${TMP_NAME}" \
  --entrypoint /bin/sh \
  "${BASE_IMAGE}" \
  -lc 'sleep infinity' >/dev/null
docker start "${TMP_NAME}" >/dev/null
docker exec "${TMP_NAME}" /bin/sh -lc 'mkdir -p /app'
tar \
  --exclude='./.git' \
  --exclude='./.cache' \
  --exclude='./dist' \
  --exclude='./round_table_work' \
  --exclude='./.pytest_cache' \
  --exclude='./__pycache__' \
  --exclude='./*.pyc' \
  -C "${REPO_ROOT}" \
  -cf - . | docker exec -i "${TMP_NAME}" /bin/sh -lc 'tar -C /app -xf -'

INSTALL_CMD='set -e
'
if [[ -n "${HTTP_PROXY_CONTAINER}" ]]; then
  INSTALL_CMD+="export HTTP_PROXY='${HTTP_PROXY_CONTAINER}' http_proxy='${HTTP_PROXY_CONTAINER}'"$'\n'
fi
if [[ -n "${HTTPS_PROXY_CONTAINER}" ]]; then
  INSTALL_CMD+="export HTTPS_PROXY='${HTTPS_PROXY_CONTAINER}' https_proxy='${HTTPS_PROXY_CONTAINER}'"$'\n'
fi
if [[ -n "${ALL_PROXY_CONTAINER}" ]]; then
  INSTALL_CMD+="export ALL_PROXY='${ALL_PROXY_CONTAINER}' all_proxy='${ALL_PROXY_CONTAINER}'"$'\n'
fi
INSTALL_CMD+=$'apk add --no-cache bash ca-certificates curl git python3 py3-pip py3-virtualenv nodejs npm procps\n'
INSTALL_CMD+=$'adduser -D -h /home/roundtable -s /bin/sh roundtable\n'
INSTALL_CMD+=$'python3 -m venv /opt/roundtable-venv\n'
INSTALL_CMD+=$'/opt/roundtable-venv/bin/pip install -r /app/requirements.txt\n'
INSTALL_CMD+=$'npm install -g @anthropic-ai/claude-code\n'
INSTALL_CMD+=$'mv /usr/local/bin/claude /usr/local/bin/claude-real\n'
INSTALL_CMD+=$'install -m 0755 /app/hosted/codex-deepseek-wrapper.sh /usr/local/bin/codex\n'
INSTALL_CMD+=$'install -m 0755 /app/hosted/entrypoint.sh /usr/local/bin/roundtable-hosted-entrypoint\n'
INSTALL_CMD+=$'ln -sf /opt/roundtable-venv/bin/python /usr/local/bin/python\n'
INSTALL_CMD+=$'ln -sf /opt/roundtable-venv/bin/pip /usr/local/bin/pip\n'
INSTALL_CMD+=$'mkdir -p /home/roundtable/.codex /app/round_table_work/benchmark-runs\n'
INSTALL_CMD+=$'chown -R roundtable:roundtable /home/roundtable /app/round_table_work\n'

docker exec "${TMP_NAME}" /bin/sh -lc "${INSTALL_CMD}"

docker export "${TMP_NAME}" | docker import \
  --platform linux/amd64 \
  -c 'WORKDIR /app' \
  -c 'USER roundtable' \
  -c 'ENTRYPOINT ["/usr/local/bin/roundtable-hosted-entrypoint"]' \
  - "${IMAGE_TAG}" >/dev/null

docker image inspect "${IMAGE_TAG}" --format 'Built {{.RepoTags}} ({{.Architecture}}/{{.Os}})'
