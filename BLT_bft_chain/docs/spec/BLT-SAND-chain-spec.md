# BLT-SAND chain specification

What the `blt` module is and how a synchronization epoch is admitted, committed and read back.
[`../../readme.md`](../../readme.md) is the shorter route: what the module does, the admission
rules against the attacks that exercise them, and how to run the chain and reproduce the
measurements.

## 1. Tech Stack

| Item | Choice | Reason |
|------|--------|--------|
| Scaffolding | **Ignite CLI v28.x** | Fast module/message generation |
| Cosmos SDK | **v0.50.x** | Bundled with CometBFT v0.38 (stable) |
| Consensus | **CometBFT** (formerly Tendermint Core) | Matches paper §IV.A wording |
| Language | Go 1.25 (`go.mod`) | Cosmos SDK standard |
| Proto codegen | buf | Ignite default |
| Target OS | Linux amd64/arm64 (deploy), Linux/Windows (dev) | |

---

## 2. Chain Parameters

```yaml
chain_id: leo_chain-1
denom: leo
address_prefix: cosmos                # Keep cosmos1... addresses

consensus:
  timeout_commit: 3500ms              # demo default; the paper runs a 6 s interval
  timeout_propose: 1000ms
  timeout_prevote: 500ms
  timeout_precommit: 500ms

genesis_validators: 12                # Paper Fig.4 "CLUSTERS 12/12" and §IV.A "12 clusters"

hash_algorithm: SHA-256               # Paper §III.A
quorum: more than 2/3 (= 9 of 12)     # CometBFT's rule, unmodified
```

---

## 3. BLT-SAND ↔ Cosmos SDK Layer Mapping

| BLT-SAND spec field | Implementation location | Notes |
|---------------------|------------------------|-------|
| `header.version, height, timestamp, prev_block_hash, body_hash, proposer_id, header_sig` | Auto-generated CometBFT block header | Use as-is |
| `header.delegate_set_hash` | CometBFT `ValidatorsHash` | Equivalent |
| `header.epoch_id` | Field inside `MsgCommitSyncBlock.body.global` | Cluster re-computation epoch |
| `header.nonce` | CometBFT block hash already serves this role | No separate field needed |
| `header.relay_path_hash` | Dedicated field in `MsgCommitSyncBlock` | h-PBFT relay path |
| `body global, cluster_table, member_table` | `MsgCommitSyncBlock` tx payload (protobuf) | One tx per block |
| `offset_report message` | **Off-chain** (intra-cluster TWTT) | Not on the blockchain |
| `propose_block, prepare_vote, commit_vote, vote_bundle` | Handled internally by CometBFT consensus | No code needed |
| `vote_evidence` | CometBFT `LastCommit` + commit signatures | Equivalent |

**Key insight**: The only custom code we must write is the `x/blt` module that handles `MsgCommitSyncBlock`. Everything else is provided by Cosmos SDK and CometBFT.

---

## 4. Custom Module: `x/blt`

### 4.1 Responsibilities
- Define and validate the `MsgCommitSyncBlock` message.
- Persist the latest synchronization state in the KV store (for queries).
- Emit events (block committed, ref_time updated) for the Unity dashboard.

### 4.2 State (KV store)

| Key | Type | Description |
|-----|------|-------------|
| `params` | `BltParams` | Epoch length, cluster_count, safety limits |
| `latest_epoch` | `BltEpochSnapshot` | Most recent finalized body (full) |
| `epoch_history/{epoch_id}` | `BltEpochSnapshot` | Past epochs (paper §III.A: "Historical timing information is preserved as metadata") |
| `delegate_set` | `BltDelegateSet` | Current round's 12 cluster heads (validators) |

### 4.3 Protobuf Messages

```protobuf
syntax = "proto3";
package leochain.blt;

// One tx per block. Submitted by the current block proposer (a rotating cluster head).
message MsgCommitSyncBlock {
  string proposer = 1;                    // cosmos1... bech32 address
  BltBlockBody body = 2;
  bytes relay_path_hash = 3;              // 32 bytes, corresponds to header.relay_path_hash
  uint32 epoch_id = 4;                    // u8 range, corresponds to header.epoch_id
}

message MsgCommitSyncBlockResponse {
  uint64 global_ref_time_q01ns = 1;       // confirmation echo
}

message BltBlockBody {
  BltBodyGlobal global = 1;
  repeated BltClusterSummary cluster_table = 2;
  repeated BltMemberRecord member_table = 3;
}

message BltBodyGlobal {
  uint64 global_ref_time_q01ns = 1;       // u64, units of 0.1 ns
  uint32 cluster_count = 2;               // u8 semantic range
  uint32 member_count = 3;                // u16 semantic range
}

message BltClusterSummary {
  uint32 cluster_id = 1;                  // u8
  uint32 head_id = 2;                     // u16
  sint32 head_offset_to_global_q01ns = 3; // int32, 0.1 ns
  uint32 member_count = 4;                // u16
  uint32 inlier_count = 5;                // u16
  sint32 member_offset_mean_q01ns = 6;    // int32, 0.1 ns
  uint32 member_offset_var_q01ns2 = 7;    // u32, (0.1 ns)^2
}

message BltMemberRecord {
  uint32 node_id = 1;                     // u16
  uint32 cluster_id = 2;                  // u8
  sint32 offset_to_head_q01ns = 3;        // int16, 0.1 ns
  uint32 resp_prob_q255 = 4;              // u8, range 0..255
  uint32 time_acc_q01ns = 5;              // u16
  uint32 flags = 6;                       // u8 (participation/outlier/saturation)
}
```

**Note on type widths**: Protobuf has no u8/u16/u24 native types. We use `uint32`/`sint32` and document the semantic range in comments. Wire-format byte counts therefore deviate slightly from the paper's byte breakdown (varint encoding).

### 4.4 Msg handler logic (outline)

```
HandleMsgCommitSyncBlock(ctx, msg):
  1. Verify msg.proposer is a member of the current delegate_set.
  2. Verify every body.cluster_table.head_id maps to a validator in delegate_set.
  3. Verify body.global.cluster_count == len(body.cluster_table).
  4. Verify body.global.member_count == len(body.member_table).
  5. (Optional sanity) Verify global_ref_time_q01ns is within median +- tolerance
     of cluster head_offset_to_global values (paper §III.B "plausibility check").
  6. Persist as latest_epoch and append to epoch_history.
  7. Emit event: EventBlockCommitted{epoch_id, global_ref_time_q01ns, height}.
```

### 4.5 Genesis state

```protobuf
message GenesisState {
  BltParams params = 1;
  BltDelegateSet initial_delegates = 2;   // Maps to the 12 genesis validators
}

message BltParams {
  uint32 cluster_count = 1;               // = 12
  uint32 epoch_length_ms = 2;             // = 3500
  uint64 max_member_records_per_block = 3; // Safety limit, e.g., 16384
}

message BltDelegateSet {
  repeated BltDelegate delegates = 1;
}

message BltDelegate {
  uint32 cluster_id = 1;
  uint32 head_id = 2;                     // Cluster-head satellite ID
  string validator_address = 3;           // cosmosvaloper1...
}
```

---

## 5. Block Composition Strategy

- **One tx per block**: `MsgCommitSyncBlock`.
- Submitter: the CometBFT proposer for that height (round-robin among the 12 cluster-head validators).
- The proposer assembles the body off-chain (via ISL) by collecting cluster summaries from the other cluster heads, then submits the assembled body as a single tx.
- CometBFT handles propose, prepare, and commit automatically (= paper's h-PBFT stage 2).
- The finalized block therefore contains exactly one tx, minimizing tx envelope overhead.

This matches the paper's wording in §III.B: "Cluster-level transactions are forwarded to a global coordination phase. Cluster heads construct candidate blocks from these transactions." Here, "transactions" refers to off-chain cluster-summary messages, and "candidate block" is the CometBFT block carrying our single `MsgCommitSyncBlock`.

---

## 6. Build and Run

```bash
# Build
ignite chain build --release --release.targets linux:amd64,linux:arm64

# Local single node (fast dev)
ignite chain serve

# Multi-node (12-validator simulation)
./scripts/init_n_validators.sh 12
./scripts/start_local.sh

# Status checks
./leochaind status
./leochaind query blt latest-epoch
```

---

## 7. Block size accounting

### 7.1 The design block (Fig. 3)

A block carries one cluster, 8192/12 = 683 records of 9 B, giving a 6,386 B
body in a 6,678 B block. The field widths and the arithmetic are in
[the readme](../../readme.md#what-the-blt-module-does), next to what each field
is for.

### 7.2 Why the serialised block differs

The chain encodes the same body with protobuf, which writes a tag before every
value, "field 3, varint", and a tag and length before every record, because
the member table is a `repeated BltMemberRecord`. A 9 B record costs about 17 B
on the wire. Holding the block at 6.7 kB therefore fits **298 records** here,
and `tools/sizemodel/block_size_model.py` gives the wire size for any count
(5,211 B of message at 298, 11,562 B at 683); it reproduces the Go measurements
in `x/blt/types/size_test.go` byte for byte.

The three quantities to keep apart:

| | Records | Size |
|---|---:|---:|
| Design block, Fig. 3 | 683 | 6,678 B |
| Measured block, this harness | 298 | 6,763-6,776 B |
| Measured block, full member table | 8,192 | about 135 kB |

### 7.3 Measured, full member table

This measures a configuration the design does not use: the whole
constellation's member table in a single block, 8,192 records rather than one
cluster's 683. It is here as the upper bound, and because it is where the
per-record wire cost was first measured. At N = 8,192 the member table
dominates everything else.

| Component | Estimated size | Measured |
|-----------|----------------|--------------------------------|
| CometBFT header | about 400 B | about 600 B (observed via `/block` JSON, conservative) |
| LastCommit (4 ed25519 sigs in dev) | about 800 B for 12 | about 300 B for 4; project about 800 B for 12 |
| MsgCommitSyncBlock envelope | about 150 B | 271 B with empty member_table |
| BltBodyGlobal | about 14 B (varint) | about 14 B |
| BltClusterSummary × 12 | about 22 B × 12 = 264 B | matches estimate |
| BltMemberRecord × 8,192 | 9 B × 8,192 = 73.7 kB of payload | **133.6 kB** (about 16.3 B/record after proto tags) |
| **Total per block** | **about 99 kB** | **about 135 kB** for 8,192 members |

Sub-totals at smaller N from `TestSize_Sampled` (`x/blt/types/size_test.go`):

| members | MsgCommitSyncBlock wire size |
|---------|------------------------------|
| 0 | 271 B |
| 12 | 511 B |
| 256 | 4.40 kB |
| 1 024 | 16.90 kB |
| 4 096 | 67.04 kB |
| 8 192 | 133.87 kB |

Reason the measured value exceeds the estimate: each `BltMemberRecord`
encodes six fields of 9 B in total, and proto3 adds a tag byte per field plus
a tag and length for the record itself, which takes it to about 16.3 B on the
wire. That ratio is what section 7.2 applies at the design's 683 records.

A third option, committing the member table as a 32-byte Merkle root instead of
carrying it, would take the member table from 133.87 KiB to 380 B, with a
428 B per-member inclusion proof. The projection
comes from `tools/sizemodel/block_size_model.py`, which reproduces every wire
size in the table above byte for byte.

---

## 8. Unity Client Integration Notes

- **RPC**: port 26657, endpoints unchanged.
- **Poll cadence**: do not align with the block interval; poll at about 1 s for responsiveness.
- **Block decoding**: `tx[0]` is the `MsgCommitSyncBlock`; protobuf-parse it and extract `BltBlockBody`.
- **Convenience query** (recommended): `/abci_query` on `/leochain.blt.Query/LatestEpoch`. The
  response is a base64 `QueryLatestEpochResponse`, not JSON; `docs/integrations/unity.md` gives the
  exact request and how to decode it.
- Add a new method to `BlockchainPoller.cs` that targets the convenience query.

---
