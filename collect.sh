#!/usr/bin/env bash
# Coleta manual de todos os switches. Uso: ./collect.sh   |  MOCK=1 ./collect.sh
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
exec $PY -m sanmon.collector ${MOCK:+--mock} "$@"
