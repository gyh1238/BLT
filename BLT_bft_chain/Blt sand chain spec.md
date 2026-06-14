# BLT-SAND Chain Implementation Spec

> **Goal**: Build a Cosmos SDK chain (`leo_chain-1`) consistent with the BLT-SAND paper.
> **Policy**: Full record (member_table included in every block). Paper text receives minimal edits only for size accounting.
> **Audience**: Claude Code, executing the roadmap phase by phase.

---

## 0. Mission Summary

- Re-implement the legacy `leo-chaind` binary (built in 2022 by a collaborator) to match the BLT-SAND paper specification.
- Built on Tendermint Core (i.e., Cosmos SDK).
- Keep `chain_id = leo_chain-1` and token denom = `leo`.
- Maintain RPC compatibility for the Unity digital twin (`BlockchainPoller.cs`, port 26657).

---

## 1. Tech Stack

| Item | Choice | Reason |
|------|--------|--------|
| Scaffolding | **Ignite CLI v28.x** | Fast module/message generation |
| Cosmos SDK | **v0.50.x** | Bundled with CometBFT v0.38 (stable) |
| Consensus | **CometBFT** (formerly Tendermint Core) | Matches paper §IV.A wording |
| Language | Go 1.21+ | Cosmos SDK standard |
| Proto codegen | buf | Ignite default |
| Target OS | Linux amd64/arm64 (deploy), Linux/Windows (dev) | Same as legacy |

---

## 2. Chain Parameters

```yaml
chain_id: leo_chain-1
denom: leo
address_prefix: cosmos                # Keep cosmos1... addresses

consensus:
  timeout_commit: 3500ms              # Paper §IV.A: "Blocks are generated every 3.5s"
  timeout_propose: 1000ms
  timeout_prevote: 500ms
  timeout_precommit: 500ms

genesis_validators: 12                # Paper Fig.4 "CLUSTERS 12/12" and §IV.A "12 clusters"

hash_algorithm: SHA-256               # Paper §III.A
quorum: 2f+1 (= 9 of 12)              # Paper §III.B "two-thirds of active participants"
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
package leochain.blt.v1;

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

**Note on type widths**: Protobuf has no u8/u16/u24 native types. We use `uint32`/`sint32` and document the semantic range in comments. Wire-format byte counts therefore deviate slightly from the paper's byte breakdown (varint encoding). This deviation is handled in §9 (paper text edits).

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

## 6. Implementation Roadmap (Claude Code execution order)

### Phase 1: Project bootstrap
```bash
# Verify Ignite installation
ignite version  # require v28.x or later

# Scaffold the chain
ignite scaffold chain leochain --address-prefix cosmos --no-module
cd leochain
git init && git add -A && git commit -m "phase 1: scaffold"
```

**Verify**: `config.yml` is generated and `ignite chain serve` boots a local node.

### Phase 2: Configure chain_id and denom
Edit `config.yml`:
```yaml
accounts:
  - name: alice
    coins: ["100000000leo"]
validators:
  - name: alice
    bonded: "100000000leo"
genesis:
  chain_id: "leo_chain-1"
  app_state:
    staking:
      params:
        bond_denom: "leo"
    crisis:
      constant_fee:
        denom: "leo"
    mint:
      params:
        mint_denom: "leo"
    gov:
      params:
        min_deposit:
          - denom: "leo"
            amount: "10000000"
```

### Phase 3: Add the x/blt module
```bash
ignite scaffold module blt --dep bank,staking
ignite scaffold message commitSyncBlock \
  body:string relayPathHash:string epochId:uint \
  --module blt --signer proposer
```

After scaffolding, replace the generated proto stubs with the schema from §4.3.

### Phase 4: Write the proto schema
- Create `proto/leochain/blt/v1/types.proto`: `BltBodyGlobal`, `BltClusterSummary`, `BltMemberRecord`, `BltBlockBody`, `BltDelegate*`.
- Replace `proto/leochain/blt/v1/tx.proto`: `MsgCommitSyncBlock` as in §4.3.
- Add to `proto/leochain/blt/v1/genesis.proto`: `GenesisState` with `params` and `initial_delegates`.
- Add `proto/leochain/blt/v1/query.proto`: `Query/LatestEpoch`, `Query/EpochHistory`, `Query/Params`.
- Regenerate: `ignite generate proto-go`.

### Phase 5: Implement keeper and msg server
- `x/blt/keeper/msg_server_commit_sync_block.go`: implement §4.4 logic.
- `x/blt/keeper/keeper.go`: accessors for `latest_epoch`, `epoch_history`, `delegate_set`.
- `x/blt/keeper/grpc_query.go`: implement query handlers.
- `x/blt/types/events.go`: define `EventTypeBlockCommitted` and attribute keys.
- `x/blt/module.go`: ensure module is registered in `app/app.go`.

### Phase 6: Tune block timing
Edit `config/config.toml` for each validator:
```toml
[consensus]
timeout_commit = "3500ms"
timeout_propose = "1000ms"
timeout_prevote = "500ms"
timeout_precommit = "500ms"
```

### Phase 7: 12-validator genesis
Write `scripts/init_12_validators.sh`:
- Generate 12 validator keys.
- For each: `leochaind add-genesis-account ... 100000000leo` then `leochaind gentx ...`.
- `leochaind collect-gentxs`.
- Populate `app_state.blt.initial_delegates` with the 12 validator addresses, assigning `cluster_id = 0..11` and `head_id` = chosen NORAD-like IDs.
- Lock `chain_id = leo_chain-1`.

### Phase 8: Local 4-node smoke test (scaled down)
Twelve validators is heavy for a laptop; run a 4-node test first.
- Use `ignite chain serve --multinode` or a docker-compose setup.
- Confirm blocks are produced at ~3.5 s intervals.
- From one node, submit a dummy `MsgCommitSyncBlock`; from another node, verify it appears in the next block via RPC.
- **Measure on-wire block size**; record the value for §9.2.

### Phase 9: Unity client integration check
- Confirm legacy `BlockchainPoller.cs` still works against the new chain on `/status` and `/block?height=`.
- For tx decoding, use protobuf to JSON (CometBFT can return JSON-encoded txs).
- Recommended: add a new poll target `/abci_query?path=/leochain.blt.v1.Query/LatestEpoch` to bypass tx parsing and pull the snapshot directly.

### Phase 10: Cross-compile and release
- Targets: `linux/amd64`, `linux/arm64`.
- Add `Makefile` target `build-all`.
- Output artifacts: `leochaind-linux-amd64`, `leochaind-linux-arm64`, `genesis.json`.

---

## 7. File Structure (expected)

```
leochain/
├── app/
│   ├── app.go                       # Module wiring
│   └── ante.go
├── cmd/
│   └── leochaind/
│       └── main.go
├── proto/
│   └── leochain/
│       └── blt/
│           └── v1/
│               ├── types.proto      # Body, Cluster, Member definitions
│               ├── tx.proto         # MsgCommitSyncBlock
│               ├── query.proto      # LatestEpoch, EpochHistory, Params
│               └── genesis.proto
├── x/
│   └── blt/                         # Core custom module
│       ├── keeper/
│       │   ├── keeper.go
│       │   ├── msg_server.go
│       │   ├── msg_server_commit_sync_block.go
│       │   ├── grpc_query.go
│       │   └── genesis.go
│       ├── types/
│       │   ├── codec.go
│       │   ├── errors.go
│       │   ├── events.go
│       │   ├── keys.go
│       │   ├── params.go
│       │   └── *.pb.go              # Auto-generated
│       └── module.go
├── scripts/
│   ├── init_12_validators.sh
│   └── start_local.sh
├── config.yml                       # Ignite config
└── Makefile
```

---

## 8. Build and Run

```bash
# Build
ignite chain build --release --release.targets linux:amd64,linux:arm64

# Local single node (fast dev)
ignite chain serve

# Multi-node (12-validator simulation)
./scripts/init_12_validators.sh
./scripts/start_local.sh

# Status checks
./leochaind status
./leochaind query blt latest-epoch
```

---

## 9. Paper Text Edits (size accounting)

### 9.1 Fig. 3 caption
**Current**: "BLT-SAND blockchain framework."
**Replace with**:
> "BLT-SAND blockchain framework. The block layout shown represents the BLT-SAND **logical design payload**; the corresponding on-wire block additionally carries CometBFT framing (header metadata and commit signatures) when implemented over Tendermint Core."

### 9.2 §IV.A insertion
**Current sentence**: "Blocks are generated every 3.5 s with a size of 1.18 kB."
**Insert immediately after**:
> "This size represents the BLT-SAND application-layer payload encoded in the block body and vote evidence. The on-wire CometBFT block additionally carries header metadata and commit signatures, yielding a total measured block size of approximately **X kB** under the testbed configuration with 12 cluster-head validators."

`X` is filled in after the Phase 8 measurement. Expected range: 2–3 kB without full member_table; ~100 kB with full member_table for N = 8,192.

### 9.3 (Optional) §IV.A clarification on full record
**Current**: "BLT-SAND addresses this issue by permitting a single hard fork [15] during the mission lifetime."
**Proposed addition before this sentence**:
> "Within each block, the body retains the full member_table to preserve per-satellite traceability across the constellation; this drives the dominant component of block size and motivates the hard-fork checkpoint policy described above."

This sentence connects the large block size to the existing hard-fork rationale and removes any apparent inconsistency.

---

## 10. Size Accounting (to measure)

| Component | Estimated size | Final value (fill after Phase 8) |
|-----------|----------------|----------------------------------|
| CometBFT header | ~400 B | |
| LastCommit (12 ed25519 sigs) | ~800 B | |
| MsgCommitSyncBlock envelope | ~150 B | |
| BltBodyGlobal | ~14 B (varint) | |
| BltClusterSummary × 12 | ~22 B × 12 = 264 B | |
| BltMemberRecord × 8,192 | ~12 B × 8,192 ≈ 98 kB | **dominant** |
| **Total per block** | **~99 kB** | |

⚠️ Full-record blocks reach ~100 kB scale. This is acceptable for the digital-twin demo but must be disclosed in the paper (§9.2's `X` value).

Alternative phrasing for the paper, if needed: "In the testbed configuration with N = 8,192, the full member_table dominates the block size; production deployments may apply per-block sampling for size-constrained scenarios."

---

## 11. Unity Client Integration Notes

- **RPC**: port 26657, endpoints unchanged.
- **Poll cadence**: do not align with the 3.5 s block interval; poll at ~1 s for responsiveness.
- **Block decoding**: `tx[0]` is the `MsgCommitSyncBlock`; protobuf-parse it and extract `BltBlockBody`.
- **Convenience query** (recommended): `/abci_query?path=/leochain.blt.v1.Query/LatestEpoch` returns the snapshot directly as JSON, bypassing tx parsing.
- Add a new method to `BlockchainPoller.cs` that targets the convenience query.

---

## 12. Open / Deferred Decisions

1. **Dynamic delegate_set updates**: how should validator-set updates be triggered when clusters reconfigure (manual governance vs. automatic EndBlocker)? Start with a static 12.
2. **relay_path_hash verification**: simple echo, or actual relay-path tracking? Start with echo.
3. **member_table sampling mode**: future paper revisions may add a sampling mode for production friendliness. Decide after Phase 8 measurement.
4. **Hard-fork policy**: paper §IV.A mentions "single hard fork during mission lifetime" — does this need a dedicated governance proposal type? Defer initial implementation.

---

## 13. Verification Checklist

- [ ] `./leochaind status` reports `chain_id = leo_chain-1`.
- [ ] Block interval measured at 3.5 ± 0.2 s.
- [ ] With 12 validators, the chain survives up to 4 validators going offline (paper §III.B 2/3 quorum).
- [ ] A submitted `MsgCommitSyncBlock` appears in the next block and is queryable from another node.
- [ ] `LatestEpoch` query response contains a `cluster_table` of length 12 and the full `member_table`.
- [ ] Unity `BlockchainPoller` connects to the new chain without code changes (legacy endpoints).
- [ ] Measured on-wire block size has been recorded; `X` in §9.2 is finalized.
- [ ] Paper edits in §9 are applied to the manuscript.