#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
if [[ "$PYTHON" == */* && "$PYTHON" != /* ]]; then
  PYTHON="$PROJECT_ROOT/$PYTHON"
fi
mode="${1:-live}"
case "$mode" in
  --mock) output_dir="${2:-$PROJECT_ROOT/data/demo}" ;;
  live) output_dir="${2:-$PROJECT_ROOT/data/runtime/live}" ;;
  *) echo "Usage: bash scripts/run_pipeline.sh [--mock|live] [output-directory]" >&2; exit 2 ;;
esac
if [[ $# -gt 2 ]]; then
  echo "Too many arguments" >&2
  exit 2
fi

if [[ "$mode" == --mock ]]; then
  "$PYTHON" -m e_platform.prepare_demo --output-dir "$output_dir"
else
  "$PYTHON" -m e_platform.live_service --once --runtime-dir "$output_dir"
fi
