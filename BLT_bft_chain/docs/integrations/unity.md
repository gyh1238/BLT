# Unity Digital Twin ↔ leo_chain-1 Integration

This document describes the RPC contract between the Unity digital twin's
`BlockchainPoller.cs` and the `leochaind` node.

## RPC endpoints

The legacy poller already targets:

| Endpoint | Purpose |
|----------|---------|
| `GET /status` | Sync info, current height, chain_id (`leo_chain-1`). |
| `GET /block?height=H` | Full block at height `H` (JSON). |

These continue to work with the new chain. The block JSON contains
zero or one tx; when present, `tx[0]` is a base64-encoded
`MsgCommitSyncBlock` from `x/blt`. Decoding requires the
`leochain.blt.MsgCommitSyncBlock` proto type and a base64 decode.

## Recommended new convenience endpoint

To avoid client-side tx parsing, poll the ABCI query directly:

```
GET /abci_query?path=%22/leochain.blt.Query/LatestEpoch%22&data=0x
```

The response is a JSON envelope with `result.response.value` carrying the
binary `QueryLatestEpochResponse`. The Cosmos SDK convention is to wrap
that value as base64 and decode it on the client. Alternative HTTP
endpoint (via the REST gateway, port 1317 by default):

```
GET http://<node>:1317/leochain/blt/latest_epoch
```

The REST gateway returns the proto as JSON directly, which is the path
of least friction for Unity.

## Other useful gRPC-gateway routes (port 1317)

- `GET /leochain/blt/params`
- `GET /leochain/blt/delegate_set`
- `GET /leochain/blt/epoch_history/{epoch_id}`

## Polling guidance

- Poll the convenience endpoint at ~1 Hz (do **not** align with the 3.5 s
  block interval).
- Treat `code != 0` with log `"no latest epoch committed yet"` as the
  legitimate pre-bootstrap state, not an error.
- The base64-encoded `relay_path_hash` in `BltEpochSnapshot` is always
  32 bytes — if it is missing or shorter, fail loudly.

## Local sanity check

```bash
./scripts/init_n_validators.sh 4
./scripts/start_local.sh 4
./scripts/check_unity_rpc.sh           # exits 0 when /status, /block, and ABCI LatestEpoch all respond
./scripts/start_local.sh stop
```
