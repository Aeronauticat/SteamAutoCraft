#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$BASE_DIR"
umask 077
mkdir -p .run

if ! mkdir .run/control.lock 2>/dev/null; then
    echo "Another start/stop operation is in progress."
    exit 1
fi
trap 'rmdir "$BASE_DIR/.run/control.lock"' EXIT

if [[ ! -f .run/main.pid ]]; then
    echo "Not running via start.sh (no PID file)."
    exit 0
fi

pid="$(cat .run/main.pid)"
if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid PID file; no process was stopped."
    exit 1
fi
if ! command_line="$(ps -p "$pid" -o command= 2>/dev/null)"; then
    if kill -0 "$pid" 2>/dev/null; then
        echo "Unable to inspect PID $pid; no process was stopped."
        exit 1
    fi
fi
if [[ "$command_line" != *"$BASE_DIR/main.py"* ]]; then
    rm -f .run/main.pid
    echo "Removed stale PID file; no matching process is running."
    exit 0
fi

if ! kill -TERM "$pid" 2>/dev/null; then
    if kill -0 "$pid" 2>/dev/null; then
        echo "Unable to stop PID $pid. Check process permissions."
        exit 1
    fi
fi
for ((attempt=0; attempt<50; attempt++)); do
    if ! command_line="$(ps -p "$pid" -o command= 2>/dev/null)"; then
        if kill -0 "$pid" 2>/dev/null; then
            echo "Unable to inspect PID $pid; PID file retained."
            exit 1
        fi
    fi
    if [[ "$command_line" != *"$BASE_DIR/main.py"* ]]; then
        rm -f .run/main.pid
        echo "Stopped (PID $pid)."
        exit 0
    fi
    sleep 0.2
done
echo "PID $pid has not exited after 10 seconds; PID file retained."
exit 1
