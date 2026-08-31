#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs) 2>/dev/null || true
fi

# Поиск рабочего Python
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYBIN="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "/home/paul/pm-venv/bin/python" ]; then
  PYBIN="/home/paul/pm-venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYBIN="$(command -v python3)"
else
  echo "Python3 не найден в системе" >&2
  exit 1
fi

exec "$PYBIN" server.py
