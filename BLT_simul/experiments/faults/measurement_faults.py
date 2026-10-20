"""Faulty measurements, the third fault category.

The three categories are separate: faulty ordinary satellites, faulty
measurements and faulty cluster heads. The first and third have their own sweeps; this one leaves every
oscillator and every head as adopted and corrupts the exchanges instead:

  outliers   each exchange, with probability p, returns an offset wrong by +/-50 ns
             (an optical link that slips, GRACE-FO reports phase jumps a few
             times per orbit, Abich 2019)
  bias       5% of the satellites carry a persistent 20 ns timing bias on every
             exchange they make or relay (an uncalibrated hardware delay)

BLT is run twice: as it stands (the filter keeps a flagged report out of the
cluster reference but the member still corrects with it) and with
LOCAL_SKIP_FLAGGED (a flagged member keeps its clock until the next round), which
is what the manuscript's "filters unreliable measurements" describes.

The same faults reach all three protocols: BLT and ATS through member-to-head
exchanges, FTSP through every relay hop of the flood. What differs is what each
does with them, BLT's median+MAD filter, ATS's mean, FTSP's hop-by-hop copy.

Run:  python experiments/faults/measurement_faults.py         # N = 8,192, 2 seeds
"""

from __future__ import annotations

import os as _os
import sys as _sys
# Run from anywhere: the engine modules live in model/, figure style in figures/, and
# data/ and result/ are resolved from the repository root.
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

import blt_params
import sensitivity_sweep as fh
import main_all

import blt_config  # noqa: E402
ADOPTED = dict(healthy=1.0, faulty=27.5, bias=blt_config.FAULTY_BIAS_PPB, alpha=0.5, range_m=1.0)
CONDITIONS = [
    ('none', 0.00, 0.0, 0.00, 0.0),
    ('outliers 1%', 0.01, 50e-9, 0.00, 0.0),
    ('outliers 5%', 0.05, 50e-9, 0.00, 0.0),
    ('outliers 10%', 0.10, 50e-9, 0.00, 0.0),
    ('bias 5% @20ns', 0.00, 0.0, 0.05, 20e-9),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8192)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--ticks', type=int, default=40000)
    ap.add_argument('--out', default='result/runs/measurement_faults.csv')
    args = ap.parse_args()
    steady = args.ticks // 4

    fh.FLOOD_TICKS, fh.LSB_S, fh.JITTER_S = 450, 1e-8, 3e-9
    print(f'measurement faults: N={args.n}, {args.seeds} seeds, 5% degraded satellites')
    print(f"{'condition':>14} | {'BLT':>6} {'BLT skip':>8} {'ATS':>6} {'FTSP':>6} {'commit':>6}")
    rows = []
    for label, p, mag, bfrac, bmag in CONDITIONS:
        acc = {'bc': [], 'bc_skip': [], 'cluster': [], 'ftsp': [], 'commit': []}
        for r in range(args.seeds):
            seed = fh.BASE_SEED + 500 + r
            for name, fn in (('bc', main_all.simulate_bc), ('bc_skip', main_all.simulate_bc),
                             ('cluster', main_all.simulate_cluster), ('ftsp', main_all.simulate_ftsp)):
                fh.configure(**ADOPTED)
                main_all.LOCAL_SKIP_FLAGGED = name == 'bc_skip'
                main_all.MEAS_OUTLIER_P, main_all.MEAS_OUTLIER_S = p, mag
                main_all.MEAS_BIAS_FRAC, main_all.MEAS_BIAS_S = bfrac, bmag
                sats = main_all.initialize_satellites(
                    args.n, int(round(0.05 * args.n)),
                    malfunction_mean=blt_params.value('osc_nominal_hz'),
                    malfunction_stddev=blt_params.ppb_to_hz(ADOPTED['faulty']),
                    malfunction_drift_bias=ADOPTED['bias'] * 1e-9,
                    cluster_aligned=True, cluster_pick='random', seed=seed)
                if name == 'bc':
                    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[])
                perf = fn(sats, args.ticks, 12, sim_seed=seed)
                acc[name].append(np.mean([d.rmse_normal for d in perf[-steady:]]) * 1e9)
                if name == 'bc':
                    d = main_all.BC_DIAG
                    rounds = d['commit'] + d['skip']
                    acc['commit'].append(d['commit'] / rounds if rounds else np.nan)
                fh.reset_levers()
        main_all.LOCAL_SKIP_FLAGGED = False
        main_all.MEAS_OUTLIER_P = main_all.MEAS_OUTLIER_S = 0.0
        main_all.MEAS_BIAS_FRAC = main_all.MEAS_BIAS_S = 0.0
        m = {k: float(np.mean(v)) for k, v in acc.items()}
        print(f"{label:>14} | {m['bc']:>6.2f} {m['bc_skip']:>8.2f} {m['cluster']:>6.2f} {m['ftsp']:>6.2f} "
              f"{100 * m['commit']:>5.0f}%", flush=True)
        rows.append({'n': args.n, 'condition': label, 'outlier_p': p, 'outlier_s': mag,
                     'bias_frac': bfrac, 'bias_s': bmag, **m})
    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
