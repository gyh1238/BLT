"""How much degradation piles up inside one cluster, the step before a head misreports.

A head reports what its cluster agreed on, so it only carries a wrong value when its
own cluster is mostly degraded, one half of the union rule HEAD_FAULT='both'. Whether
that happens is not a matter of how many satellites are degraded but of where they are:
the same budget
spread uniformly never fills a cluster, while a regional cause (a radiation belt
crossing) fills whole clusters at once. That is the mechanism that matters:
correlated benign degradation is what collusion would look like to a vote.

This measures the placement alone, with no simulation: satellites are created with the
same generator and seeds as experiments/faults/correlated_faults.py, clustered the way the
engine clusters them, and the degraded share of each cluster is counted.

Output: result/runs/fault_concentration.csv, one row per (placement, share, seed)
with the worst and the mean cluster share and how many clusters are over half.

Run:  python experiments/faults/fault_concentration.py
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
import os

import numpy as np

import blt_core
import main_all
import blt_config

K = 12
BASE_SEED = 20260930            # the seeds of correlated_faults.py, so the two line up
PLACEMENTS = {'scattered': dict(), 'regional': dict(concentrate_faults=True),
              'clustered': dict(cluster_aligned=True, cluster_pick='random')}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8192)
    ap.add_argument('--seeds', type=int, default=4)
    ap.add_argument('--fractions', default='0.05,0.10,0.15,0.20,0.25,0.30,0.35,0.40')
    args = ap.parse_args()
    blt_config.apply(main_all)
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for case, kw in PLACEMENTS.items():
        for lv in (float(x) for x in args.fractions.split(',')):
            for r in range(args.seeds):
                seed = BASE_SEED + r
                sats = main_all.initialize_satellites(
                    args.n, int(round(lv * args.n)),
                    malfunction_mean=main_all.blt_params.value('osc_nominal_hz'),
                    malfunction_stddev=blt_config.FAULTY_STDDEV_HZ,
                    malfunction_drift_bias=blt_config.FAULTY_DRIFT_BIAS, seed=seed, **kw)
                main_all.cluster_by_position(sats, K)
                degraded = blt_core.fault_mask(sats)
                label = np.array([s['cluster'] for s in sats])
                share = np.array([degraded[label == c].mean() for c in range(K)])
                rows.append({'case': case, 'level': lv, 'seed': seed,
                             'worst_cluster_frac': float(share.max()),
                             'mean_cluster_frac': float(share.mean()),
                             'clusters_over_half': int((share > 0.5).sum())})
                print(f'{case:>10} {100 * lv:4.0f}% seed {seed}: worst cluster '
                      f'{100 * share.max():5.1f}%, {int((share > 0.5).sum())} over half', flush=True)
    with open(os.path.join(out_dir, 'fault_concentration.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {out_dir}/fault_concentration.csv ({len(rows)} rows)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
