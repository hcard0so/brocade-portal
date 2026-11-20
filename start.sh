#!/usr/bin/env bash
# Sobe o portal em segundo plano (sem coleta automática).
# Uso: ./start.sh   |   PORT=8600 ./start.sh   |   MOCK=1 ./start.sh
cd "$(dirname "$0")"
PORT=${PORT:-8501}
mkdir -p logs
[ -f .env ] && { set -a; . ./.env; set +a; }
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3

./stop.sh >/dev/null 2>&1; sleep 1
if ss -tln "sport = :$PORT" | grep -q LISTEN; then
  echo "ERRO: a porta $PORT já está em uso. Escolha outra: PORT=8600 ./start.sh"
  echo "Portas em uso:"; ss -tln | awk 'NR>1 {print "  " $4}' | sort -u
  exit 1
fi

nohup $PY -m streamlit run app.py --server.port "$PORT" >> logs/portal.log 2>&1 &
echo $! > logs/portal.pid
echo "portal PID $(cat logs/portal.pid) — http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT"
echo "coleta: botão 'Coletar agora' no portal ou ./collect.sh"
