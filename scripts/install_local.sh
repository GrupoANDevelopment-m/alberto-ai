#!/usr/bin/env bash
# Reproducible, isolated local installation for Linux/macOS.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="${ALBERTO_VENV:-$ROOT/.venv}"

command -v "$PYTHON" >/dev/null 2>&1 || { echo "ERROR: python3 not found"; exit 1; }
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("ERROR: Alberto AI requires Python 3.11 or newer.")
print("Python:", sys.version.split()[0])
PY

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi
source "$VENV/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e "$ROOT"

echo
echo "Installation completed in: $VENV"
echo "Activate with: source "$VENV/bin/activate""
echo "Next: python scripts/alberto_doctor.py"
echo "Then configure NVIDIA and start: alberto-serve --host 127.0.0.1 --port 8741"
