#!/bin/bash
# DocBooK LM — avvio da doppio clic.
set -u
cd "$(dirname "$0")" || exit 1

PORT=8078
ROUTER="http://127.0.0.1:8080"
LOG="data/docbooklm.log"

say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------- ambiente
if [ ! -x ".venv/bin/python" ]; then
  say "Preparo l'ambiente (una volta sola)..."
  command -v uv >/dev/null 2>&1 || { say "Serve 'uv' (https://docs.astral.sh/uv/)."; exit 1; }
  uv venv --python 3.12 .venv >/dev/null || exit 1
  uv pip install --python .venv/bin/python -e ".[dev]" >/dev/null || exit 1
fi

[ -f ".env" ] || cp .env.example .env

mkdir -p data

# ---------------------------------------------------------------- motore
if ! curl -s --max-time 3 "$ROUTER/v1/models" >/dev/null 2>&1; then
  say "Il router llama.cpp non risponde su $ROUTER."
  say "Apri prima 'LLAMA.CPP START.command' e riprova."
  read -r -p "Premi invio per uscire." _
  exit 1
fi

# ---------------------------------------------------------------- servizio
if curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  say "DocBooK LM è già attivo: apro il browser."
  open "http://127.0.0.1:$PORT/"
  exit 0
fi

say "Avvio DocBooK LM su http://127.0.0.1:$PORT/"
.venv/bin/python -m uvicorn docbooklm.api:app \
  --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  say ""
  say "Fermo DocBooK LM..."
  kill "$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
  say "Fermato."
}
trap cleanup INT TERM EXIT

for _ in $(seq 1 40); do
  if curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT/"
    say "Pronto. Chiudi questa finestra o premi CTRL+C per fermare."
    break
  fi
  sleep 0.5
done

wait "$SERVER_PID"
