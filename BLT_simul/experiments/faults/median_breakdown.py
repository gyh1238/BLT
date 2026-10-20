"""When does a cluster's robust reference actually break down?

The head reports its cluster's MAD-trimmed median, and the fault model flips the head
to "misreporting" once more than half its members are degraded
(``blt_core.head_fault_mask(majority_frac=0.5)``). That 0.5 is the textbook breakdown
point of the median, this measures it on the engine's own numbers instead of asserting
it: one cluster, a growing share of degraded members, the same aggregation the local
phase runs (median, MAD x 1.4826 x 3 trim, median of what survives), and the error of
the reference against what the healthy members alone would have said.

Adopted values: healthy 1 ppb, degraded 27.5 ppb spread + 19 ppb bias, 6 s between
rounds, two-way timestamp noise on each member exchange. No orbit propagation and no
consensus, this is about the estimator, so it draws the members directly.

Run:  python experiments/faults/median_breakdown.py
Output: result/runs/median_breakdown.csv
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

import blt_links
import blt_config

MEMBERS = 683          # 8192 / 12
CYCLE_S = 6.0


def reference(values, within_k=3.0):
    """The local phase's aggregate: median, MAD trim, median of the survivors."""
    med = np.median(values)
    mad = np.median(np.abs(values - med))
    threshold = max(within_k * 1.4826 * mad, 1e-18)
    valid = np.abs(values - med) <= threshold
    return float(np.median(values[valid])) if valid.any() else float(med)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--members', type=int, default=MEMBERS)
    ap.add_argument('--draws', type=int, default=400)
    ap.add_argument('--shares', default=','.join(f'{x / 100:.2f}' for x in range(0, 75, 5)))
    args = ap.parse_args()
    rng = np.random.default_rng(20260930)
    sigma_meas = blt_links.twoway_sigma_s()
    healthy_ppb = blt_config.HEALTHY_PPB
    faulty_ppb, bias_ppb = blt_config.FAULTY_PPB, blt_config.FAULTY_BIAS_PPB
    print(f'members {args.members}, {args.draws} draws, cycle {CYCLE_S} s, '
          f'healthy {healthy_ppb} ppb, degraded {faulty_ppb} ppb + {bias_ppb} ppb bias, '
          f'exchange noise {1e9 * sigma_meas:.1f} ns')

    rows = []
    for share in (float(x) for x in args.shares.split(',')):
        errs, trimmed = [], []
        for _ in range(args.draws):
            n_bad = int(round(share * args.members))
            # each member's clock offset after one round: its own rate x the cycle,
            # plus the error of the two-way exchange that reports it
            rate = rng.normal(0.0, healthy_ppb * 1e-9, args.members)
            bad = np.zeros(args.members, dtype=bool)
            if n_bad:
                bad[rng.choice(args.members, n_bad, replace=False)] = True
                rate[bad] = (rng.normal(0.0, faulty_ppb * 1e-9, n_bad)
                             + bias_ppb * 1e-9)
            offs = rate * CYCLE_S + rng.normal(0.0, sigma_meas, args.members)
            ref = reference(offs)
            truth = float(np.median(offs[~bad])) if (~bad).any() else float('nan')
            errs.append(abs(ref - truth))
            med = np.median(offs)
            mad = np.median(np.abs(offs - med))
            thr = max(3.0 * 1.4826 * mad, 1e-18)
            trimmed.append(float(np.mean(np.abs(offs - med) > thr)))
        rows.append({'faulty_share': share,
                     'ref_err_ns': 1e9 * float(np.mean(errs)),
                     'ref_err_p95_ns': 1e9 * float(np.percentile(errs, 95)),
                     'trimmed_frac': float(np.mean(trimmed))})
        print(f"  {100 * share:5.0f}%  reference off by {rows[-1]['ref_err_ns']:8.2f} ns "
              f"(p95 {rows[-1]['ref_err_p95_ns']:8.2f})  trimmed {100 * rows[-1]['trimmed_frac']:.1f}%",
              flush=True)

    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'median_breakdown.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {out_dir}/median_breakdown.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
