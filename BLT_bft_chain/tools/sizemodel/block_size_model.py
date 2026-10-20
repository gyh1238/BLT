#!/usr/bin/env python3
"""Exact protobuf wire-size model for MsgCommitSyncBlock, plus a size and
verifiability comparison between the full-record body and a Merkle-committed
member table.

Why a model instead of the Go test: x/blt/types/size_test.go already reports the
full-record sizes, but it can only measure bodies the current schema can
express. Evaluating "what if the member table were replaced by a commitment"
needs sizes for a schema that does not exist yet. This model reproduces the
recorded Go measurements byte for byte (see the self-test it prints first), so
its projection for the alternative layout carries the same weight.

Run:
    python block_size_model.py
    python block_size_model.py --csv out.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys

# ---------------------------------------------------------------------------
# protobuf primitives
# ---------------------------------------------------------------------------


def varint_len(v: int) -> int:
    """Bytes used by a base-128 varint. A negative value is encoded as its
    two's-complement uint64 form, i.e. always 10 bytes."""
    if v < 0:
        return 10
    n = 1
    while v >= 0x80:
        v >>= 7
        n += 1
    return n


def zigzag32(v: int) -> int:
    return (v << 1) ^ (v >> 31)


def tag_len(field_no: int) -> int:
    return varint_len(field_no << 3)


def f_varint(field_no: int, value: int) -> int:
    """proto3 scalar field: omitted entirely when zero."""
    if value == 0:
        return 0
    return tag_len(field_no) + varint_len(value)


def f_sint32(field_no: int, value: int) -> int:
    if value == 0:
        return 0
    return tag_len(field_no) + varint_len(zigzag32(value))


def f_bytes(field_no: int, length: int) -> int:
    """bytes/string: omitted when empty, else tag + length prefix + payload."""
    if length == 0:
        return 0
    return tag_len(field_no) + varint_len(length) + length


def f_embedded(field_no: int, payload: int) -> int:
    """Embedded message. gogoproto emits (gogoproto.nullable) = false fields
    unconditionally, including when the payload is empty, matching the generated
    MarshalToSizedBuffer, which has no nil check for value types."""
    return tag_len(field_no) + varint_len(payload) + payload


def f_repeated_embedded(field_no: int, payloads: list) -> int:
    return sum(tag_len(field_no) + varint_len(p) + p for p in payloads)


# ---------------------------------------------------------------------------
# x/blt messages, populated exactly as x/blt/types/size_test.go fullBody() does
# ---------------------------------------------------------------------------

PROPOSER_LEN = len("cosmos1abcdefghijklmnopqrstuvwxyz0123456789ab")
RELAY_HASH_LEN = 32
EPOCH_ID = 42
GLOBAL_REF_TIME = 1_234_567_890


def body_global(n_clusters: int, n_members: int) -> int:
    return (
        f_varint(1, GLOBAL_REF_TIME)
        + f_varint(2, n_clusters)
        + f_varint(3, n_members)
    )


def cluster_summary(i: int, n_clusters: int, n_members: int) -> int:
    per = n_members // n_clusters
    return (
        f_varint(1, i)                                  # cluster_id
        + f_varint(2, 100 + i)                          # head_id
        + f_sint32(3, 1000 * (i - n_clusters // 2))     # head_offset_to_global
        + f_varint(4, per)                              # member_count
        + f_varint(5, per)                              # inlier_count
        + f_sint32(6, 1000)                             # member_offset_mean
        + f_varint(7, 500)                              # member_offset_var
    )


def member_record(i: int, n_clusters: int) -> int:
    return (
        f_varint(1, i + 1)                              # node_id
        + f_varint(2, i % n_clusters)                   # cluster_id
        + f_sint32(3, (i % 1024) - 512)                 # offset_to_head
        + f_varint(4, 250)                              # resp_prob_q255
        + f_varint(5, 64)                               # time_acc_q01ns
        + f_varint(6, 1)                                # flags
    )


def block_body(n_clusters: int, n_members: int, member_table: bool = True,
               commitment_bytes: int = 0) -> int:
    clusters = [cluster_summary(i, n_clusters, n_members) for i in range(n_clusters)]
    members = (
        [member_record(i, n_clusters) for i in range(n_members)] if member_table else []
    )
    size = (
        f_embedded(1, body_global(n_clusters, n_members))
        + f_repeated_embedded(2, clusters)
        + f_repeated_embedded(3, members)
    )
    if commitment_bytes:
        # One added `bytes member_root = 4` on BltBlockBody.
        size += f_bytes(4, commitment_bytes)
    return size


def msg_size(n_clusters: int, n_members: int, member_table: bool = True,
             commitment_bytes: int = 0) -> int:
    body = block_body(n_clusters, n_members, member_table, commitment_bytes)
    return (
        f_bytes(1, PROPOSER_LEN)
        + f_embedded(2, body)
        + f_bytes(3, RELAY_HASH_LEN)
        + f_varint(4, EPOCH_ID)
    )


# ---------------------------------------------------------------------------
# self-test against the recorded Go measurements
# ---------------------------------------------------------------------------

# From docs/spec/BLT-SAND-chain-spec.md section 10, produced by TestSize_Sampled.
GO_MEASURED_BYTES = {0: 271, 12: 511}
# The larger rows were recorded in KiB (2 decimals) only.
GO_MEASURED_KIB = {256: 4.40, 1024: 16.90, 4096: 67.04, 8192: 133.87}


def selftest() -> bool:
    ok = True
    for n in sorted(GO_MEASURED_BYTES):
        want = GO_MEASURED_BYTES[n]
        got = msg_size(12, n)
        good = got == want
        ok = ok and good
        print("  [{}] members={:>5}  model={:>7} B    go={:>7} B".format(
            "OK  " if good else "DIFF", n, got, want))
    for n in sorted(GO_MEASURED_KIB):
        want = GO_MEASURED_KIB[n]
        got_kib = msg_size(12, n) / 1024.0
        good = abs(got_kib - want) <= 0.005      # the doc rounds to 2 decimals
        ok = ok and good
        print("  [{}] members={:>5}  model={:>7.2f} KiB  go={:>7.2f} KiB".format(
            "OK  " if good else "DIFF", n, got_kib, want))
    return ok


# ---------------------------------------------------------------------------
# Merkle-committed member table
# ---------------------------------------------------------------------------

HASH_BYTES = 32


def inclusion_proof_bytes(n_members: int) -> int:
    """What one member sends to prove its own record was in the committed epoch:
    the record itself plus the sibling path up to the root."""
    if n_members <= 1:
        return member_record(0, 12)
    depth = int(math.ceil(math.log2(n_members)))
    return member_record(0, 12) + depth * HASH_BYTES


def rows(n_clusters: int, member_counts: list, epoch_s: float) -> list:
    out = []
    blocks_per_year = 365 * 86400.0 / epoch_s
    for n in member_counts:
        full = msg_size(n_clusters, n)
        committed = msg_size(n_clusters, n, member_table=False,
                             commitment_bytes=HASH_BYTES)
        out.append({
            "members": n,
            "full_bytes": full,
            "committed_bytes": committed,
            "reduction_x": full / committed,
            "proof_bytes": inclusion_proof_bytes(n),
            "full_gb_per_year": full * blocks_per_year / 1e9,
            "committed_gb_per_year": committed * blocks_per_year / 1e9,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", type=int, default=12)
    ap.add_argument("--epoch-s", type=float, default=3.5,
                    help="block/epoch period used for the storage projection")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    print("protobuf size model vs. recorded Go measurements "
          "(x/blt/types/size_test.go):")
    ok = selftest()
    print("\n  model {} the Go wire sizes\n".format(
        "reproduces" if ok else "DOES NOT reproduce"))

    data = rows(args.clusters, [0, 12, 256, 1024, 4096, 8192], args.epoch_s)

    print("full member_table vs. Merkle commitment "
          "({} clusters, {} s epoch):\n".format(args.clusters, args.epoch_s))
    hdr = "{:>8} {:>13} {:>12} {:>8} {:>9} {:>11} {:>11}".format(
        "members", "full", "committed", "ratio", "proof", "full/yr", "commit/yr")
    print(hdr)
    print("-" * len(hdr))
    for r in data:
        print("{:>8} {:>9.2f} KiB {:>10} B {:>7.1f}x {:>7} B {:>8.1f} GB {:>8.2f} GB".format(
            r["members"], r["full_bytes"] / 1024, r["committed_bytes"],
            r["reduction_x"], r["proof_bytes"],
            r["full_gb_per_year"], r["committed_gb_per_year"]))

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
        print("\nwrote " + args.csv)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
