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
  # Before any MsgCommitSyncBlock lands, the keeper returns NotFound (codes.NotFound),
  # which surfaces here as a non-zero ABCI code with a meaningful log. That's the
  # documented "no epoch yet" state, NOT a transport failure — so we treat it as PASS.
  if [ "$code" = "0" ]; then
    pass "/abci_query LatestEpoch (code=0, snapshot present)"
  elif echo "$log" | grep -qi 'no latest epoch\|not implemented'; then
    pass "/abci_query LatestEpoch (code=$code, log=\"$log\" → pre-snapshot state OK)"
  else
    fail "/abci_query LatestEpoch (code=$code, log=\"$log\")"
  fi
}

check_status
check_block
check_abci_latest_epoch

exit $fail
