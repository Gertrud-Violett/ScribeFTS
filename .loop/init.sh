#!/usr/bin/env bash
# .loop/init.sh: make ScribeFTS ready for a loop run. ralph.sh runs it once
# before the first iteration; you can run it by hand at any time.
#
# Contract (the loop relies on this):
#   - Idempotent: safe to run on every loop start; second run should be fast.
#   - Non-interactive: no prompts, no GUI, no sudo.
#   - Exit 0  = ready.
#   - Exit 10 = needs the owner (missing tool). Prints WHAT and HOW to fix it.
#   - Any other non-zero = setup is broken.
#
# Stack: pure Python (stdlib + Flask + PyMuPDF), tests are unittest run via pytest.
# No secrets needed: AI extraction (Gemini/OpenAI) is optional and not used by tests.
set -euo pipefail
cd "$(dirname "$0")/.."

need() {  # need <command> "<how to install>"
  command -v "$1" >/dev/null 2>&1 || { echo "MISSING TOOL: $1. $2"; exit 10; }
}
need_env() {  # need_env VAR "<where it comes from>"
  [[ -n ${!1:-} ]] || { echo "MISSING SECRET: \$$1. $2"; exit 10; }
}

# ---- 1. tools -------------------------------------------------------------
need git "apt install git"

# README asks for Python 3.14+; the code itself needs >= 3.10 (PEP 604 `X | None`).
# Use the newest interpreter on the host (override with PYTHON=/path/to/python).
PY="${PYTHON:-}"
if [[ -z $PY ]]; then
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[[ -n $PY ]] || { echo "MISSING TOOL: python3 (>=3.10). apt install python3 python3-venv (owner)"; exit 10; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "MISSING TOOL: Python >= 3.10 (found $("$PY" -V 2>&1)). Install python3.12+ with venv (owner)"; exit 10; }

# ---- 2. secrets: none required ---------------------------------------------
# AI provider keys live in data/ai_config.json (gitignored) and are only for
# interactive use; the loop and tests must never call paid AI APIs.

# ---- 3. dependencies (idempotent) ------------------------------------------
DEPS="flask pymupdf pytest"
STAMP=.venv/.installed
if [[ ! -x .venv/bin/python ]]; then
  "$PY" -m venv .venv \
    || { echo "MISSING TOOL: python venv module for $PY. apt install python3-venv (owner)"; exit 10; }
fi
if [[ ! -f $STAMP || "$(cat "$STAMP")" != "$DEPS" || .loop/init.sh -nt $STAMP ]]; then
  .venv/bin/python -m pip install -q --disable-pip-version-check -U pip
  # shellcheck disable=SC2086
  .venv/bin/python -m pip install -q --disable-pip-version-check $DEPS
  echo "$DEPS" > "$STAMP"
fi
mkdir -p .loop/artifacts

# ---- 4. smoke check: the verify tooling runs --------------------------------
.venv/bin/python -m pytest --version >/dev/null
.venv/bin/python -c 'import flask, pymupdf, sqlite3; sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")' \
  || { echo "SETUP BROKEN: flask/pymupdf import or SQLite FTS5 unavailable"; exit 1; }

echo "init ok ($(.venv/bin/python -V))"
