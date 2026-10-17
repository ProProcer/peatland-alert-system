#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
role="${1:-all}"
case "$role" in
  a|b|c|d|e|all) ;;
  *) echo "Usage: bash scripts/setup.sh [a|b|c|d|e|all]" >&2; exit 2 ;;
esac

python_command="${BOOTSTRAP_PYTHON:-python3}"
"$python_command" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"'
if [[ ! -x .venv/bin/python ]]; then
  "$python_command" -m venv .venv
fi

requirements=(-r requirements-dev.txt)
case "$role" in
  a) requirements+=(-r a_data/requirements.txt) ;;
  b) requirements+=(-r b_model/requirements.txt) ;;
  c) requirements+=(-r c_agent/requirements.txt) ;;
  e) requirements+=(-r e_platform/requirements.txt) ;;
  all) requirements+=(-r a_data/requirements.txt -r b_model/requirements.txt -r c_agent/requirements.txt -r e_platform/requirements.txt) ;;
esac
.venv/bin/python -m pip install --disable-pip-version-check -c constraints.txt "${requirements[@]}"

if [[ ! -e .env ]]; then
  cp .env.example .env
fi
.venv/bin/python -m contracts.validate
echo "Role $role is ready. Activate with: source .venv/bin/activate"
echo "Run the offline handoff viewer with: make demo"
