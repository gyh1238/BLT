"""Local collection time as a function of cluster count: how long a head needs to poll its members.

The manuscript derives the local synchronization cycle from the cluster size: a head
polls every member over two-way exchanges, so one local round takes

    T_local(Nc) = members per cluster x mean member round trip / ISL terminals at the head

and fewer, larger clusters take longer. At Nc = 12 this is the 5.7 s behind the 6 s
cycle (NUMBERS §2). This computes the same quantity for every cluster count from the
constellation geometry and the ISL link model: KMeans clusters, heads nearest the
centroid, most-reliable relay routes (blt_isl), and per-hop latency = propagation +
relay processing (blt_links.hop_delay_s). The round trip is twice the one-way route
latency.

deployment_grid.py uses it so the local cycle follows the cluster size instead of
being held at 6 s.

Run:  python experiments/design/collection_time.py            # Nc = 6, 12, 18, 24, 30
"""

from __future__ import annotations

import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.isdir(_os.path.join(_ROOT, 'model')):   # climb to the repository root
    _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_os.path.join(_ROOT, 'model'), _os.path.join(_ROOT, 'figures')]
# Every experiment group, so a driver can import another driver by module name
# regardless of which group either of them sits in.
_EXP = _os.path.join(_ROOT, 'experiments')
_sys.path[:0] = [_os.path.join(_EXP, d) for d in sorted(_os.listdir(_EXP))
                 if _os.path.isdir(_os.path.join(_EXP, d)) and not d.startswith('_')]
_os.chdir(_ROOT)

import argparse
import csv

import numpy as np

import blt_isl
import blt_links
import main_all

ISL_TERMINALS = 2


def collection_time(n, nc, seed=20260914, terminals=ISL_TERMINALS):
    """Return dict: members per cluster, mean hops, mean route km, round trip [s], T_local [s]."""
    sats = main_all.initialize_satellites(n, 0, seed=seed)
    pos = np.array([s['position'] for s in sats], dtype=float)
    clusters = main_all.cluster_indices_from_kmeans(pos, nc)
    lm = blt_isl.LinkModel(n, np.random.default_rng(seed))
    lm.update(pos, clusters, 0.0)
    hops, km, rtt = [], [], []
    for tree, idxs in zip(lm.local_trees, clusters):
        for v in idxs:
            if tree.depth[v] <= 0:
                continue
            d, u = 0.0, int(v)
            while tree.parent[u] >= 0:
                p = int(tree.parent[u])
                d += float(np.linalg.norm(pos[u] - pos[p]))
                u = p
            hops.append(int(tree.depth[v]))
            km.append(d)
            rtt.append(2.0 * (d / blt_links.C_KM_S + tree.depth[v] * float(blt_links.hop_delay_s(0.0))))
    members = n / nc
    mean_rtt = float(np.mean(rtt))
    return {'Nc': nc, 'members': members, 'hops': float(np.mean(hops)), 'route_km': float(np.mean(km)),
            'round_trip_ms': mean_rtt * 1e3, 'T_local_s': members * mean_rtt / terminals}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8192)
    ap.add_argument('--nc', default='6,12,18,24,30')
    ap.add_argument('--out', default='result/runs/collection_time.csv')
    args = ap.parse_args()
    rows = [collection_time(args.n, int(k)) for k in args.nc.split(',')]
    print(f"{'Nc':>4} {'members':>8} {'hops':>5} {'route km':>9} {'RTT ms':>7} {'T_local s':>9}")
    for r in rows:
        print(f"{r['Nc']:>4} {r['members']:>8.0f} {r['hops']:>5.2f} {r['route_km']:>9.0f} "
              f"{r['round_trip_ms']:>7.2f} {r['T_local_s']:>9.2f}")
    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
