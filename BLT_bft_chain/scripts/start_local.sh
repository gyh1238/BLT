#!/usr/bin/env bash
# start_local.sh - launch N already-initialized validators in the background.
#
# Usage:
#   ./scripts/start_local.sh [N]          # defaults to 12
#   ./scripts/start_local.sh stop         # kill all running leochaind processes
#
# Each node logs to $TESTNET_DIR/v{i}.log. PIDs are recorded in
# $TESTNET_DIR/pids so the helper can stop them cleanly.

set -euo pipefail

TESTNET_DIR="${TESTNET_DIR:-$HOME/.leochain-testnet}"

case "${1:-}" in
  stop)
    if [ -f "$TESTNET_DIR/pids" ]; then
      while read -r pid; do
        kill "$pid" 2>/dev/null || true
      done <"$TESTNET_DIR/pids"
      rm -f "$TESTNET_DIR/pids"
      echo "✓ stopped"
    fi
    exit 0
    ;;
esac

N=${1:-12}

if [ ! -d "$TESTNET_DIR/v0" ]; then
  echo "error: $TESTNET_DIR/v0 not initialized. run scripts/init_n_validators.sh first." >&2
  exit 1
fi

: >"$TESTNET_DIR/pids"
for i in $(seq 0 $((N-1))); do
  HOME_I="$TESTNET_DIR/v$i"
  LOG="$TESTNET_DIR/v$i.log"
  nohup leochaind start --home "$HOME_I" --log_level info >"$LOG" 2>&1 &
  echo "$!" >>"$TESTNET_DIR/pids"
  echo "  v$i pid=$! log=$LOG"
done
echo "✓ $N nodes started. Tail logs: tail -f $TESTNET_DIR/v0.log"
