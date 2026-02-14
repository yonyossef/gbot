#!/usr/bin/env bash
# Run the Shop Assistant server. Keeps running until Ctrl+C or --stop.
#
# Usage:
#   ./scripts/run_server.sh          # Foreground (recommended: keep terminal open)
#   ./scripts/run_server.sh --daemon  # Background with nohup, survives shell close
#   ./scripts/run_server.sh --stop    # Stop daemon
#
set -e
cd "$(dirname "$0")/.."
PIDFILE=".server.pid"
PORT="${PORT:-8001}"

stop_server() {
  if [[ -f "$PIDFILE" ]]; then
    pid=$(cat "$PIDFILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "Stopped server (PID $pid)"
    fi
    rm -f "$PIDFILE"
  else
    pkill -f "uvicorn main:app" 2>/dev/null && echo "Stopped uvicorn" || echo "No server running"
  fi
}

if [[ "$1" == "--stop" ]]; then
  stop_server
  exit 0
fi

if [[ "$1" == "--daemon" ]]; then
  stop_server
  . .venv/bin/activate
  nohup uvicorn main:app --host 0.0.0.0 --port "$PORT" > .server.log 2>&1 &
  echo $! > "$PIDFILE"
  echo "Server started in background (PID $(cat $PIDFILE)). Log: .server.log"
  echo "Stop with: ./scripts/run_server.sh --stop"
  exit 0
fi

# Foreground: run with restart loop so it recovers from crashes
. .venv/bin/activate
echo "Server on http://127.0.0.1:$PORT (Ctrl+C to stop)"
while true; do
  uvicorn main:app --host 0.0.0.0 --port "$PORT" || true
  echo "Restarting in 2s..."
  sleep 2
done
