"""The adopted configuration time series: the accuracy panel's curves and the no-sync reference.

Saves the per-tick error of BLT, ATS and FTSP (healthy-satellite RMSE) and of no
synchronization (all-satellite RMSE), so the accuracy figure and the
no-synchronization drift figure come from a file instead of a note.

Output: result/runs/timeseries.csv  (one row every 50 ms; columns in ns)

Run:  python experiments/accuracy/timeseries.py              # N = 8,192, 1 seed
      python experiments/accuracy/timeseries.py --seeds 3    # mean over seeds
      python experiments/accuracy/timeseries.py --stride 1 --seeds 8 --jobs 8
      python experiments/accuracy/timeseries.py --stride 1   # every tick (40,000 rows)
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
import os

import numpy as np
import pandas as pd

import blt_params
import main_all
import blt_config

K = 12
BASE_SEED = 20260914
STRIDE = 50


def run_seed(job):
    """All four schemes for one seed -> ({column: series}, log lines)."""
    n, fault, ticks, stride, seed = job
    blt_config.apply(main_all)
    sats = main_all.initialize_satellites(
        n, int(round(fault * n)),
        malfunction_mean=blt_params.value('osc_nominal_hz'),
        malfunction_stddev=blt_config.FAULTY_STDDEV_HZ,
        malfunction_drift_bias=blt_config.FAULTY_DRIFT_BIAS,
        cluster_aligned=True, cluster_pick='random', seed=seed)
    cols, lines = {}, []
    for name, fn in (('bc', main_all.simulate_bc), ('cluster', main_all.simulate_cluster),
                     ('ftsp', main_all.simulate_ftsp)):
        perf = fn(sats, ticks, K, sim_seed=seed)
        cols[name] = np.array([d.rmse_normal for d in perf[::stride]]) * 1e9
        lines.append(f'  seed {seed} {name}: steady {np.mean([d.rmse_normal for d in perf[-ticks // 4:]]) * 1e9:.2f} ns')
    perf = main_all.simulate_none(sats, ticks, K, sim_seed=seed)
    cols['none_all'] = np.array([d.rmse_all for d in perf[::stride]]) * 1e9
    cols['none_healthy'] = np.array([d.rmse_normal for d in perf[::stride]]) * 1e9
    # The last sample, whatever --ticks was asked for; the default is 40 s.
    last = perf[-1]
    lines.append(f'  seed {seed} no sync @{ticks / 1000:g} s: all {last.rmse_all * 1e9:.1f} ns, '
                 f'healthy {last.rmse_normal * 1e9:.1f} ns')
    return cols, lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=blt_config.N_SATS)
    ap.add_argument('--seeds', type=int, default=1)
    ap.add_argument('--ticks', type=int, default=40000)
    ap.add_argument('--fault', type=float, default=0.05)
    ap.add_argument('--jobs', type=int, default=1, help='seeds run in parallel processes')
    ap.add_argument('--stride', type=int, default=STRIDE,
                    help='keep one row every STRIDE ticks (1 = per tick, as the manuscript panel)')
    args = ap.parse_args()
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    blt_config.apply(main_all)
    print(blt_config.describe())

    cols = {'bc': [], 'cluster': [], 'ftsp': [], 'none_all': [], 'none_healthy': []}
    jobs = [(args.n, args.fault, args.ticks, args.stride, BASE_SEED + r) for r in range(args.seeds)]
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.get_context('spawn').Pool(min(args.jobs, len(jobs))) as pool:
            results = pool.map(run_seed, jobs)
    else:
        results = [run_seed(j) for j in jobs]
    for seed_cols, lines in results:  # seed order, whatever finished first
        print('\n'.join(lines), flush=True)
        for k, v in seed_cols.items():
            cols[k].append(v)

    df = pd.DataFrame({k: np.mean(v, axis=0) for k, v in cols.items()})
    df.insert(0, 't_ms', np.arange(len(df)) * args.stride)
    path = os.path.join(out_dir, 'timeseries.csv')
    df.to_csv(path, index=False, float_format='%.4f')
    print(f'wrote {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
