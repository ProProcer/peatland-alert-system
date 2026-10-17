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
  live) output_dir="${2:-$PROJECT_ROOT/data/processed}" ;;
  *) echo "Usage: bash scripts/run_pipeline.sh [--mock|live] [output-directory]" >&2; exit 2 ;;
esac
if [[ $# -gt 2 ]]; then
  echo "Too many arguments" >&2
  exit 2
fi

if [[ "$mode" == --mock ]]; then
  "$PYTHON" -m e_platform.prepare_demo --output-dir "$output_dir"
else
  "$PYTHON" -m a_data.refresh --output-dir "$output_dir"
  "$PYTHON" -m contracts.validate --kind features "$output_dir/features.json"
  "$PYTHON" -m contracts.validate --kind cells "$output_dir/cells.geojson"
  "$PYTHON" -m b_model.predict --input "$output_dir/features.json" --output "$output_dir/risk.json"
  "$PYTHON" -m contracts.validate --kind risk "$output_dir/risk.json"
  "$PYTHON" -m c_agent.agent --data-dir "$output_dir" --output "$output_dir/dispatch.json"
  "$PYTHON" -m contracts.validate --data-dir "$output_dir"
fi
