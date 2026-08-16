#!/usr/bin/env bash
set -euo pipefail

REAL_CLAUDE="${ROUNDTABLE_REAL_CLAUDE:-/usr/local/bin/claude-real}"
CLAUDE_MODEL="${ROUNDTABLE_MODEL:-claude-sonnet-4-5}"

ensure_anthropic_base_url() {
  local raw="${1:-}"
  if [[ -z "${raw}" ]]; then
    printf '%s\n' "http://api.deepseek.com.tsecbench.gw/anthropic"
    return 0
  fi
  if [[ "${raw}" == */anthropic ]]; then
    printf '%s\n' "${raw}"
    return 0
  fi
  printf '%s/anthropic\n' "${raw%/}"
}

export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-${DEEPSEEK_API_KEY:-}}"
export ANTHROPIC_BASE_URL="$(
  ensure_anthropic_base_url "${ANTHROPIC_BASE_URL:-${DEEPSEEK_BASE_URL:-http://api.deepseek.com.tsecbench.gw}}"
)"

if [[ "${1:-}" != "exec" ]]; then
  exec "${REAL_CLAUDE}" "$@"
fi
shift

output_last_message=""
output_schema=""
workdir=""

while [[ "$#" -gt 0 ]]; do
  case "${1}" in
    --skip-git-repo-check)
      shift
      ;;
    --output-last-message)
      output_last_message="${2:?missing value for --output-last-message}"
      shift 2
      ;;
    --output-schema)
      output_schema="${2:?missing value for --output-schema}"
      shift 2
      ;;
    --sandbox)
      shift 2
      ;;
    --cd)
      workdir="${2:?missing value for --cd}"
      shift 2
      ;;
    --model)
      shift 2
      ;;
    -)
      shift
      break
      ;;
    *)
      echo "unsupported codex bridge arg: ${1}" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${output_last_message}" || -z "${output_schema}" ]]; then
  echo "missing required codex bridge outputs" >&2
  exit 2
fi

if [[ -n "${workdir}" ]]; then
  cd "${workdir}"
fi

prompt_file="$(mktemp)"
json_file="$(mktemp)"
cleanup() {
  rm -f "${prompt_file}" "${json_file}"
}
trap cleanup EXIT

cat >"${prompt_file}"

schema_minified="$(
  python3 - "${output_schema}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
print(json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":")))
PY
)"

"${REAL_CLAUDE}" \
  -p \
  --output-format json \
  --json-schema "${schema_minified}" \
  --permission-mode bypassPermissions \
  --model "${CLAUDE_MODEL}" \
  "$(cat "${prompt_file}")" >"${json_file}"

python3 - "${json_file}" "${output_last_message}" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
structured = payload.get("structured_output")
if structured is None:
    raise SystemExit("claude bridge missing structured_output")
pathlib.Path(sys.argv[2]).write_text(
    json.dumps(structured, ensure_ascii=False),
    encoding="utf-8",
)
PY
