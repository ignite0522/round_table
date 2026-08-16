#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -gt 0 ]]; then
  exec "$@"
fi

: "${BENCHMARK_BASE_URL:?BENCHMARK_BASE_URL is injected by TSecBench}"
: "${BENCHMARK_TOKEN:?BENCHMARK_TOKEN is injected by TSecBench}"
: "${DEEPSEEK_API_KEY:?configure DEEPSEEK_API_KEY in hosted environment variables}"

export HOME="${HOME:-/home/roundtable}"
export CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
export ROUNDTABLE_MODEL="${ROUNDTABLE_MODEL:-claude-sonnet-4-5}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-${DEEPSEEK_API_KEY}}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://api.deepseek.com.tsecbench.gw/anthropic}"
export DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL:-http://api.deepseek.com.tsecbench.gw}"
export PYTHONUNBUFFERED=1

mkdir -p "${CODEX_HOME}" /app/round_table_work/benchmark-runs

echo "[hosted] Round Table Standalone starting"
echo "[hosted] model=${ROUNDTABLE_MODEL}"
echo "[hosted] anthropic_base_url=${ANTHROPIC_BASE_URL}"
echo "[hosted] task_budget_min=${ROUNDTABLE_TASK_BUDGET_MIN:-5} max_cycles=${ROUNDTABLE_MAX_CYCLES:-7} max_parallel=${ROUNDTABLE_MAX_PARALLEL:-3}"

exec python -m examples.run_benchmark \
  --cwd /app/round_table_work/benchmark-runs \
  --codex-bin /usr/local/bin/codex \
  --max-cycles "${ROUNDTABLE_MAX_CYCLES:-7}" \
  --time-budget-min "${ROUNDTABLE_TASK_BUDGET_MIN:-5}" \
  --max-parallel "${ROUNDTABLE_MAX_PARALLEL:-3}" \
  --no-sandbox
