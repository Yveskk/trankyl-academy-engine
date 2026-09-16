#!/usr/bin/env bash
# Demarre l'API FastAPI. Installe les dependances tout seul au premier lancement.
# Usage : scripts/start.sh [--reload]
set -e
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "-> .env cree depuis .env.example. Renseignez DATABASE_URL et SECRET_KEY avant de continuer."
fi

PYTHON=python3

if ! "$PYTHON" -c "import fastapi" >/dev/null 2>&1; then
  echo "-> installation des dependances Python..."
  "$PYTHON" -m pip install -q -r requirements.txt --break-system-packages 2>/dev/null \
    || "$PYTHON" -m pip install -q -r requirements.txt --user \
    || "$PYTHON" -m pip install -q -r requirements.txt
fi

RELOAD_FLAG=""
if [ "$1" = "--reload" ]; then
  RELOAD_FLAG="--reload"
fi

PORT="${PORT:-8000}"

exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" $RELOAD_FLAG
