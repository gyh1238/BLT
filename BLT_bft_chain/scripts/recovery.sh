#!/usr/bin/env bash
# Disconnect a node for N sync rounds, reconnect it, and measure what recovery costs.
#
# The question is what the history chain buys that a single authenticated
# snapshot would not. The honest way to answer is to disconnect a node, keep the
# swarm committing while it is away, and then watch what the node has to do to
# come back, rather than describing the mechanism and asserting it helps.
#
# Reported per gap length:
#
#   committed      sync epochs that actually committed while the node was down
#   missed_heights blocks it has to replay
#   recovery_s     reconnect -> caught up with the chain head
#   bytes_rx       on-disk growth during catch-up. Reported as n/a when the
#                  delta is negative: compaction can shrink the data directory
#                  during the same window, and a negative "bytes received" is
#                  not a measurement of anything.
#   adopted_epoch  the epoch id it holds once caught up
#   replayed       epochs the reconnected node can enumerate over the gap via
#                  the height index (`query blt epoch-history-range`), over the
#                  epochs that actually committed during the gap
#
# The last column is the one that separates the two designs. A node holding only
# the latest authenticated state can accept the head and stop there; it cannot
# answer what happened while it was away. A node with the chain can walk the gap
# and verify each step.
#
# Three constraints the chain puts on a script that commits epochs by hand:
#
#   1. epoch_id is a u8 on the wire, so ids must stay inside 0..255. They start
#      at EPOCH_BASE and the script refuses a sweep that would pass 255; past
#      it every commit is rejected with code 18.
#   2. global_ref_time is checked against the including block's time, not the
#      one the transaction was built from, and signing and broadcasting take
#      seconds. A fixed lead cannot cover that, since the offset depends on
#      block production, so the lead self-calibrates: R2's rejection reports
#      the skew it measured, the script folds that into the lead and retries,
#      and the remaining commits land first time.
#   3. leochaind failures are printed with their code and log line. A run that
#      silently discarded them would look quiet rather than broken.
#
# Do not wrap this script in a pipe (`| tail`): that buffers the whole run and
# a long sweep then looks like a hang with an empty output file.
#
# Usage: recovery.sh [gap_rounds ...]     default: 1 5 10
#   env: TESTNET_DIR, SCRATCH, REF_LEAD_S, EPOCH_BASE, COMMIT_TRIES
set -uo pipefail

GAPS=${*:-"1 5 10"}
TESTNET_DIR="${TESTNET_DIR:-$HOME/.leochain-testnet}"
SCRATCH="${SCRATCH:-${TMPDIR:-/tmp}/blt_scratch}"     # override with SCRATCH=...
CHAIN_ID="leo_chain-1"
VICTIM=3                       # the node we disconnect; v0 stays as submitter
REF_LEAD_S="${REF_LEAD_S:-0}"  # starting lead; self-calibrates, see note 2
LEAD=$REF_LEAD_S               # current calibrated lead, in seconds
COMMIT_TRIES="${COMMIT_TRIES:-3}"
EPOCH_BASE="${EPOCH_BASE:-20}" # u8 range; see note 1 above

rpc() { echo "tcp://localhost:$((26657 + 10 * $1))"; }
http() { echo "http://localhost:$((26657 + 10 * $1))"; }

height() {
  curl -fsS --max-time 4 "$(http "$1")/status" 2>/dev/null |
    jq -r '.result.sync_info.latest_block_height // empty'
}

epoch_of() {
  leochaind query blt latest-epoch --node "$(rpc "$1")" --output json 2>/dev/null |
    jq -r '.snapshot.epoch_id // empty'
}

data_bytes() { du -sb "$TESTNET_DIR/v$1/data" 2>/dev/null | cut -f1; }

# Epochs the node can enumerate over a height window, through the height index.
# This is the query a rejoining node uses: epoch_id wraps every 256 rounds, so a
# long gap cannot be walked by id at all.
replayed_over() {
  local node=$1 from=$2 to=$3
  leochaind query blt epoch-history-range "$from" "$to" --node "$(rpc "$node")" \
    --output json 2>/dev/null | jq -r '.snapshots | length'
}

# Submit one epoch once, with the current lead. Echoes "ok", or "skew=<ns>" when
# R2 rejected it for a reference offset, or "fail" otherwise.
submit_epoch() {
  local epoch=$1 ref h code raw skew
  ref=$(python -c "
import datetime as d
now = d.datetime.now(d.timezone.utc).timestamp()
print(int((int((now + $LEAD) * 1e9) - 1735689600000000000) * 10))")
  python -c "
import json, io
t = json.load(io.open('$SCRATCH/unsigned.json'))
m = t['body']['messages'][0]
m['body']['global']['global_ref_time_q01ns'] = '$ref'
m['epoch_id'] = $epoch
json.dump(t, io.open('$SCRATCH/unsigned.json', 'w'))" || { echo "fail"; return; }

  leochaind tx sign "$SCRATCH/unsigned.json" --from v0 --keyring-backend test \
    --home "$TESTNET_DIR/v0" --chain-id "$CHAIN_ID" --node "$(rpc 0)" \
    --output-document "$SCRATCH/signed.json" >/dev/null 2>&1 || { echo "fail"; return; }

  h=$(leochaind tx broadcast "$SCRATCH/signed.json" --node "$(rpc 0)" \
        --output json 2>/dev/null | jq -r '.txhash // empty')
  [ -z "$h" ] && { echo "fail"; return; }

  for _ in $(seq 1 40); do
    sleep 0.5
    raw=$(leochaind query tx "$h" --node "$(rpc 0)" --output json 2>/dev/null)
    code=$(echo "$raw" | jq -r '.code // empty')
    [ -n "$code" ] && break
  done
  if [ "$code" = "0" ]; then echo "ok"; return; fi

  # R2 reports exactly how far off the reference was. Positive skew means the
  # claim ran ahead of the including block.
  skew=$(echo "$raw" | jq -r '.raw_log // ""' | grep -o 'skew=-\?[0-9]\+' | head -1 | cut -d= -f2)
  if [ "$code" = "1112" ] && [ -n "$skew" ]; then
    echo "skew=$skew"
    return
  fi
  echo "  ! epoch $epoch: code=${code:-timeout} $(echo "$raw" | jq -r '.raw_log // "no log"' | head -c 160)" >&2
  echo "fail"
}

# Commit one sync epoch, calibrating the reference lead against R2's own
# measurement. Echoes the committed epoch id, or nothing.
commit_epoch() {
  local epoch=$1 r skew
  for _ in $(seq 1 "$COMMIT_TRIES"); do
    r=$(submit_epoch "$epoch")
    case "$r" in
      ok) echo "$epoch"; return ;;
      skew=*)
        skew=${r#skew=}
        # Fold the measured offset into the lead: subtracting it aims the next
        # claim at the time of the block that will include it.
        LEAD=$(python -c "print(round($LEAD - $skew / 1e9, 3))")
        echo "  ~ epoch $epoch: reference off by $(python -c "print(round($skew/1e9,2))")s, lead -> ${LEAD}s" >&2
        ;;
      *) return ;;
    esac
  done
  echo "  ! epoch $epoch: still rejected after $COMMIT_TRIES tries (lead ${LEAD}s)" >&2
}

# --- refuse to run a sweep that would leave the u8 range -------------------
total=0
for gap in $GAPS; do total=$((total + gap)); done
if [ $((EPOCH_BASE + total * COMMIT_TRIES)) -gt 255 ]; then
  echo "error: EPOCH_BASE $EPOCH_BASE + $total rounds passes the u8 epoch_id limit (255)." >&2
  echo "       lower EPOCH_BASE or shorten the sweep." >&2
  exit 1
fi

echo "recovery sweep: node v$VICTIM disconnected for N committed sync rounds"
echo "epoch ids from $((EPOCH_BASE + 1)), reference lead self-calibrating from ${REF_LEAD_S}s"
printf "\n%10s %9s %10s %11s %12s %9s\n" \
  "committed" "missed_h" "recovery_s" "bytes_rx" "adopted_ep" "replayed"
printf "%s\n" "--------------------------------------------------------------------------"

epoch=$EPOCH_BASE
for gap in $GAPS; do
  # --- take the node down ------------------------------------------------
  pid=$(sed -n "$((VICTIM + 1))p" "$TESTNET_DIR/pids" 2>/dev/null)
  h_down=$(height "$VICTIM")
  b_down=$(data_bytes "$VICTIM")
  [ -n "$pid" ] && kill "$pid" 2>/dev/null
  sleep 4

  # --- commit `gap` epochs while it is away -------------------------------
  committed=0
  for _ in $(seq 1 "$gap"); do
    epoch=$((epoch + 1))
    got=$(commit_epoch "$epoch")
    [ -n "$got" ] && committed=$((committed + 1))
    sleep 1
  done

  h_head=$(height 0)

  # --- bring it back and time the catch-up --------------------------------
  ( cd "$TESTNET_DIR" && nohup leochaind start --home "$TESTNET_DIR/v$VICTIM" \
      --log_level info >"$TESTNET_DIR/v$VICTIM.log" 2>&1 & echo $! >>"$TESTNET_DIR/pids" )
  t0=$(date +%s.%N)
  recovered="-"
  for _ in $(seq 1 60); do
    sleep 1
    hv=$(height "$VICTIM")
    h0=$(height 0)
    if [ -n "$hv" ] && [ -n "$h0" ] && [ "$hv" -ge "$((h0 - 1))" ]; then
      recovered=$(python -c "print(f'{$(date +%s.%N) - $t0:.1f}')"); break
    fi
  done

  b_up=$(data_bytes "$VICTIM")
  rx="n/a"
  if [ -n "$b_up" ] && [ -n "$b_down" ] && [ "$b_up" -gt "$b_down" ]; then
    rx=$(python -c "print(f'{($b_up - $b_down)/1024:.0f} KiB')")
  fi
  missed="-"
  [ -n "$h_head" ] && [ -n "$h_down" ] && missed=$((h_head - h_down))
  adopted=$(epoch_of "$VICTIM")

  # --- can it enumerate the epochs committed during the gap? --------------
  replayed="-"
  if [ -n "$h_down" ] && [ -n "$h_head" ]; then
    n=$(replayed_over "$VICTIM" "$h_down" "$h_head")
    [ -z "$n" ] && n=0
    replayed="$n/$committed"
  fi

  printf "%10s %9s %10s %11s %12s %9s\n" \
    "$committed" "$missed" "$recovered" "$rx" "${adopted:--}" "$replayed"
done

echo
echo "replayed = epochs the reconnected node can enumerate over the gap's height"
echo "window / epochs that actually committed during it. Equal means the node can"
echo "reconstruct what it missed rather than only adopting the head; a design"
echo "keeping the latest state alone would show 0 for any gap."
