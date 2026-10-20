#!/usr/bin/env bash
# Stop validators one at a time and measure what the chain can still do.
#
# Validator faults belong reported as the availability of a valid agreed state,
# not as RMSE. RMSE answers a different question: it says how
# far clocks drifted, which on a halted chain is a consequence rather than the
# finding. What matters when validators go down is whether a sync epoch still
# commits, how long it takes, and whether the surviving nodes agree.
#
# So this reports, per number of halted validators:
#
#   committed     did a submitted MsgCommitSyncBlock reach code=0
#   latency       submit -> committed, seconds
#   agreement     do all surviving nodes report the same epoch and reference
#   height moving is the chain producing blocks at all
#
# With N validators of equal voting power, CometBFT needs more than 2/3 of the
# power online. At N=4 that is 3, so halting 2 must stop block production, the
# expected result, and the one that distinguishes "consensus stopped safely"
# from "consensus committed something wrong".
#
# Usage: validator_halt.sh [N]        (default 4)
#   env: TESTNET_DIR, SCRATCH (where the unsigned tx template lives)
set -uo pipefail

N="${1:-4}"
TESTNET_DIR="${TESTNET_DIR:-$HOME/.leochain-testnet}"
SCRATCH="${SCRATCH:-/tmp}"
CHAIN_ID="leo_chain-1"

rpc_port() { echo $((26657 + 10 * $1)); }

node_height() {
  curl -fsS --max-time 4 "http://localhost:$(rpc_port "$1")/status" 2>/dev/null |
    jq -r '.result.sync_info.latest_block_height // empty'
}

node_epoch() {
  leochaind query blt latest-epoch --node "tcp://localhost:$(rpc_port "$1")" \
    --output json 2>/dev/null |
    jq -r '"\(.snapshot.epoch_id)/\(.snapshot.body.global.global_ref_time_q01ns)"' 2>/dev/null
}

# Submit one sync block from v0, timed. Echoes "code latency".
submit_epoch() {
  local epoch=$1 t0 bt ref code h elapsed
  bt=$(curl -fsS --max-time 4 "http://localhost:26657/status" 2>/dev/null |
       jq -r '.result.sync_info.latest_block_time // empty')
  [ -z "$bt" ] && { echo "- -"; return; }
  ref=$(python -c "
import sys,re,datetime as d
bt=re.sub(r'\.(\d{6})\d*', r'.\1', '$bt').replace('Z','+00:00')
print(int((int(d.datetime.fromisoformat(bt).timestamp()*1e9)-1735689600000000000)*10))")
  python -c "
import json,io
t=json.load(io.open('$SCRATCH/unsigned.json'))
m=t['body']['messages'][0]
m['body']['global']['global_ref_time_q01ns']='$ref'
m['epoch_id']=$epoch
json.dump(t, io.open('$SCRATCH/unsigned.json','w'))"
  leochaind tx sign "$SCRATCH/unsigned.json" --from v0 --keyring-backend test \
    --home "$TESTNET_DIR/v0" --chain-id "$CHAIN_ID" --node tcp://localhost:26657 \
    --output-document "$SCRATCH/signed.json" >/dev/null 2>&1 || { echo "- -"; return; }

  t0=$(date +%s.%N)
  h=$(leochaind tx broadcast "$SCRATCH/signed.json" --node tcp://localhost:26657 \
        --output json 2>/dev/null | jq -r '.txhash // empty')
  [ -z "$h" ] && { echo "- -"; return; }
  code="-"
  for _ in $(seq 1 40); do
    sleep 0.5
    local q; q=$(leochaind query tx "$h" --node tcp://localhost:26657 --output json 2>/dev/null)
    if [ -n "$q" ] && echo "$q" | jq -e . >/dev/null 2>&1; then
      code=$(echo "$q" | jq -r '.code'); break
    fi
  done
  elapsed=$(python -c "print(f'{$(date +%s.%N) - $t0:.2f}')")
  echo "$code $elapsed"
}

echo "validator halt sweep: N=$N, quorum needs more than 2/3 of voting power online"
printf "\n%8s %9s %9s %9s %10s  %s\n" "halted" "online" "committed" "latency" "blocks" "agreement"
printf "%s\n" "--------------------------------------------------------------------------"

# One throwaway submission first. The account sequence is not usable until the
# signer's first tx has been through a block, and a baseline row that fails for
# that reason says nothing about halting validators.
epoch=200
submit_epoch "$epoch" >/dev/null
sleep 5

for halt in $(seq 0 $((N - 1))); do
  # Halt validators v(N-1) downward, leaving v0 (the submitter) up.
  if [ "$halt" -gt 0 ]; then
    idx=$((N - halt))
    pid=$(sed -n "$((idx + 1))p" "$TESTNET_DIR/pids" 2>/dev/null)
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
    sleep 6
  fi

  h_before=$(node_height 0)
  epoch=$((epoch + 1))
  read -r code latency < <(submit_epoch "$epoch")
  sleep 4
  h_after=$(node_height 0)

  blocks="stalled"
  [ -n "$h_before" ] && [ -n "$h_after" ] && [ "$h_after" -gt "$h_before" ] && blocks="moving"

  # Do the surviving nodes report the same state?
  agree="n/a"
  first=""; same="yes"
  for i in $(seq 0 $((N - halt - 1))); do
    e=$(node_epoch "$i")
    [ -z "$first" ] && first="$e"
    [ "$e" != "$first" ] && same="no"
  done
  [ -n "$first" ] && agree="$same ($((N - halt)) nodes)"

  committed="no"
  [ "$code" = "0" ] && committed="yes"
  [ "$code" = "-" ] && committed="no-reply"

  printf "%8s %9s %9s %9s %10s  %s\n" \
    "$halt" "$((N - halt))" "$committed" "$latency" "$blocks" "$agree"
done

echo
echo "A row with blocks=stalled and committed=no is consensus stopping safely:"
echo "no quorum, so nothing commits. A row that commits while below quorum would"
echo "be the serious finding, and none is expected."
