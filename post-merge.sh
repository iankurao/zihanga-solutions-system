#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

export PATH="$PWD/.pythonlibs/bin:$PATH"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

# Fail before touching the database if the merged Python code has syntax errors.
python -m compileall -q backend main.py setup_super_admin.py

# Keep the database schema ready for the application after a merge.
python -m backend.init_db