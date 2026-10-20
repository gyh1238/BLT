"""What the ledger's history buys over consensus alone.

The comparison is against a scheme that uses the same consensus but no
blockchain. The difference between the two is memory: consensus alone
agrees on the current timing state and forgets; the ledger keeps the agreed record
of every round, and the record a satellite actually needs is each satellite's
precision.

The measurable use of that record is choosing who reports for a cluster. Here a
cluster head misreports when its OWN oscillator is degraded (the union rule HEAD_FAULT
'both'; scattered faults never fill a cluster, so the majority half never fires here), and
faults are scattered at random, so any satellite can end up as a head.

  BLT + ledger     head = best recorded precision among the 10 members nearest the
                   centroid (HEAD_POLICY 'history'); quorum vote
  BLT, no ledger   head = member nearest the centroid; the same quorum vote
  ATS              head = member nearest the centroid; no vote, no ledger

Everything else is as adopted (model/blt_config.py). Reported per member-fault fraction:
healthy-satellite RMSE, degraded heads per round (after the first round, when no
record exists yet), commit rate, wrong commits.

Run:  python experiments/ledger/ledger_history.py            # N = 8,192, 2 seeds
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
ARMS = [('BLT + ledger', 'bc', 'history'),
        ('BLT, no ledger', 'bc', 'centroid'),
        ('ATS', 'cluster', 'centroid')]


_W = {}


def _init_worker(n, ticks):
    _W.update(n=n, ticks=ticks)
    fh.FLOOD_TICKS, fh.LSB_S, fh.JITTER_S = 450, 1e-8, 3e-9


def one_run(job):
    """One (fraction, arm, seed) run. The degraded-head count of the no-ledger arm is
    Binomial(12, fraction) with sd ~1.5, so the mean only settles with many seeds."""
    frac, label, alg, policy, r = job
    fh.configure(**ADOPTED)
    main_all.HEAD_FAULT = 'both'
    main_all.HEAD_POLICY = policy
    seed = fh.BASE_SEED + 300 + r
    sats = main_all.initialize_satellites(
        _W['n'], int(round(frac * _W['n'])),
        malfunction_mean=blt_params.value('osc_nominal_hz'),
        malfunction_stddev=blt_params.ppb_to_hz(ADOPTED['faulty']),
        malfunction_drift_bias=ADOPTED['bias'] * 1e-9, seed=seed)
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[])
    fn = main_all.simulate_bc if alg == 'bc' else main_all.simulate_cluster
    perf = fn(sats, _W['ticks'], 12, sim_seed=seed)
    steady = _W['ticks'] // 4
    row = {'n': _W['n'], 'faulty_frac': frac, 'arm': label, 'seed': seed,
           'rmse': float(np.mean([d.rmse_normal for d in perf[-steady:]])) * 1e9}
    if alg == 'bc':
        d = main_all.BC_DIAG
        rounds = d['commit'] + d['skip']
        row['commit'] = d['commit'] / rounds if rounds else float('nan')
        row['bad'] = d['bad_commit'] / rounds if rounds else float('nan')
        # skip the first round: heads are chosen before any satellite has a record
        row['liars'] = float(np.mean(d['liars'][1:])) if len(d['liars']) > 1 else float('nan')
    else:
        pos = np.array([s['position'] for s in sats])
        heads = main_all.select_heads(pos, main_all.cluster_indices_from_kmeans(pos, 12), False)
        faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in sats])
        row['liars'] = float(faulty[heads].sum())
        row['commit'] = row['bad'] = float('nan')
    fh.reset_levers()
    main_all.HEAD_FAULT, main_all.HEAD_POLICY = 'majority', 'centroid'
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8192)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--ticks', type=int, default=40000)
    ap.add_argument('--fractions', default='0.05,0.15,0.25,0.35')
    ap.add_argument('--out', default='result/runs/ledger_history.csv')
    ap.add_argument('--jobs', type=int, default=1)
    args = ap.parse_args()
    steady = args.ticks // 4

    fh.FLOOD_TICKS, fh.LSB_S, fh.JITTER_S = 450, 1e-8, 3e-9
    print(f'ledger history: N={args.n}, {args.seeds} seeds, faults scattered at random, '
          f'a head misreports when its own oscillator is degraded')
    print(f"{'faulty':>7} {'arm':>15} | {'RMSE ns':>8} {'bad heads':>9} {'commit':>7} {'wrong':>6}")
    import multiprocessing as mp
    jobs = [(frac, label, alg, policy, r)
            for frac in (float(x) for x in args.fractions.split(','))
            for label, alg, policy in ARMS
            for r in range(args.seeds)]
    runs = []
    with mp.get_context('spawn').Pool(args.jobs, _init_worker, (args.n, args.ticks)) as pool:
        for row in pool.imap_unordered(one_run, jobs):
            runs.append(row)
            print(f"  [{len(runs)}/{len(jobs)}] {100 * row['faulty_frac']:.0f}% {row['arm']:>15} "
                  f"seed {row['seed']}: bad heads {row['liars']:.2f}", flush=True)

    rows = []
    for frac in (float(x) for x in args.fractions.split(',')):
        for label, *_ in ARMS:
            sel = [x for x in runs if x['faulty_frac'] == frac and x['arm'] == label]
            m = {k: float(np.nanmean([x[k] for x in sel])) if
                 not all(np.isnan(x[k]) for x in sel) else float('nan')
                 for k in ('rmse', 'liars', 'commit', 'bad')}
            fmt = lambda x, pct=False: '-' if np.isnan(x) else (f'{100 * x:.0f}%' if pct else f'{x:.2f}')
            print(f"{100 * frac:>6.0f}% {label:>15} | {m['rmse']:>8.2f} {fmt(m['liars']):>9} "
                  f"{fmt(m['commit'], True):>7} {fmt(m['bad'], True):>6}", flush=True)
            rows.append({'n': args.n, 'faulty_frac': frac, 'arm': label, 'seeds': len(sel), **m})

    for row in rows:
        sel = [x for x in runs if x['faulty_frac'] == row['faulty_frac'] and x['arm'] == row['arm']]
        for k in ('liars', 'commit'):
            v = [x[k] for x in sel if not np.isnan(x[k])]
            row[k + '_min'] = float(min(v)) if v else float('nan')
            row[k + '_max'] = float(max(v)) if v else float('nan')
    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    runs_path = args.out.replace('.csv', '_runs.csv')
    with open(runs_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0]))
        w.writeheader()
        w.writerows(runs)
    print(f'wrote {args.out} and {runs_path}')
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
