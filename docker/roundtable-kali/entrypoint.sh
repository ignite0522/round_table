#!/usr/bin/env bash
set -euo pipefail

USER_CODEX_HOME="${HOME}/.codex"
HOST_CODEX_HOME="${HOST_CODEX_HOME:-/host-codex-home}"

mkdir -p "${USER_CODEX_HOME}"

if [[ -f "${HOST_CODEX_HOME}/auth.json" && ! -f "${USER_CODEX_HOME}/auth.json" ]]; then
  cp "${HOST_CODEX_HOME}/auth.json" "${USER_CODEX_HOME}/auth.json"
  chmod 600 "${USER_CODEX_HOME}/auth.json"
fi

if [[ -f "${HOST_CODEX_HOME}/config.toml" && ! -f "${USER_CODEX_HOME}/config.toml" ]]; then
  cp "${HOST_CODEX_HOME}/config.toml" "${USER_CODEX_HOME}/config.toml"
  chmod 600 "${USER_CODEX_HOME}/config.toml"
fi

exec "$@"
