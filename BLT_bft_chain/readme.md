# BLT_bft_chain, the consensus chain

A Cosmos SDK application chain on CometBFT v0.38.17 implementing §III of the paper: cluster heads
propose a synchronization block, the validator set commits it on a two-thirds quorum, and the
committed epoch becomes the constellation's time reference.

This is the part of the system that is **measured rather than simulated**. The per-block traffic,
the commit latency, the CPU cost, the five-year storage growth and every rejected tamper attempt
quoted in [`../docs/FIGURES.md`](../docs/FIGURES.md) come from running this chain, not from a model
of it. The simulator next door models the quorum; it does not model what running one costs.

Chain id `leo_chain-1`, denom `leo`, binary `leochaind`. Scaffolded with Ignite CLI; the work is in
`x/blt/`.

## What the `blt` module does

One message carries a synchronization epoch:

```
MsgCommitSyncBlock
  global         the proposed reference time, with declared cluster and member counts
  cluster_table  one row per cluster head: its id and the offset it reported
  member_table   the per-member precision records the heads collected
```

**A block carries one cluster, not the constellation.** At N = 8,192 in twelve
clusters that is 8192/12 = 683 member records, so twelve consecutive blocks
cover everyone, 72 s at a 6 s interval. Each record is six fields:

| Field | Type | Width | |
|---|---|---:|---|
| `node_id` | u16 | 2 B | which satellite |
| `cluster_id` | u8 | 1 B | which cluster it answered in |
| `offset_to_head_q01ns` | int16 | 2 B | its offset from the head, 0.1 ns |
| `resp_prob_q255` | u8 | 1 B | how often it answers |
| `time_acc_q01ns` | u16 | 2 B | its timing accuracy, 0.1 ns |
| `flags` | u8 | 1 B | participation, outlier, saturation |
| | | **9 B** | |

The first three are what the paper's Fig. 3 calls the *node offset* and the last
three its *reliability*, which is the record the ledger keeps so a head can be
chosen on past behaviour rather than on connectivity alone. A block is then

```
body  = global reference  11 B + cluster summaries 19 B x 12 + records 9 B x 683
      = 11 + 228 + 6,147                                      = 6,386 B
block = header 222 B + body 6,386 B + vote evidence 70 B      = 6,678 B
```

which is the 6.7 kB the paper quotes. That is the payload; the same body through
protobuf costs more, and [the spec](docs/spec/BLT-SAND-chain-spec.md#7-block-size-accounting)
accounts for both.

The proposer is fixed by round rather than chosen by what it wants to say, and a block is admitted
only if it survives every check below. Admission is in
`x/blt/keeper/msg_server_commit_sync_block.go`; plausibility has its own file because it is the
check that does the real work.

| Code | Rejected because |
|---|---|
| 1101 | the proposer is not in the current delegate set |
| 1102 | a cluster head is not in the current delegate set |
| 1103, 1104 | the declared cluster or member count disagrees with the block's own tables |
| 1105 | the member table is over the per-block limit |
| 1106 | the relay path hash is not 32 bytes |
| 1107, 1108 | the epoch snapshot, or the latest epoch, is missing |
| **1109** | the proposed global time is implausible against what the cluster heads reported |
| **1110** | the global time does not advance past the committed epoch |
| 1111 | an epoch was already committed at this height or later |
| **1112** | the global time disagrees with the consensus block time beyond tolerance |
| **1113** | the same head appears twice in the cluster table |
| **1114** | the epoch id does not advance by 1..128 (mod 256) |

The five in bold are what the tamper experiment attacks: rewinding the reference time (1112),
replaying a committed epoch (1114), forging a time (1112), reporting one head twice (1113) and
proposing from outside the delegate set (1101). All five are rejected, the ledger is unchanged, and
all twelve nodes return the same verdict.

1109 is the cross-cluster check, and it is the one worth understanding. A proposer whose global time
contradicts most of the cluster summaries carried in its own block is refused even though every
signature on that block is valid. That is what makes several heads agreeing on a wrong value a
detectable condition rather than simply a majority, which matters here because the faults are
benign and regional, so heads that err together are the expected case rather than an attack.

```
x/blt/
  keeper/   admission, epoch state, plausibility, queries, ABCI hooks
  types/    messages, the errors above, genesis
  module/   module wiring
proto/leochain/blt/   message and query definitions
```

## Two quorum rules, two adversaries

The chain runs CometBFT's rule **unmodified**: a block commits on more than two
thirds of the voting power, which at twelve equal validators is **9 of 12**. The
simulation next door commits on `ceil(2n/3)`, **8 of 12**. The difference is one
vote and it is deliberate, because the two are sized against different
adversaries.

| | Rule at n = 12 | Tolerates | Assumes |
|---|---|---|---|
| Simulation | `ceil(2n/3)` = 8 | 4 wrong heads (1/3) | benign degradation: a wrong value, sent once, to everyone |
| This chain | `> 2/3` = 9 | 3 (1/4) | Byzantine voting power, including equivocation |

The fault model in the paper is **benign**. A degraded satellite stays up,
follows the protocol and reports the value it believes; nothing forges a
signature, withholds a message, or sends one value to one peer and a different
value to another. The `3f+1` bound of classical PBFT exists to defeat exactly
that last behaviour, and CometBFT's strictly-greater-than rule is stricter
still. Neither bound is wrong; they answer a question the synchronization layer
does not ask.

At a quorum of 8 the arithmetic is: an honest proposal is backed by all
`12 - f` honest heads, so it commits while `f <= 4`; a wrong proposal is backed
only by wrong heads, so it needs `f >= 8` and never commits below that. Between
4 and 8 nothing commits. Measured, the head axis holds under 10 ns to 4 of 12
and breaks at 5.

A round that fails to reach the quorum writes nothing to the ledger, but it is
not a no-op in the simulation: with the fallback arm enabled, which is the arm
the head-axis figure uses, the heads still reconcile toward the **median** of
what was reported. A median needs no agreement, every head computes it from the
same reports, and it is the same robust aggregate the local phase already uses,
so it is the floor the hierarchy provides without consensus. What is lost past
the quorum is the guarantee, not the correction.

Running the chain at the simulation's quorum would mean tolerating `f = n/3`
exactly, which is outside the classical Byzantine bound. It is not done.

## How a block goes through

```
proposer (fixed by round)
  -> MsgCommitSyncBlock        global time + cluster_table + member_table
  -> admission                 the fourteen checks above; any one refuses the block
  -> CometBFT vote             committed on a two-thirds quorum
  -> epoch state               the committed epoch becomes the time reference
```

What a refusal means matters here. A block that fails admission is **not committed and changes
nothing**, the previous epoch stands and the chain moves on. That is the behaviour the design
wants: under regionally correlated degradation, refusing to agree is the correct outcome, and the
cost is availability rather than a wrong reference time.

Module parameters are set at genesis (`x/blt/types/params.go`): `cluster_count` 12,
`epoch_length_ms` 3500, `max_member_records_per_block` 16384.

**The demo chain drives itself.** There is no satellite swarm attached, so `EndBlocker`
(`x/blt/keeper/abci.go`) synthesizes a plausible sync epoch each block instead of waiting for a
proposer. It is seeded from the block height and uses integer-only arithmetic throughout, because
every validator has to derive identical state, a float differing in the last bit across
architectures would fork the app hash. In a real deployment this path is replaced by a rotating
cluster head submitting measured offsets; the admission rules do not change.

## Running it

```bash
make install                           # builds leochaind
bash scripts/init_n_validators.sh 12   # lay down 12 node homes, once
bash scripts/start_local.sh 12         # start them
bash scripts/start_local.sh stop       # stop them
```

`init_n_validators.sh` writes independent node homes under `~/.leochain-testnet/v{i}`
(`$TESTNET_DIR` to move it) with chain id `leo_chain-1`, 100000000`leo` bonded each, the
`blt.initial_delegates` genesis entry filled in for all N, consensus timeouts at 3500 ms, p2p/rpc
ports stepped by 10 from 26656/26657, and `persistent_peers` wired full mesh. It needs `jq` and
`leochaind` on `PATH`. Each node logs to `~/.leochain-testnet/v{i}.log`.

Validators run as native processes on one host rather than in containers, so the CPU, memory and
p2p figures belong to the process itself rather than to a runtime around it.

### Looking at it

```bash
leochaind query blt latest-epoch                  # the committed reference time
leochaind query blt delegate-set                  # who may propose
leochaind query blt epoch-history 7               # one epoch by id
leochaind query blt params

curl localhost:26657/status                       # height, catching-up
curl localhost:1317/leochain/blt/latest_epoch     # the same over REST
```

The digital twin polls `/status`, `/block` and `/abci_query` on 26657.
`bash scripts/check_unity_rpc.sh [rpc_url]` smoke-tests exactly those and exits non-zero if one is
broken, run it before opening the Unity scene rather than debugging from inside it.

## Reproducing the measurements

```bash
mkdir -p ../BLT_simul/result/chain
N=12 K=10 TAMPER=1 RECOVERY=1 CROSS=1 bash scripts/chain_scale.sh   | tee ../BLT_simul/result/chain/chain_n12_full.log
```

| Part | What it measures |
|---|---|
| A | Latency, block size, CPU, memory, bandwidth at N validators |
| B | The five tamper attempts above |
| C | Recovery: a node is disconnected, the chain advances, the node rejoins |
| D | Cross-cluster consistency, including the 1109 case |

`MEMBERS` sets how many member records a block carries; of the knobs here it is
the one that moves a measured quantity, since p2p traffic scales with the block
in bytes. [The spec](docs/spec/BLT-SAND-chain-spec.md#7-block-size-accounting)
gives the sizes and why the default is 298.

`N` is the validator count, measured at 4, 8, 12 and 16; `K` is how many synchronization epochs
to measure. The script writes to standard output, so the command above redirects it to
`../BLT_simul/result/chain/`, where the figure code reads it. The scripts report sizes in KiB
because that is what the counters give; the figures and documents are SI, converted in one place.

`scripts/recovery.sh` and `scripts/validator_halt.sh` run parts C and B on their own.
`scripts/check_unity_rpc.sh` verifies the endpoints the digital twin polls.

[`../docs/REPRODUCING.md`](../docs/REPRODUCING.md) puts these alongside the simulation commands.

## Built with

[Ignite CLI](https://ignite.com/cli) · [Cosmos SDK](https://docs.cosmos.network) ·
[CometBFT](https://docs.cometbft.com)
