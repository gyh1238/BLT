"""What each modelling effect contributes, measured one at a time.

Each arm adds one effect to the one before it, on the same seeds and the same
initial states, so the column that moves is the effect that moved it. This is
how the error budget in the documentation is arrived at.

  A base        cadences local 2.7 s, global 5.5 s, ideal links
  B cadence     local = global = 6 s (2 ISL terminals collect 683 members in 5.7 s)
  C links       B + distance-dependent ISL availability (blt_isl, 1-3 relay hops)
  D stamp-TDC   C + two-way timestamp noise on member exchanges, registry timing tier
                (100 ps LSB, 100 ps jitter)
  E stamp-100M  C + the same with a plain 100 MHz counter (10 ns LSB)
  F stamp-40M   C + a plain 40 MHz counter (25 ns LSB, the parameter's upper bound)
  G C+93ppb     C with a far worse degraded oscillator, 93 ppb against the
                registry's 27.5, as the upper end of the degradation axis
  H E+93ppb     E with that oscillator

D, E and F change one stated hardware assumption, the timestamp counter, and
nothing in the protocols, so the spread between them is what the choice of
counter is worth. G and H do the same for the degraded oscillator. Neither
axis is adjusted to meet a number: both are swept across their registry
range, and `blt_params.py` holds each bound with its source.

Run:  python experiments/accuracy/effect_budget.py            # N = 8,192, 2 seeds
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
import dataclasses

import numpy as np

import blt_params
import engine_profiles
import main_all

K = 12
BASE_SEED = 20260914
PUBLISHED = {'bc': 8.8, 'cluster': 14.4, 'ftsp': 17.2}

ARMS = [
    ('A published', dict(cadence=False, links=False, noise=False, lsb=None)),
    ('B cadence', dict(cadence=True, links=False, noise=False, lsb=None)),
    ('C links', dict(cadence=True, links=True, noise=False, lsb=None)),
    ('D stamp-TDC', dict(cadence=True, links=True, noise=True, lsb=None)),
    ('E stamp-100M', dict(cadence=True, links=True, noise=True, lsb=1e-8)),
    ('F stamp-40M', dict(cadence=True, links=True, noise=True, lsb=2.5e-8)),
    ('G C+93ppb', dict(cadence=True, links=True, noise=False, lsb=None, faulty_ppb=93.0)),
    ('H E+93ppb', dict(cadence=True, links=True, noise=True, lsb=1e-8, faulty_ppb=93.0)),
]


def set_lsb(value):
    name = 'timestamp_resolution_s'
    base = blt_params.REGISTRY[name]
    blt_params.REGISTRY[name] = dataclasses.replace(base, value=value)
    return base


def configure(arm):
    engine_profiles.apply(engine_profiles.FAULT_PROFILE, main_all)
    if arm['cadence']:
        for key in ('BC_LOCAL_CYCLE', 'BC_CLUSTER_CYCLE', 'ATS_LOCAL_CYCLE',
                    'ATS_GLOBAL_CYCLE', 'POSITION_UPDATE_CYCLE'):
            setattr(main_all, key, 6000)
    main_all.ISL_LINK_MODEL = arm['links']
    main_all.LOCAL_MEASUREMENT_NOISE = arm['noise']


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8192)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--fault', type=float, default=0.05)
    ap.add_argument('--ticks', type=int, default=40000)
    ap.add_argument('--out', default='result/fit/effect_budget.csv')
    args = ap.parse_args()
    steady = args.ticks // 4

    print(f'effect budget: N={args.n}, {args.seeds} seeds, {100 * args.fault:.0f}% faulty, '
          f'{args.ticks} ticks (mean of last {steady})')
    print(f"{'arm':>13} {'BLT':>7} {'ATS':>7} {'FTSP':>7} {'commit':>7}  "
          f"{'two-way sigma':>13} {'one-way sigma':>13}")
    print(f"{'(published)':>13} {PUBLISHED['bc']:>7.2f} {PUBLISHED['cluster']:>7.2f} "
          f"{PUBLISHED['ftsp']:>7.2f}")
    rows = []
    base_lsb = blt_params.REGISTRY['timestamp_resolution_s']
    for label, arm in ARMS:
        blt_params.REGISTRY['timestamp_resolution_s'] = base_lsb
        if arm['lsb'] is not None:
            set_lsb(arm['lsb'])
        configure(arm)
        acc = {'bc': [], 'cluster': [], 'ftsp': [], 'commit': []}
        for r in range(args.seeds):
            seed = BASE_SEED + r
            sats = main_all.initialize_satellites(
                args.n, int(round(args.fault * args.n)),
                malfunction_mean=blt_params.value('osc_nominal_hz'),
                malfunction_stddev=(blt_params.ppb_to_hz(arm['faulty_ppb'])
                                    if arm.get('faulty_ppb') else engine_profiles.FAULTY_STDDEV_HZ),
                malfunction_drift_bias=engine_profiles.FAULTY_DRIFT_BIAS,
                cluster_aligned=True, cluster_pick='random', seed=seed)
            for name, fn in (('bc', main_all.simulate_bc),
                             ('cluster', main_all.simulate_cluster),
                             ('ftsp', main_all.simulate_ftsp)):
                if name == 'bc':
                    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[])
                perf = fn(sats, args.ticks, K, sim_seed=seed)
                acc[name].append(np.mean([d.rmse_normal for d in perf[-steady:]]) * 1e9)
                if name == 'bc':
                    d = main_all.BC_DIAG
                    rounds = d['commit'] + d['skip']
                    acc['commit'].append(d['commit'] / rounds if rounds else np.nan)
        res = {k: float(np.mean(v)) for k, v in acc.items()}
        tw = main_all.blt_links.twoway_sigma_s() * 1e9
        ow = main_all.blt_links.oneway_sigma_s() * 1e9
        print(f"{label:>13} {res['bc']:>7.2f} {res['cluster']:>7.2f} {res['ftsp']:>7.2f} "
              f"{100 * res['commit']:>6.0f}%  {tw:>10.3f} ns {ow:>10.3f} ns", flush=True)
        rows.append({'arm': label, **res, 'twoway_sigma_ns': tw, 'oneway_sigma_ns': ow})
    blt_params.REGISTRY['timestamp_resolution_s'] = base_lsb
    main_all.ISL_LINK_MODEL = False
    main_all.LOCAL_MEASUREMENT_NOISE = False

    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
