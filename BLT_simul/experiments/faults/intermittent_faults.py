"""Does keeping the whole history matter? Intermittent degradation.

A satellite crossing the South Atlantic Anomaly degrades, recovers when it leaves,
and degrades again on the next pass. Its latest measurement can look healthy while
its record says otherwise. This tests whether choosing cluster heads from the
recorded history, rather than from the newest round alone, keeps such
satellites out of the vote.

A fraction of the satellites degrade for 6 s out of every 18 s (one sync round in
three), each with its own phase; the others stay healthy. A cluster head misreports
while its own oscillator is degraded (the union rule HEAD_FAULT 'both'; scattered faults
never fill a cluster, so the majority half never fires here).

  BLT, full history  head = best record over past rounds (ledger EMA, decay 0.7)
  BLT, latest only   head = best record in the most recent round (decay 0), i.e.
                     a node that keeps only the newest agreed state
  BLT, no ledger     head = member nearest the centroid
  ATS                head = member nearest the centroid, no vote

The adopted configuration otherwise. Reported: degraded heads per round, BLT commit rate, wrong
commits and the RMSE of the satellites that never degrade.

Every (fraction, arm, seed) run is written to intermittent_faults_runs.csv so the
arms can be compared seed by seed; intermittent_faults.csv holds the summary with
the spread of the degraded-head count.

Run:  python experiments/faults/intermittent_faults.py --seeds 64 --jobs 36
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
import os

import numpy as np

import main_all
import blt_config

K = 12
BASE_SEED = 20260916
ROUND = blt_config.CYCLE_TICKS
ARMS = [('BLT, full history', 'bc', 'history', 0.7),
        ('BLT, latest only', 'bc', 'history', 0.0),
        ('BLT, no ledger', 'bc', 'centroid', 0.7),
        ('ATS', 'cluster', 'centroid', 0.7)]


def schedule(n, frac, seed, pattern='random', rounds=64):
    """Intermittent degradation, on for one round in three on average.

    random    each intermittent satellite is degraded in each round independently with
              probability 1/3. Memoryless, so the newest round says nothing about the
              next one, the fair test of "is one round of history enough?".
    periodic  degraded for one round in every three with a fixed phase. The earlier
              version: under it "healthy in the newest round" means "one round closer to
              the next degraded round", which made the latest-round policy WORSE than no
              record at all, an artefact of the round-robin, not of the ledger.
    """
    rng = np.random.default_rng(seed + 77)
    who = rng.random(n) < frac
    rate = rng.normal(blt_config.FAULTY_BIAS_PPB, blt_config.FAULTY_PPB, n) * 1e-9
    sch = {'extra': np.where(who, rate * main_all.TIME_TICK, 0.0),
           'period': 3 * ROUND, 'on': ROUND,
           'phase': rng.integers(0, 3, n) * ROUND}
    if pattern == 'random':
        sch['draws'] = rng.random((rounds, n)) < 1.0 / 3.0
        sch['round_ticks'] = ROUND
    return sch


_W = {}


def _init_worker(n, ticks, pattern='random'):
    _W['n'], _W['ticks'], _W['pattern'] = n, ticks, pattern
    blt_config.apply(main_all)


def one_run(job):
    """One (fraction, arm, seed) run -> row. Kept separate so the arms can be
    compared seed by seed: the spread between them decides whether a difference
    like 'latest only' vs 'no ledger' is a real effect or seed noise."""
    frac, label, alg, policy, decay, r = job
    seed = BASE_SEED + r
    sats = main_all.initialize_satellites(_W['n'], 0, seed=seed)
    main_all.FAULT_SCHEDULE = schedule(_W['n'], frac, seed, _W.get('pattern', 'random'),
                                       rounds=_W['ticks'] // ROUND + 2)
    main_all.HEAD_FAULT, main_all.HEAD_POLICY, main_all.LEDGER_DECAY = 'both', policy, decay
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[])
    fn = main_all.simulate_bc if alg == 'bc' else main_all.simulate_cluster
    perf = fn(sats, _W['ticks'], K, sim_seed=seed)
    d = main_all.BC_DIAG
    rounds = d['commit'] + d['skip']
    row = {'n': _W['n'], 'intermittent_frac': frac, 'arm': label, 'seed': seed,
           'rmse': float(np.mean([p.rmse_normal for p in perf[-(_W['ticks'] // 4):]])) * 1e9}
    if alg == 'bc':
        row['liars'] = float(np.mean(d['liars'][3:])) if len(d['liars']) > 3 else float('nan')
        row['commit'] = d['commit'] / rounds if rounds else float('nan')
        row['bad'] = d['bad_commit'] / rounds if rounds else float('nan')
    else:
        row['liars'] = row['commit'] = row['bad'] = float('nan')
    main_all.FAULT_SCHEDULE = None
    main_all.HEAD_FAULT, main_all.HEAD_POLICY, main_all.LEDGER_DECAY = 'majority', 'centroid', 0.7
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=blt_config.N_SATS)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--ticks', type=int, default=12 * ROUND)
    ap.add_argument('--fractions', default='0.3,0.6')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--pattern', choices=('random', 'periodic'), default='random',
                    help='random: memoryless, 1/3 per round (default); periodic: the old round-robin')
    args = ap.parse_args()
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    steady = args.ticks // 4

    blt_config.apply(main_all)
    print(blt_config.describe())
    print(f'intermittent degradation: 6 s on / 12 s off per satellite, N={args.n}, '
          f'{args.seeds} seeds, {args.ticks // ROUND} rounds')
    print(f"{'intermittent':>12} {'arm':>18} | {'bad heads':>9} {'commit':>7} {'wrong':>6} {'RMSE ns':>8}")
    import multiprocessing as mp
    jobs = [(frac, label, alg, policy, decay, r)
            for frac in (float(x) for x in args.fractions.split(','))
            for label, alg, policy, decay in ARMS
            for r in range(args.seeds)]
    runs = []
    with mp.get_context('spawn').Pool(args.jobs, _init_worker, (args.n, args.ticks, args.pattern)) as pool:
        for row in pool.imap_unordered(one_run, jobs):
            runs.append(row)
            print(f"  [{len(runs)}/{len(jobs)}] {100 * row['intermittent_frac']:.0f}% "
                  f"{row['arm']:>18} seed {row['seed']}: bad heads {row['liars']:.2f} "
                  f"RMSE {row['rmse']:.2f}", flush=True)
    tag = '' if args.pattern == 'random' else '_periodic'
    with open(os.path.join(out_dir, f'intermittent_faults_runs{tag}.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(runs[0])); w.writeheader()
        w.writerows(sorted(runs, key=lambda x: (x['intermittent_frac'], x['arm'], x['seed'])))

    rows = []
    for frac in (float(x) for x in args.fractions.split(',')):
        for label, *_ in ARMS:
            sel = [x for x in runs if x['intermittent_frac'] == frac and x['arm'] == label]
            m = {k: float(np.nanmean([x[k] for x in sel])) for k in ('liars', 'commit', 'bad', 'rmse')}
            sd = {'liars_sd': float(np.nanstd([x['liars'] for x in sel], ddof=1)),
                  'liars_min': float(np.nanmin([x['liars'] for x in sel])),
                  'liars_max': float(np.nanmax([x['liars'] for x in sel]))}
            f = lambda x, pct=False: '-' if np.isnan(x) else (f'{100 * x:.0f}%' if pct else f'{x:.2f}')
            print(f"{100 * frac:>11.0f}% {label:>18} | {f(m['liars']):>9} {f(m['commit'], True):>7} "
                  f"{f(m['bad'], True):>6} {m['rmse']:>8.2f}  (bad heads sd {sd['liars_sd']:.2f}, "
                  f"{sd['liars_min']:.2f}-{sd['liars_max']:.2f})", flush=True)
            rows.append({'n': args.n, 'intermittent_frac': frac, 'arm': label,
                         'seeds': len(sel), **m, **sd})
    with open(os.path.join(out_dir, f'intermittent_faults{tag}.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
