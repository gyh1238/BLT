#!/usr/bin/env bash
# init_n_validators.sh - bootstrap an N-validator leo_chain-1 testnet.
#
# Usage:
#   ./scripts/init_n_validators.sh [N]   # defaults to 12
#
# Lays down N independent node homes under $TESTNET_DIR (default
# ~/.leochain-testnet/v{i}) with:
#   - chain_id   = leo_chain-1
#   - denom      = leo
#   - 100000000leo bonded per validator
#   - app_state.blt.initial_delegates populated for all N (cluster_id i,
#     head_id 100+i, validator address from the gentx)
#   - config.toml consensus timeouts patched to 3500ms (spec §IV.A)
#   - p2p/rpc ports stepped by 10 (26656/26657 for v0)
#   - persistent_peers wired full-mesh
#
# Requires: jq, leochaind in $PATH.

set -euo pipefail

N=${1:-12}
CHAIN_ID="leo_chain-1"
DENOM="leo"
STAKE_PER_VALIDATOR="100000000${DENOM}"
SUPPLY_PER_VALIDATOR="200000000${DENOM}"
TESTNET_DIR="${TESTNET_DIR:-$HOME/.leochain-testnet}"
KEYRING="${KEYRING:-test}"

if ! command -v jq >/dev/null 2>&1; then
  echo "error: jq is required" >&2; exit 1
fi
if ! command -v leochaind >/dev/null 2>&1; then
  echo "error: leochaind not in PATH" >&2; exit 1
fi

echo ">> wiping $TESTNET_DIR"
rm -rf "$TESTNET_DIR"
mkdir -p "$TESTNET_DIR"

echo ">> initializing $N validator homes"
for i in $(seq 0 $((N-1))); do
  HOME_I="$TESTNET_DIR/v$i"
  leochaind init "v$i" --chain-id "$CHAIN_ID" --home "$HOME_I" --default-denom "$DENOM" >/dev/null 2>&1
done

echo ">> creating keys + funding accounts on v0"
V0_HOME="$TESTNET_DIR/v0"
declare -a ADDRS=()
for i in $(seq 0 $((N-1))); do
  HOME_I="$TESTNET_DIR/v$i"
  KEYNAME="v$i"
  leochaind keys add "$KEYNAME" --keyring-backend "$KEYRING" --home "$HOME_I" --output json \
    >"$HOME_I/key.json" 2>/dev/null
  ADDR=$(jq -r '.address' "$HOME_I/key.json")
  ADDRS+=("$ADDR")
  leochaind genesis add-genesis-account "$ADDR" "$SUPPLY_PER_VALIDATOR" \
    --home "$V0_HOME" --keyring-backend "$KEYRING" >/dev/null
done

echo ">> gentx per validator"
declare -a VALOPER_ADDRS=()
for i in $(seq 0 $((N-1))); do
  HOME_I="$TESTNET_DIR/v$i"
  # mirror v0's genesis (with all accounts funded) into vi so its gentx validates locally
  if [ "$i" -ne 0 ]; then
    cp "$V0_HOME/config/genesis.json" "$HOME_I/config/genesis.json"
  fi
  # the gentx needs vi's local keyring; vi already has its own key from above
  leochaind genesis gentx "v$i" "$STAKE_PER_VALIDATOR" \
    --chain-id "$CHAIN_ID" --keyring-backend "$KEYRING" \
    --home "$HOME_I" --output-document "$HOME_I/gentx.json" >/dev/null 2>&1
  VALOPER=$(jq -r '.body.messages[0].validator_address' "$HOME_I/gentx.json")
  VALOPER_ADDRS+=("$VALOPER")
done

echo ">> collecting gentxs into v0"
mkdir -p "$V0_HOME/config/gentx"
for i in $(seq 0 $((N-1))); do
  cp "$TESTNET_DIR/v$i/gentx.json" "$V0_HOME/config/gentx/gentx-v$i.json"
done
leochaind genesis collect-gentxs --home "$V0_HOME" >/dev/null 2>&1

echo ">> patching app_state.blt.initial_delegates ($N entries)"
DELEGATES_JSON=$(jq -n --argjson n "$N" \
  --argjson valopers "$(printf '%s\n' "${VALOPER_ADDRS[@]}" | jq -R . | jq -s .)" \
  '[range(0; $n) | {
       cluster_id: .,
       head_id: (100 + .),
       validator_address: $valopers[.]
   }]')

TMP_GEN="$V0_HOME/config/genesis.json.tmp"
jq --argjson n "$N" --argjson delegates "$DELEGATES_JSON" '
  .app_state.blt.params.cluster_count = $n
  | .app_state.blt.initial_delegates.delegates = $delegates
' "$V0_HOME/config/genesis.json" >"$TMP_GEN"
mv "$TMP_GEN" "$V0_HOME/config/genesis.json"

echo ">> distributing finalized genesis to v1..v$((N-1))"
for i in $(seq 1 $((N-1))); do
  cp "$V0_HOME/config/genesis.json" "$TESTNET_DIR/v$i/config/genesis.json"
done

echo ">> patching consensus timeouts (3500ms) and ports per validator"
for i in $(seq 0 $((N-1))); do
  HOME_I="$TESTNET_DIR/v$i"
  CFG="$HOME_I/config/config.toml"
  APP="$HOME_I/config/app.toml"
  P2P_PORT=$((26656 + 10 * i))
  RPC_PORT=$((26657 + 10 * i))
  PROXY_PORT=$((26658 + 10 * i))
  API_PORT=$((1317 + 10 * i))
  GRPC_PORT=$((9090 + 10 * i))
  GRPCW_PORT=$((9091 + 10 * i))
  sed -i "s|^timeout_commit = .*|timeout_commit = \"3500ms\"|" "$CFG"
  sed -i "s|^timeout_propose = .*|timeout_propose = \"1000ms\"|" "$CFG"
  sed -i "s|^timeout_prevote = .*|timeout_prevote = \"500ms\"|" "$CFG"
  sed -i "s|^timeout_precommit = .*|timeout_precommit = \"500ms\"|" "$CFG"
  sed -i "s|^laddr = \"tcp://0.0.0.0:26656\"|laddr = \"tcp://0.0.0.0:$P2P_PORT\"|" "$CFG"
  sed -i "s|^laddr = \"tcp://127.0.0.1:26657\"|laddr = \"tcp://0.0.0.0:$RPC_PORT\"|" "$CFG"
  sed -i "s|^proxy_app = \"tcp://127.0.0.1:26658\"|proxy_app = \"tcp://127.0.0.1:$PROXY_PORT\"|" "$CFG"
  # app.toml ports
  sed -i "s|^address = \"tcp://localhost:1317\"|address = \"tcp://0.0.0.0:$API_PORT\"|" "$APP"
  sed -i "s|^address = \"localhost:9090\"|address = \"0.0.0.0:$GRPC_PORT\"|" "$APP"
  sed -i "s|^address = \"localhost:9091\"|address = \"0.0.0.0:$GRPCW_PORT\"|" "$APP"
  # enable API for queries
  sed -i 's|^enable = false$|enable = true|' "$APP"
  # required by Cosmos SDK v0.50 — set a non-empty min gas price
  sed -i "s|^minimum-gas-prices = \"\"|minimum-gas-prices = \"0${DENOM}\"|" "$APP"
done

echo ">> wiring persistent_peers full mesh"
declare -a PEER_IDS=()
for i in $(seq 0 $((N-1))); do
  HOME_I="$TESTNET_DIR/v$i"
  PEER_ID=$(leochaind comet show-node-id --home "$HOME_I")
  PEER_IDS+=("$PEER_ID")
done
for i in $(seq 0 $((N-1))); do
  HOME_I="$TESTNET_DIR/v$i"
  CFG="$HOME_I/config/config.toml"
  PEERS=""
  for j in $(seq 0 $((N-1))); do
    [ "$j" = "$i" ] && continue
    P2P_PORT=$((26656 + 10 * j))
    PEERS+="${PEER_IDS[$j]}@127.0.0.1:${P2P_PORT},"
  done
  PEERS=${PEERS%,}
  sed -i "s|^persistent_peers = \".*\"|persistent_peers = \"$PEERS\"|" "$CFG"
  sed -i 's|^allow_duplicate_ip = false|allow_duplicate_ip = true|' "$CFG"
done

echo "✓ $N validator homes ready under $TESTNET_DIR"
echo "  start with: ./scripts/start_local.sh $N"
