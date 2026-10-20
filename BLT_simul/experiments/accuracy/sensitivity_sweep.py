"""Sweep the oscillator, aggregation and ranging parameters and report what each
setting reaches.

One row per parameter point, all three schemes measured on the same seeds and the
same initial states, so a column that moves is the parameter that moved it. The
`--lsb` and `--jitter` options sweep the timestamp counter instead, which is how
`result/fit/jitter_sweep.csv` behind the timestamp-sensitivity panel is
produced.

Base configuration:
  - local = global = 6 s, N = 8,192 in the confirmation stage
  - distance-dependent ISL links (blt_isl), members relay over 1-3 hops
  - every derived threshold recomputed from the parameters being moved:
    agree_tol_s (healthy ppb x local cycle), faulty_report_error_s and
    faulty_relay_timestamp_error_s (faulty ppb x cycle)

Parameters swept (all registered in blt_params with a range and a source class):
  osc_healthy_ppb        spread of healthy oscillators (physical)
  osc_faulty_ppb         degraded oscillator spread (design, bounded by the
                         +-30 ppb/year ageing specification)
  osc_faulty_bias_ppb    coherent one-directional offset of a degraded oscillator
                         (design), the term a mean aggregation is pulled by
  ats_reconcile_alpha    ATS global correction strength (design)
  range_uncertainty_m    a-priori ISL range knowledge, sets FTSP's one-way residual
                         (physical; 0.28 m is in-orbit GNSS, Hauschild 2021)
  ftsp_flood_cycle_ticks FTSP re-flood period (design; --flood, shorter favours FTSP)
  timestamp_resolution_s timestamp counter LSB (design; --lsb turns on member-exchange
                         noise, which also enters FTSP's one-way hops)
  timestamp_jitter_s     stamping jitter (physical; --jitter)

The healthy oscillator stays at 1 ppb: the manuscript's argument is that 1 ppb
drifts 1 ns per second, so a synchronization within about 10 s keeps the network
inside 10 ns.

Run:  python experiments/accuracy/sensitivity_sweep.py --stage coarse        # N=500, fast
      python experiments/accuracy/sensitivity_sweep.py --stage confirm --points "3,27.5,9,0.5,1.0;..."
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
import itertools

import numpy as np

import blt_params
import engine_profiles
import main_all

K = 12
BASE_SEED = 20260914
CYCLE_TICKS = 6000
FLOOD_TICKS = 750
LSB_S = None   # timestamp LSB; None keeps member exchanges noiseless
JITTER_S = None   # timestamp jitter override; None keeps the registry value
_ORIGINAL = dict(blt_params.REGISTRY)


def set_levers(values: dict):
    """Replace registry values for this run; restore with reset_levers()."""
    blt_params.REGISTRY.clear()
    blt_params.REGISTRY.update(_ORIGINAL)
    for name, v in values.items():
        blt_params.REGISTRY[name] = dataclasses.replace(_ORIGINAL[name], value=v)


def reset_levers():
    blt_params.REGISTRY.clear()
    blt_params.REGISTRY.update(_ORIGINAL)


def configure(healthy, faulty, bias, alpha, range_m):
    set_levers({
        'osc_healthy_ppb': healthy,
        'osc_faulty_ppb': faulty,
        'osc_faulty_bias_ppb': bias,
        'ats_reconcile_alpha': alpha,
        'range_uncertainty_m': range_m,
        'bc_local_cycle_ticks': CYCLE_TICKS,
        'bc_cluster_cycle_ticks': CYCLE_TICKS,
        'ftsp_flood_cycle_ticks': FLOOD_TICKS,
        **({'timestamp_resolution_s': LSB_S} if LSB_S is not None else {}),
        **({'timestamp_jitter_s': JITTER_S} if JITTER_S is not None else {}),
    })
    # the derived FTSP relay error follows the faulty oscillator
    blt_params.REGISTRY['faulty_relay_timestamp_error_s'] = dataclasses.replace(
        _ORIGINAL['faulty_relay_timestamp_error_s'], value=blt_params.faulty_relay_error_s())

    engine_profiles.apply(engine_profiles.FAULT_PROFILE, main_all)
    for key in ('BC_LOCAL_CYCLE', 'BC_CLUSTER_CYCLE', 'ATS_LOCAL_CYCLE',
                'ATS_GLOBAL_CYCLE', 'POSITION_UPDATE_CYCLE'):
        setattr(main_all, key, CYCLE_TICKS)
    main_all.NORMAL_OSC_STDDEV = blt_params.ppb_to_hz(healthy)
    main_all.BC_AGREE_TOL = blt_params.agree_tol_s()
    main_all.FAULTY_REPORT_ERROR = blt_params.faulty_report_error_s()
    main_all.ATS_RECONCILE_ALPHA = alpha
    main_all.FTSP_FLOOD_CYCLE = FLOOD_TICKS
    main_all.ISL_LINK_MODEL = True
    main_all.CLUSTER_WARM_START = True  # stable clusters across re-clustering
    main_all.LOCAL_MEASUREMENT_NOISE = LSB_S is not None


def run_point(n, seeds, ticks, healthy, faulty, bias, alpha, range_m, fault_frac):
    configure(healthy, faulty, bias, alpha, range_m)
    steady = ticks // 4
    acc = {'bc': [], 'cluster': [], 'ftsp': [], 'commit': [],
           'bc_all': [], 'cluster_all': [], 'ftsp_all': []}
    for r in range(seeds):
        seed = BASE_SEED + r
        sats = main_all.initialize_satellites(
            n, int(round(fault_frac * n)),
            malfunction_mean=blt_params.value('osc_nominal_hz'),
            malfunction_stddev=blt_params.ppb_to_hz(faulty),
            malfunction_drift_bias=bias * 1e-9,
            cluster_aligned=True, cluster_pick='random', seed=seed)
        for name, fn in (('bc', main_all.simulate_bc),
                         ('cluster', main_all.simulate_cluster),
                         ('ftsp', main_all.simulate_ftsp)):
            if name == 'bc':
                main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[])
            perf = fn(sats, ticks, K, sim_seed=seed)
            acc[name].append(np.mean([d.rmse_normal for d in perf[-steady:]]) * 1e9)
            # all-satellite RMSE, for the manuscript's metric question
            acc[name + '_all'].append(np.mean([d.rmse_all for d in perf[-steady:]]) * 1e9)
            if name == 'bc':
                d = main_all.BC_DIAG
                rounds = d['commit'] + d['skip']
                acc['commit'].append(d['commit'] / rounds if rounds else np.nan)
    reset_levers()
    res = {k: float(np.mean(v)) for k, v in acc.items()}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=('coarse', 'confirm'), default='coarse')
    ap.add_argument('--n', type=int, default=None)
    ap.add_argument('--seeds', type=int, default=None)
    ap.add_argument('--ticks', type=int, default=None)
    ap.add_argument('--fault', type=float, default=0.05)
    ap.add_argument('--healthy', default='1,2,3,4')
    ap.add_argument('--faulty', default='27.5,93')
    ap.add_argument('--bias', default='9')
    ap.add_argument('--alpha', default='0.5')
    ap.add_argument('--range', dest='range_m', default='1.0')
    ap.add_argument('--points', default=None,
                    help='explicit "healthy,faulty,bias,alpha,range;..." instead of the grid')
    ap.add_argument('--flood', type=int, default=750, help='FTSP re-flood period [ticks]')
    ap.add_argument('--lsb', type=float, default=None,
                    help='timestamp LSB [s]; turns on member-exchange noise (e.g. 1e-8 = 100 MHz counter)')
    ap.add_argument('--jitter', default=None,
                    help='timestamp jitter [s]; a comma-separated list sweeps it '
                         '(registry 1e-10)')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    global FLOOD_TICKS, LSB_S, JITTER_S
    FLOOD_TICKS = args.flood
    LSB_S = args.lsb
    jitters = ([float(x) for x in str(args.jitter).split(',')]
               if args.jitter is not None else [None])
    JITTER_S = jitters[0]

    coarse = args.stage == 'coarse'
    n = args.n or (500 if coarse else 8192)
    seeds = args.seeds or (1 if coarse else 3)
    ticks = args.ticks or (24000 if coarse else 40000)
    out = args.out or f'result/fit/sweep_{args.stage}.csv'

    if args.points:
        points = [tuple(float(x) for x in p.split(',')) for p in args.points.split(';')]
    else:
        f = lambda s: [float(x) for x in s.split(',')]
        points = list(itertools.product(f(args.healthy), f(args.faulty), f(args.bias), f(args.alpha), f(args.range_m)))

    print(f'fit ({args.stage}): N={n}, {seeds} seed(s), {ticks} ticks, {100 * args.fault:.0f}% faulty, '
          f'cycles {CYCLE_TICKS / 1000:.0f} s, FTSP flood {FLOOD_TICKS} ms, timestamp LSB {LSB_S} jitter {JITTER_S}, '
          f'ISL links on')
    print(f"{'healthy':>8} {'faulty':>7} {'bias':>5} {'alpha':>6} {'range':>6} | {'BLT':>6} {'ATS':>6} {'FTSP':>6} "
          f"{'commit':>6}")
    rows = []
    for jitter in jitters:
        JITTER_S = jitter
        for healthy, faulty, bias, alpha, range_m in points:
            r = run_point(n, seeds, ticks, healthy, faulty, bias, alpha, range_m, args.fault)
            print(f"{healthy:>8.2f} {faulty:>7.1f} {bias:>5.1f} {alpha:>6.2f} {range_m:>6.2f} | "
                  f"{r['bc']:>6.2f} {r['cluster']:>6.2f} {r['ftsp']:>6.2f} "
                  f"{100 * r['commit']:>5.0f}% | "
                  f"| all-sat {r['bc_all']:.2f} / {r['cluster_all']:.2f} / "
                  f"{r['ftsp_all']:.2f}", flush=True)
            rows.append({'n': n, 'seeds': seeds, 'healthy_ppb': healthy,
                         'faulty_ppb': faulty, 'faulty_bias_ppb': bias,
                         'ftsp_flood_ticks': FLOOD_TICKS, 'lsb_s': LSB_S,
                         'jitter_s': JITTER_S, 'ats_alpha': alpha,
                         'range_m': range_m, **r})
    with open(out, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
