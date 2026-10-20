"""How far the constellation's shared time walks away from true time.

The ablation ladder shows that removing the vote or the ledger leaves the relative
RMSE unchanged. That is structural, not a weak measurement: a wrong commit moves every
cluster by the same amount, so the satellites stay aligned with each other. What it
does move is the constellation's COMMON time, and it moves it again at every wrong
commit, so the damage accumulates, which a 40-s run and an inter-satellite metric
both hide.

This runs the three BLT arms of experiments/ledger/ablation_ladder.py for ten minutes and
records the mean clock of the nominal satellites against true time (the engines store
each clock as its accumulated error, so a perfect clock reads 0). Its slope is the
drift rate of the constellation's timescale, in ppb, the unit an oscillator is
specified in, so it can be read against a single healthy clock (1 ppb).

  BLT-SAND (published)   hierarchy + vote + ledger-based head selection
  no ledger record       heads chosen by position
  no vote                the proposal is distributed unverified

Conditions are the two of the ladder in which a component acts: a degraded region
(25%, a spatial patch that ignores cluster borders) and degraded individuals (25%,
scattered). One head-fault rule, the adopted configuration, failed-round fallback on, as in the ladder.

Output: result/runs/timescale_drift.csv (summary), timescale_drift_runs.csv (per seed),
        timescale_drift_series.csv (common time against true time, one row per second)

Run:  python experiments/ledger/timescale_drift.py --seeds 4 --jobs 12
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

import ablation_ladder as ladder
import main_all
import blt_config

K = 12
ARMS = [a for a in ladder.ARMS if a[0] in ('BLT-SAND (published)', 'no ledger record', 'no vote')]
CONDITIONS = [c for c in ladder.CONDITIONS if not c[0].startswith('headline')]
SAMPLE = 1000          # ticks between samples of the common time (1 s)
SETTLE_S = 60.0        # the slope is fitted after the first minute

_W = {}


def _init_worker(n, ticks):
    _W.update(n=n, ticks=ticks)
    blt_config.apply(main_all)


def one_run(job):
    label, hier, vote, ledger, cond, r = job
    cond_label, frac, placement, head_rule = cond
    seed = ladder.BASE_SEED + r
    sats = ladder.degraded(_W['n'], frac, seed, placement)
    main_all.HEAD_FAULT = 'both'   # one rule across every arm (ablation_ladder)
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[], migrated=[],
                            ref_err=[])
    perf = ladder.simulate_blt_arm(sats, _W['ticks'], K, vote, ledger, sim_seed=seed)
    d = main_all.BC_DIAG
    rounds = d['commit'] + d['skip']
    t = np.arange(0, len(perf), SAMPLE) * main_all.TIME_TICK
    common = np.array([perf[i].reference for i in range(0, len(perf), SAMPLE)])
    keep = t >= SETTLE_S
    slope = float(np.polyfit(t[keep], common[keep], 1)[0]) if keep.sum() > 2 else float('nan')
    tail = len(perf) // 4
    row = {'arm': label, 'condition': cond_label, 'seed': seed,
           'drift_ppb': slope * 1e9,
           'offset_end_ns': float(common[-1]) * 1e9,
           'rmse': float(np.mean([p.rmse_normal for p in perf[-tail:]])) * 1e9,
           'rmse_true': float(np.mean([p.rmse_absolute for p in perf[-tail:]])) * 1e9,
           'commit': d['commit'] / rounds if rounds else float('nan'),
           'bad': d['bad_commit'] / rounds if rounds else float('nan')}
    series = [{'arm': label, 'condition': cond_label, 'seed': seed, 't_s': float(ti),
               'common_ns': float(ci) * 1e9} for ti, ci in zip(t, common)]
    main_all.HEAD_FAULT, main_all.HEAD_POLICY = 'majority', 'centroid'
    main_all.FAILED_ROUND_FALLBACK = False
    return row, series


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=blt_config.N_SATS)
    ap.add_argument('--seeds', type=int, default=4)
    ap.add_argument('--minutes', type=float, default=10.0)
    ap.add_argument('--jobs', type=int, default=1)
    args = ap.parse_args()
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    ticks = int(args.minutes * 60 / main_all.TIME_TICK)
    blt_config.apply(main_all)
    print(blt_config.describe())
    print(f'\n== common-time drift over {args.minutes:g} min, N={args.n}, {args.seeds} seeds')

    import multiprocessing as mp
    jobs = [(label, h, v, l, c, r) for c in CONDITIONS for label, h, v, l in ARMS
            for r in range(args.seeds)]
    runs, series = [], []
    with mp.get_context('spawn').Pool(args.jobs, _init_worker, (args.n, ticks)) as pool:
        for row, ser in pool.imap_unordered(one_run, jobs):
            runs.append(row)
            series += ser
            print(f"  [{len(runs)}/{len(jobs)}] {row['condition']:>38} {row['arm']:>22} "
                  f"seed {row['seed']}: drift {row['drift_ppb']:+.3f} ppb  "
                  f"offset {row['offset_end_ns']:+.1f} ns  rmse {row['rmse']:.2f}  "
                  f"wrong {row['bad']:.3f}", flush=True)

    for name, rows in (('timescale_drift_runs.csv', runs), ('timescale_drift_series.csv', series)):
        with open(os.path.join(out_dir, name), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    out = []
    for c in CONDITIONS:
        print(f"\n{c[0]:>38}  {'arm':>22} | {'|drift| ppb':>11} {'offset ns':>10} {'rmse':>6} "
              f"{'rmse true':>9} {'commit':>7} {'wrong':>6}")
        for label, *_ in ARMS:
            sel = [x for x in runs if x['arm'] == label and x['condition'] == c[0]]
            m = {k: float(np.nanmean([x[k] for x in sel]))
                 for k in ('drift_ppb', 'offset_end_ns', 'rmse', 'rmse_true', 'commit', 'bad')}
            m['abs_drift_ppb'] = float(np.nanmean([abs(x['drift_ppb']) for x in sel]))
            m['abs_offset_end_ns'] = float(np.nanmean([abs(x['offset_end_ns']) for x in sel]))
            print(f"{'':>38}  {label:>22} | {m['abs_drift_ppb']:>11.3f} {m['abs_offset_end_ns']:>10.1f} "
                  f"{m['rmse']:>6.2f} {m['rmse_true']:>9.1f} {100 * m['commit']:>6.0f}% "
                  f"{100 * m['bad']:>5.1f}%", flush=True)
            out.append({'n': args.n, 'minutes': args.minutes, 'condition': c[0], 'arm': label,
                        'seeds': len(sel), **m})
    with open(os.path.join(out_dir, 'timescale_drift.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print(f'wrote {out_dir}/timescale_drift*.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
