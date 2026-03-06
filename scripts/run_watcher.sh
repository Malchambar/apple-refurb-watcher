#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}"

if [[ -x "venv/bin/python3" ]]; then
  PYTHON_BIN="venv/bin/python3"
elif [[ -x ".venv/bin/python3" ]]; then
  PYTHON_BIN=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "No python3 interpreter found. Create a virtualenv first." >&2
  exit 1
fi

"${PYTHON_BIN}" -m src.main
