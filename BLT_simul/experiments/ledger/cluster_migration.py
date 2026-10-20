"""Cross-cluster state verification: what a record has to survive.

Three functions should require the ledger rather than the
consensus, recovery after disconnection, tamper-evident history, and
*cross-cluster state verification*. Checking a proposal against one's own
cluster reference is the vote, not the ledger, so it cannot be the answer to the
third one. What does need an agreed, constellation-wide record is this: the
clustering follows the orbits, so satellites keep changing cluster, and the
cluster that has to choose a head sees satellites it has never measured.

Two parts:

  turnover   how fast membership changes. No simulation, positions are
             propagated and re-clustered, and the run reports the satellites
             that change cluster per update and the share that has changed at
             least once, i.e. how long a cluster-local record stays complete.
             The default hour-long window is needed to see the shape: the share
             rises almost linearly to about 15 min, then the rate falls roughly
             threefold and the curve creeps (48.7% at 10 min, 80.2% at 24 min,
             91.5% at 60 min). Two reasons, the warm-started partition ends up
             co-rotating with the constellation, so fewer satellites cross a
             boundary, and most of the crossings that remain are the same
             boundary satellites going back and forth (21% of moves are repeats
             in the first five minutes, 64% between 15 and 20 min).

  arms       the same degraded constellation with three ways of keeping the
             record. The vote, the filter, the periods and the fault model are
             identical; only the record changes.

               ledger        one agreed history; a satellite keeps its record
                             when it moves (LEDGER_SCOPE 'global')
               cluster-local the record belongs to the cluster that measured it,
                             so a satellite that moves arrives unknown
                             (LEDGER_SCOPE 'cluster')
               no ledger     no record at all: the head is the member nearest
                             the centroid

             Reported per arm: degraded heads per round, commit rate, wrong
             commits, and the RMSE of the satellites that never degrade.

Output: result/runs/cluster_migration_turnover.csv, cluster_migration.csv

Run:  python experiments/ledger/cluster_migration.py --turnover-only
      python experiments/ledger/cluster_migration.py --seeds 4 --jobs 12
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

import blt_params
import main_all
import blt_config

K = 12
BASE_SEED = 20260918
ROUND = blt_config.CYCLE_TICKS
# (label, head policy, ledger scope)
ARMS = [('BLT, ledger', 'history', 'global'),
        ('BLT, cluster-local record', 'history', 'cluster'),
        ('BLT, no ledger', 'centroid', 'global')]


def degraded(n, frac, seed):
    """Scattered degradation, as on the member axis."""
    return main_all.initialize_satellites(
        n, int(round(frac * n)),
        malfunction_mean=blt_params.value('osc_nominal_hz'),
        malfunction_stddev=blt_config.FAULTY_STDDEV_HZ,
        malfunction_drift_bias=blt_config.FAULTY_DRIFT_BIAS,
        cluster_pick='random', seed=seed)


def turnover(n, updates, seed):
    """Membership churn alone: no clocks, no synchronization."""
    sats = main_all.initialize_satellites(n, 0, seed=seed)
    pos = np.array([s['position'] for s in sats], dtype=float)
    vel = np.array([s['velocity'] for s in sats], dtype=float)
    ang = np.array([s.get('angular_velocity', 0.0) for s in sats], dtype=float)
    clusters = main_all.cluster_indices_from_kmeans(pos, K)
    prev = main_all._cluster_of(n, clusters)
    first = main_all._cluster_of(n, clusters)
    rows = []
    for u in range(1, updates + 1):
        pos = main_all.update_positions_vec(pos, vel, ang, main_all.POSITION_UPDATE_CYCLE)
        clusters = main_all.recluster(pos, K, clusters)
        cur = main_all._cluster_of(n, clusters)
        rows.append({'seed': seed, 'update': u,
                     'seconds': u * main_all.POSITION_UPDATE_CYCLE * main_all.TIME_TICK,
                     'moved': int((cur != prev).sum()),
                     'moved_frac': float((cur != prev).mean()),
                     'ever_moved_frac': float((cur != first).mean())})
        prev = cur
    return rows


_W = {}


def _init_worker(n, ticks, frac):
    _W.update(n=n, ticks=ticks, frac=frac)
    blt_config.apply(main_all)


def one_run(job):
    label, policy, scope, r = job
    seed = BASE_SEED + r
    sats = degraded(_W['n'], _W['frac'], seed)
    main_all.HEAD_FAULT, main_all.HEAD_POLICY, main_all.LEDGER_SCOPE = 'both', policy, scope
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[], migrated=[])
    perf = main_all.simulate_bc(sats, _W['ticks'], K, sim_seed=seed)
    d = main_all.BC_DIAG
    rounds = d['commit'] + d['skip']
    row = {'arm': label, 'seed': seed, 'faulty_frac': _W['frac'],
           # the first rounds have no record yet under any arm, so they are not
           # what separates them; drop one cycle as in the ledger experiment
           'liars': float(np.mean(d['liars'][3:])) if len(d['liars']) > 3 else float('nan'),
           'commit': d['commit'] / rounds if rounds else float('nan'),
           'bad': d['bad_commit'] / rounds if rounds else float('nan'),
           'migrated': float(np.mean(d['migrated'])) if d['migrated'] else 0.0,
           'rmse': float(np.mean([p.rmse_normal for p in perf[-(_W['ticks'] // 4):]])) * 1e9}
    main_all.HEAD_FAULT, main_all.HEAD_POLICY, main_all.LEDGER_SCOPE = 'majority', 'centroid', 'global'
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=blt_config.N_SATS)
    ap.add_argument('--seeds', type=int, default=4)
    ap.add_argument('--ticks', type=int, default=30 * ROUND, help='default 30 rounds = 180 s')
    ap.add_argument('--faulty', type=float, default=0.25)
    ap.add_argument('--updates', type=int, default=720, help='turnover: position updates (5 s each)')
    ap.add_argument('--turnover-only', action='store_true')
    ap.add_argument('--jobs', type=int, default=1)
    args = ap.parse_args()
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    blt_config.apply(main_all)
    print(blt_config.describe())

    print(f'\n== membership turnover: N={args.n}, {args.updates} position updates '
          f'({args.updates * 5 / 60:.0f} min of orbit)')
    rows = turnover(args.n, args.updates, BASE_SEED)
    with open(os.path.join(out_dir, 'cluster_migration_turnover.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for r in rows:
        if r['update'] % max(1, args.updates // 12) == 0:
            print(f"  {r['seconds'] / 60:>5.1f} min: {r['moved']:>4} moved this update "
                  f"({100 * r['moved_frac']:.2f}%), {100 * r['ever_moved_frac']:.1f}% "
                  f"have changed cluster at least once")
    per = float(np.mean([r['moved_frac'] for r in rows]))
    print(f'  mean {100 * per:.2f}% per 5 s update')
    if args.turnover_only:
        return 0

    import multiprocessing as mp
    print(f'\n== head selection: {100 * args.faulty:.0f}% degraded, {args.ticks // ROUND} rounds, '
          f'{args.seeds} seeds')
    jobs = [(label, policy, scope, r) for label, policy, scope in ARMS for r in range(args.seeds)]
    runs = []
    with mp.get_context('spawn').Pool(args.jobs, _init_worker,
                                      (args.n, args.ticks, args.faulty)) as pool:
        for row in pool.imap_unordered(one_run, jobs):
            runs.append(row)
            print(f"  [{len(runs)}/{len(jobs)}] {row['arm']:>26} seed {row['seed']}: "
                  f"bad heads {row['liars']:.2f}  commit {100 * row['commit']:.0f}%  "
                  f"RMSE {row['rmse']:.2f}", flush=True)
    with open(os.path.join(out_dir, 'cluster_migration_runs.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0])); w.writeheader()
        w.writerows(sorted(runs, key=lambda x: (x['arm'], x['seed'])))

    print(f"\n{'arm':>26} | {'bad heads':>9} {'commit':>7} {'wrong':>6} {'RMSE ns':>8} {'moved/upd':>9}")
    out = []
    for label, *_ in ARMS:
        sel = [x for x in runs if x['arm'] == label]
        m = {k: float(np.nanmean([x[k] for x in sel])) for k in
             ('liars', 'commit', 'bad', 'rmse', 'migrated')}
        sd = float(np.nanstd([x['liars'] for x in sel], ddof=1)) if len(sel) > 1 else 0.0
        print(f"{label:>26} | {m['liars']:>9.2f} {100 * m['commit']:>6.0f}% "
              f"{100 * m['bad']:>5.0f}% {m['rmse']:>8.2f} {m['migrated']:>9.1f}   "
              f"(bad heads sd {sd:.2f})", flush=True)
        out.append({'n': args.n, 'faulty_frac': args.faulty, 'arm': label, 'seeds': len(sel),
                    **m, 'liars_sd': sd})
    with open(os.path.join(out_dir, 'cluster_migration.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
