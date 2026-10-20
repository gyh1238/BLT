#!/usr/bin/env bash
# check_unity_rpc.sh - smoke-tests the RPC endpoints the Unity digital
# twin's BlockchainPoller.cs hits, plus the recommended x/blt convenience
# query. Pass/fail per endpoint, non-zero exit if any required endpoint
# is broken.
#
# Usage:
#   ./scripts/check_unity_rpc.sh [rpc_url]
# Defaults to http://localhost:26657.

set -uo pipefail

RPC="${1:-http://localhost:26657}"
fail=0

green() { printf "\033[32m%s\033[0m" "$1"; }
red()   { printf "\033[31m%s\033[0m" "$1"; }

pass() { printf "[%s] %s\n" "$(green PASS)" "$1"; }
fail() { printf "[%s] %s\n" "$(red FAIL)" "$1"; fail=1; }

check_status() {
  local body
  body=$(curl -fsS "$RPC/status" 2>/dev/null || true)
  if [ -z "$body" ]; then
    fail "/status returned no body"; return
  fi
  local chain h
  chain=$(echo "$body" | jq -r '.result.node_info.network // empty')
  h=$(echo "$body" | jq -r '.result.sync_info.latest_block_height // empty')
  if [ "$chain" = "leo_chain-1" ] && [ -n "$h" ] && [ "$h" -gt 0 ]; then
    pass "/status (chain=$chain, height=$h)"
  else
    fail "/status (chain=$chain, height=$h)"
  fi
}

check_block() {
  local body
  body=$(curl -fsS "$RPC/block?height=1" 2>/dev/null || true)
  if [ -z "$body" ]; then fail "/block?height=1 returned no body"; return; fi
  local hash
  hash=$(echo "$body" | jq -r '.result.block_id.hash // empty')
  if [ -n "$hash" ]; then
    pass "/block?height=1 (hash=${hash:0:16}...)"
  else
    fail "/block?height=1 missing block_id.hash"
  fi
}

check_abci_latest_epoch() {
  # x/blt convenience query; bypasses tx parsing for the Unity client.
  local body
  body=$(curl -fsS "$RPC/abci_query?path=%22/leochain.blt.Query/LatestEpoch%22&data=0x" 2>/dev/null || true)
  if [ -z "$body" ]; then fail "/abci_query LatestEpoch returned no body"; return; fi
  local code log
  code=$(echo "$body" | jq -r '.result.response.code // 0')
  log=$(echo "$body"  | jq -r '.result.response.log  // ""')
  # Before any MsgCommitSyncBlock lands, the keeper returns NotFound, which
  # surfaces as a non-zero ABCI code with a meaningful log. That is the
  # documented "no epoch yet" state and not a transport failure.
  #
  # "not implemented" is NOT that state. It means the query handler is not
  # wired, i.e. the thing being smoke-tested does not exist, treating it as a
  # pass let a chain with no working LatestEpoch query report healthy.
  if [ "$code" = "0" ]; then
    pass "/abci_query LatestEpoch (code=0, snapshot present)"
  elif echo "$log" | grep -qi 'not implemented'; then
    fail "/abci_query LatestEpoch handler is not wired (log=\"$log\")"
  elif echo "$log" | grep -qi 'no latest epoch'; then
    pass "/abci_query LatestEpoch (code=$code, pre-snapshot state)"
  else
    fail "/abci_query LatestEpoch (code=$code, log=\"$log\")"
  fi
}

# A rising block height proves the chain is alive, not that synchronization is
# working: empty blocks advance the height while the epoch stands still. This
# watches both across several block intervals and reports them apart.
#
# The window matters. A sync epoch commits when a proposer submits, which is not
# necessarily every block, so demanding a change within one block reports a
# healthy chain as broken. EPOCH_WATCH_S covers several block intervals at the
# default 3.5 s cadence.
EPOCH_WATCH_S="${EPOCH_WATCH_S:-16}"

check_epoch_advances() {
  local h0 e0 h1 e1 waited moved
  h0=$(curl -fsS "$RPC/status" 2>/dev/null | jq -r '.result.sync_info.latest_block_height // empty')
  e0=$(epoch_id)
  waited=0
  moved=0
  h1="$h0"
  e1="$e0"
  while [ "$waited" -lt "$EPOCH_WATCH_S" ]; do
    sleep 2; waited=$((waited + 2))
    h1=$(curl -fsS "$RPC/status" 2>/dev/null | jq -r '.result.sync_info.latest_block_height // empty')
    e1=$(epoch_id)
    if [ -n "$e1" ] && [ "$e1" != "$e0" ]; then moved=1; break; fi
  done

  if [ -z "$h1" ] || [ "$h1" = "$h0" ]; then
    fail "block height did not advance in ${waited}s (chain stalled)"
  elif [ -z "$e1" ]; then
    pass "height $h0 -> $h1 in ${waited}s, no epoch committed yet (chain alive, sync idle)"
  elif [ "$moved" = "1" ]; then
    pass "height $h0 -> $h1 AND the epoch advanced within ${waited}s"
  else
    fail "height $h0 -> $h1 over ${waited}s but the epoch never changed: blocks are being produced without committing a sync epoch"
  fi
}

# Current epoch id, or empty when no snapshot exists yet.
epoch_id() {
  curl -fsS "$RPC/abci_query?path=%22/leochain.blt.Query/LatestEpoch%22&data=0x" 2>/dev/null |
    jq -r 'if (.result.response.code // 0) == 0
           then (.result.response.value // "") else "" end' 2>/dev/null
}

check_status
check_block
check_abci_latest_epoch
check_epoch_advances

exit $fail
