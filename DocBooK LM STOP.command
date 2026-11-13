#!/bin/bash
# DocBooK LM — ferma l'interfaccia. Il router llama.cpp resta com'è.
set -u

PORT=8078
FOUND=0

PIDS=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null && FOUND=1
  done
fi

PIDS=$(pgrep -f "uvicorn docbooklm.api:app" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null && FOUND=1
  done
fi

if [ "$FOUND" = "1" ]; then
  echo "DocBooK LM fermato."
else
  echo "DocBooK LM non era in esecuzione."
fi
