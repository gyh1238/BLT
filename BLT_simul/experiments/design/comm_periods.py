"""Synchronization period each scheme needs for the 10 ns target (manuscript Fig. 4(c)).

The communication-efficiency panel sets each scheme's cycle to the longest one
that still meets 10 ns and counts messages per second there, so the periods
have to be measured before the message rates mean anything. This sweeps each
scheme's cycle at the operating point (N = 8,192, 5% degraded, clusters placed
as in the headline) and reports where each one crosses:

  BLT   local = global period in {3, 6, 9, 12} s
  ATS   local = global period in {1, 2, 3, 6} s
  FTSP  flood period in {0.1, 0.2, 0.45, 1.0} s

A scheme that stays above 10 ns at its shortest period has no qualifying cycle;
that is reported rather than extrapolated.

--timestamps sweeps the timestamping assumption (LSB:jitter in ns) for all three
schemes at once. Under the adopted 10 ns LSB + 3 ns jitter, FTSP has a period-independent
floor near 18 ns and never reaches the target, so the comparison has no common
operating point; a finer timestamp lowers every scheme's floor and can restore one.

Output: result/runs/comm_periods.csv   Run: python experiments/design/comm_periods.py --jobs 12
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

K = 12
BASE_SEED = 20260914
POINTS = ([('bc', t) for t in (3000, 6000, 9000, 12000)] +
          [('cluster', t) for t in (1000, 2000, 3000, 6000)] +
          [('ftsp', t) for t in (100, 200, 450, 1000)])


def parse_points(text):
    """'bc:3,6,9;cluster:1,2;ftsp:0.45,1' (seconds) -> [(alg, ticks), ...]."""
    out = []
    for part in text.split(';'):
        alg, periods = part.split(':')
        out += [(alg.strip(), int(round(float(t) * 1000))) for t in periods.split(',')]
    return out


def job(spec):
    import dataclasses
    import blt_params
    import main_all
    import blt_config
    alg, period, seed, n, ticks, lsb_ns, jitter_ns = spec
    blt_config.apply(main_all)
    if (lsb_ns, jitter_ns) != (blt_config.LSB_S * 1e9, blt_config.JITTER_S * 1e9):
        # Timestamping resolution and jitter, applied to all three schemes alike.
        # FTSP's error floor is a per-hop timestamp budget along the flood path,
        # not a period effect, so it is the one parameter that decides whether FTSP
        # has any period at which it reaches 10 ns.
        for name, value in (('timestamp_resolution_s', lsb_ns * 1e-9),
                            ('timestamp_jitter_s', jitter_ns * 1e-9)):
            blt_params.REGISTRY[name] = dataclasses.replace(blt_params.REGISTRY[name], value=value)
        blt_params.REGISTRY['faulty_relay_timestamp_error_s'] = dataclasses.replace(
            blt_params.REGISTRY['faulty_relay_timestamp_error_s'],
            value=blt_params.faulty_relay_error_s())
        main_all.BC_AGREE_TOL = blt_params.agree_tol_s()
    if alg == 'bc':
        main_all.BC_LOCAL_CYCLE = main_all.BC_CLUSTER_CYCLE = main_all.POSITION_UPDATE_CYCLE = period
        fn = main_all.simulate_bc
    elif alg == 'cluster':
        main_all.ATS_LOCAL_CYCLE = main_all.ATS_GLOBAL_CYCLE = period
        fn = main_all.simulate_cluster
    else:
        main_all.FTSP_FLOOD_CYCLE = period
        fn = main_all.simulate_ftsp
    sats = main_all.initialize_satellites(
        n, int(round(0.05 * n)), malfunction_mean=blt_params.value('osc_nominal_hz'),
        malfunction_stddev=blt_config.FAULTY_STDDEV_HZ, malfunction_drift_bias=blt_config.FAULTY_DRIFT_BIAS,
        cluster_aligned=True, cluster_pick='random', seed=seed)
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[], rounds=[], honest_spread=[])
    perf = fn(sats, ticks, K, sim_seed=seed)
    return {'alg': alg, 'period_s': period / 1000, 'seed': seed,
            'lsb_ns': lsb_ns, 'jitter_ns': jitter_ns,
            'rmse_ns': float(np.mean([d.rmse_normal for d in perf[-ticks // 4:]])) * 1e9}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8192)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--ticks', type=int, default=48000)
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--out', default='result/runs/comm_periods.csv')
    ap.add_argument('--timestamps', default='10:3',
                    help='LSB:jitter in ns, comma separated for several (e.g. "10:3,1:1")')
    ap.add_argument('--points', default=None,
                    help='periods in seconds per scheme, e.g. "bc:12,18,24;cluster:6,9;ftsp:1,2,4". '
                         'Default: the swept range of the manuscript panel')
    args = ap.parse_args()
    stamps = [tuple(float(x) for x in v.split(':')) for v in args.timestamps.split(',')]
    points = parse_points(args.points) if args.points else POINTS
    specs = [(a, t, BASE_SEED + r, args.n, args.ticks, lsb, jit)
             for lsb, jit in stamps for a, t in points for r in range(args.seeds)]
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.get_context('spawn').Pool(args.jobs) as pool:
            rows = pool.map(job, specs)
    else:
        rows = [job(s) for s in specs]
    import pandas as pd
    df = pd.DataFrame(rows).groupby(['lsb_ns', 'jitter_ns', 'alg', 'period_s'],
                                    as_index=False).rmse_ns.mean()
    df.to_csv(args.out, index=False)
    print(df.to_string(index=False))
    for (lsb, jit, alg), g in df.groupby(['lsb_ns', 'jitter_ns', 'alg']):
        ok = g[g.rmse_ns <= 10.0]
        print(f'{lsb:.0f} ns LSB + {jit:.0f} ns jitter, {alg}: longest period meeting 10 ns = '
              f'{ok.period_s.max() if len(ok) else "none in the swept range"}')
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
