#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$BASE_DIR"
umask 077
mkdir -p .run logs

if ! mkdir .run/control.lock 2>/dev/null; then
    echo "Another start/stop operation is in progress."
    exit 1
fi
trap 'rmdir "$BASE_DIR/.run/control.lock"' EXIT

if [[ -f .run/main.pid ]]; then
    pid="$(cat .run/main.pid)"
    if [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
        if ! command_line="$(ps -p "$pid" -o command= 2>/dev/null)"; then
            if kill -0 "$pid" 2>/dev/null; then
                echo "Unable to inspect PID $pid; no new process was started."
                exit 1
            fi
        fi
        if [[ "$command_line" == *"$BASE_DIR/main.py"* ]]; then
            echo "Already running (PID $pid)."
            exit 0
        fi
    fi
    rm -f .run/main.pid
fi

if [[ -n "${PYTHON_BIN:-}" ]]; then
    python_bin="$PYTHON_BIN"
elif [[ -x "$BASE_DIR/.venv/bin/python" ]]; then
    python_bin="$BASE_DIR/.venv/bin/python"
else
    python_bin="python3"
fi
command -v "$python_bin" >/dev/null
"$python_bin" -c 'import pandas, yaml, steampy'

for file in config/config.yaml config/secrets.yaml data/STC_set_data_sort.csv; do
    if [[ ! -r "$file" ]]; then
        echo "Missing or unreadable file: $file"
        exit 1
    fi
done

nohup "$python_bin" -u "$BASE_DIR/main.py" >> logs/console.log 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > .run/main.pid
sleep 1
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f .run/main.pid
    echo "Process exited during startup. Check logs/console.log and logs/error.log."
    exit 1
fi
echo "Started (PID $pid). Logs: $BASE_DIR/logs/console.log"
