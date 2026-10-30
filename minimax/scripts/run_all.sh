#!/usr/bin/env bash
# One-command reproduction of the whole verification chain.
#
#   bash scripts/run_all.sh            # embedded seekdb (no Docker required)
#   bash scripts/run_all.sh docker     # containerised seekdb
#
# The script resolves the virtual environment interpreter itself, so it works
# on Linux, macOS and Windows (Git Bash) without editing any path.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINIMAX="$(dirname "$HERE")"
STORAGE="${1:-embedded}"

if [ -n "${SDDCTX_PYTHON:-}" ]; then
    PY="$SDDCTX_PYTHON"
elif [ -x "$MINIMAX/.venv/bin/python" ]; then
    PY="$MINIMAX/.venv/bin/python"
elif [ -x "$MINIMAX/.venv/Scripts/python.exe" ]; then
    PY="$MINIMAX/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    PY="$(command -v python)"
fi

cd "$MINIMAX"
echo "== interpreter: $PY"
echo "== storage mode: $STORAGE"

echo
echo "== [0/4] reset the scope and re-import the corpus"
"$PY" scripts/reset.py --scope minimax-sdd --storage "$STORAGE"

echo
echo "== [1/4] end to end: import -> retrieve -> model -> patch -> tests -> reuse progress"
"$PY" scripts/run_e2e.py --storage "$STORAGE" \
    --model-answer model/SPEC-BILL-001-pricing.session-model.txt \
    --model-id "MiniMax-M3.1-Flash"

echo
echo "== [2/4] restart persistence: empty state -> cold restart -> read back -> reuse"
"$PY" scripts/prove_restart_persistence.py --storage "$STORAGE"

echo
echo "== [3/4] specification revision: edit the spec -> re-import -> new content in context"
"$PY" scripts/prove_spec_revision.py --storage "$STORAGE"

echo
echo "== [4/4] done -- evidence under artifacts/"
