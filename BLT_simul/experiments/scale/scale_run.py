"""Does the fault tolerance hold at the constellation scale the paper claims?

N = 8,192 with k = 12 is not merely a bigger run: it is the configuration the
cadences are derived from, since 8192/12 = 683 members per cluster polled over
two ISL terminals is what sets the collection time and therefore the cycle.
This sweeps the constellation size so the behaviour at the design point can be
read against smaller ones rather than assumed to carry over.

It is affordable at full size: about 40 s per seed for all three schemes at
N = 8,192, because the per-tick loop is vectorised and the flood BFS
short-circuits on visited nodes.
At N = 500 a cluster holds 42 members and the same 2.7 s cadence is heavily
over-provisioned, which is the more favourable case for every algorithm. So this
is the run that tests the cadence against the collection load it was budgeted
for.

Fault fractions are whole multiples of 1/k, which is the budget for j whole
clusters. The number of heads that actually goes faulty is smaller and is
measured, not assumed: initialize_satellites consumes whole KMeans clusters
largest-first, and since real clusters are unequal a budget of j average-sized
clusters typically covers j-1 of them. The `heads` column reports what the run
produced. The 2f+1-of-3f+1 quorum tolerates f = 4 of 12 heads, and the sweep
runs to j = 6 so the measured head count crosses that bound.

Columns:
    frac         faulty member fraction (= j/k)
    heads        faulty cluster heads observed, out of k
    blt/ats/ftsp steady-state RMSE over healthy nodes [ns]
    commit       fraction of BLT global rounds that reached quorum
    bad          rounds where a degraded head's own proposal carried a quorum.
                 "a value committed" and "a correct value committed" are
                 different claims and only the second supports the result.

Run:  python experiments/scale/scale_run.py
      python experiments/scale/scale_run.py --sizes 500 --quick
      BLT_CONFIG=1 python experiments/scale/scale_run.py --sizes 8192 --clusters 4 --cluster-pick random --out part.csv

BLT_CONFIG=1 switches to the adopted configuration (model/blt_config.py), N = 8,192 by
default, result/runs/ output, and the run can be split with the filters below so
the pieces run as parallel processes and are merged afterwards.
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

import blt_core
import blt_params
import engine_profiles
import main_all
from fig_style import UNIT_SCALE, ISL_REQUIREMENT_NS

RESULT_DIR = os.environ.get('BLT_SAND_RESULT_DIR', './result')
os.makedirs(RESULT_DIR, exist_ok=True)

SIZES = (500, 8192)
K = 12
NUM_RUNS = 4
TIME_UNITS = 40000
STEADY_WINDOW = 12000
BASE_SEED = 20260912

# j faulty clusters out of k, j = 0..6. Steps through the f = 4 quorum bound.
FAULTY_CLUSTERS = (0, 1, 2, 3, 4, 5, 6)


def run_point(n, k, j, ticks, steady, runs, fixed_heads=None,
              cluster_pick='largest'):
    """One sweep point. `j` is the faulty-cluster budget.

    Comparing two constellation sizes needs `cluster_pick='random'`. With the
    default, initialize_satellites degrades whole clusters in size order and
    KMeans decides the sizes, so the degraded set is deterministic for a given N
    and different between two Ns, {1,6,8,11} measured at N=500 against
    {1,3,4,5} at N=8192. The proposer rotates as round_no % k over the 8 rounds
    that fit in a run, so those sets put a different number of unreliable heads
    in the proposer sequence and the commit rate moves for a reason unrelated to
    size. Seeds cannot average that out, because the placement does not depend
    on the seed.

    `fixed_heads` is a different fault model, not a fix for this. It names the
    unreliable heads directly, which severs the link between a head being
    unreliable and its own cluster having degraded: heads then misreport while
    their members are healthy, and fully degraded clusters keep honest heads
    that faithfully report a badly skewed reference. Both effects cost votes, so
    the quorum fails far earlier, and it models an adversary, which is not the
    threat this work addresses. Kept because the measurement is worth having,
    clearly labelled as the other model.
    """
    frac = j / k
    n_faulty = int(round(frac * n))
    out = {a: [] for a in ('bc', 'cluster', 'ftsp')}
    heads, commits, bad = [], [], []
    for r in range(runs):
        seed = BASE_SEED + r
        sats = main_all.initialize_satellites(
            n, n_faulty,
            malfunction_mean=blt_params.value('osc_nominal_hz'),
            malfunction_stddev=engine_profiles.FAULTY_STDDEV_HZ,
            malfunction_drift_bias=engine_profiles.FAULTY_DRIFT_BIAS,
            cluster_aligned=True, cluster_pick=cluster_pick, seed=seed)
        positions = np.array([s['position'] for s in sats], dtype=float)
        cil = main_all.cluster_indices_from_kmeans(positions, k)
        is_faulty = np.array([s.get('drift_bias', 0.0) != 0.0 for s in sats])
        if fixed_heads is None:
            faulty_head = None
            heads.append(int(blt_core.head_fault_mask(cil, is_faulty).sum()))
        else:
            faulty_head = blt_core.choose_faulty_heads(
                k, fixed_heads, np.random.default_rng(seed))
            heads.append(int(faulty_head.sum()))
        for name, fn in (('bc', main_all.simulate_bc),
                         ('cluster', main_all.simulate_cluster),
                         ('ftsp', main_all.simulate_ftsp)):
            if name == 'bc':
                main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[])
            kw = {'sim_seed': seed}
            if faulty_head is not None and name in ('bc', 'cluster'):
                kw['faulty_head'] = faulty_head
            perf = fn(sats, ticks, k, **kw)
            out[name].append(np.mean([d.rmse_normal for d in perf[-steady:]]))
            if name == 'bc':
                d = main_all.BC_DIAG
                rounds = d['commit'] + d['skip']
                commits.append(d['commit'] / rounds if rounds else float('nan'))
                bad.append(d['bad_commit'] / rounds if rounds else float('nan'))
    res = {a: float(np.mean(v)) * UNIT_SCALE for a, v in out.items()}
    res['heads'] = float(np.mean(heads))
    res['commit'] = float(np.mean(commits))
    res['bad'] = float(np.mean(bad))
    res['frac'] = frac
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', default=','.join(str(s) for s in SIZES))
    ap.add_argument('--k', type=int, default=K)
    ap.add_argument('--seeds', type=int, default=None,
                    help='override the seed count. Worth raising together with '
                         '--cluster-pick random, which is the option that makes '
                         'extra seeds average the fault geometry instead of '
                         'only the oscillator draw')
    ap.add_argument('--clusters', default=None,
                    help='comma-separated faulty-cluster budgets to run instead '
                         'of the whole sweep, e.g. 4,5,6')
    ap.add_argument('--heads', type=int, default=None,
                    help='DIFFERENT FAULT MODEL, not a placement control: names '
                         'the unreliable heads directly, so a head misreports '
                         'while its own members are healthy. That is the '
                         'adversarial case this work does not claim. For a '
                         'size comparison use --cluster-pick random')
    ap.add_argument('--cluster-pick', choices=('largest', 'random'),
                    default='largest', dest='cluster_pick',
                    help="which clusters degrade. 'largest' is deterministic "
                         "and is what the published sweep used; 'random' draws "
                         "the set per seed, which a comparison across "
                         "constellation sizes needs")
    ap.add_argument('--out', default='scale_run.csv')
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(',')]

    ticks = 8000 if args.quick else TIME_UNITS
    steady = 2500 if args.quick else STEADY_WINDOW
    runs = args.seeds or (2 if args.quick else NUM_RUNS)
    budgets = (tuple(int(x) for x in args.clusters.split(','))
               if args.clusters else FAULTY_CLUSTERS)
    k = args.k

    engine_profiles.apply(engine_profiles.FAULT_PROFILE, main_all)
    global RESULT_DIR
    import blt_config
    if blt_config.active():
        blt_config.apply(main_all)
        engine_profiles.FAULTY_STDDEV_HZ = blt_config.FAULTY_STDDEV_HZ
        engine_profiles.FAULTY_DRIFT_BIAS = blt_config.FAULTY_DRIFT_BIAS
        RESULT_DIR = os.environ.get('BLT_SAND_RESULT_DIR', './result/runs')
        os.makedirs(RESULT_DIR, exist_ok=True)
    # The engine commits when votes >= ceil(quorum * k), and an honest proposal
    # is backed only by the honest heads, so it carries while k - f >= needed.
    # Quoting "f of 3f+1" instead would say 3 here, which is not the rule the
    # code applies.
    needed = int(np.ceil(main_all.BC_QUORUM * k))
    print(f'scale run: k={k}, {ticks} ticks, {runs} seeds, quorum='
          f'{main_all.BC_QUORUM:.4f} -> needs {needed} of {k} votes, so an honest '
          f'proposal carries up to f={k - needed} faulty heads')
    print(f'cadences local={main_all.BC_LOCAL_CYCLE} global={main_all.BC_CLUSTER_CYCLE}')

    rows = []
    for n in sizes:
        print(f'\n=== N = {n}, {n // k} members per cluster ===')
        hdr = (f"{'faulty':>7} {'heads':>6} {'BLT':>8} {'ATS':>8} {'FTSP':>8}  "
               f"{'commit':>7} {'bad':>6}  {'ordering':>14} {'BLT vs 10ns':>12}")
        print(hdr)
        print('-' * len(hdr))
        for j in budgets:
            r = run_point(n, k, j, ticks, steady, runs, fixed_heads=args.heads,
                          cluster_pick=args.cluster_pick)
            order = ('BLT<ATS<FTSP' if r['bc'] < r['cluster'] < r['ftsp']
                     else 'BLT<FTSP<ATS' if r['bc'] < r['ftsp'] < r['cluster']
                     else 'not BLT-first' if min(r['bc'], r['cluster'], r['ftsp']) != r['bc']
                     else 'other')
            print(f"{100*r['frac']:>6.1f}% {r['heads']:>6.1f} {r['bc']:>8.2f} "
                  f"{r['cluster']:>8.2f} {r['ftsp']:>8.2f}  {100*r['commit']:>6.0f}% "
                  f"{100*r['bad']:>5.0f}%  {order:>14} "
                  f"{'over' if r['bc'] > ISL_REQUIREMENT_NS else 'PASS':>12}", flush=True)
            rows.append({'n': n, 'k': k, 'faulty_clusters': j,
                         'fault_pct': 100 * r['frac'], 'faulty_heads': r['heads'],
                         'blt_ns': r['bc'], 'ats_ns': r['cluster'],
                         'ftsp_ns': r['ftsp'], 'commit_rate': r['commit'],
                         'bad_commit_rate': r['bad'], 'ordering': order,
                         'ticks': ticks, 'seeds': runs})
            pd.DataFrame(rows).to_csv(
                os.path.join(RESULT_DIR, args.out), index=False)

    print('\nSaved ' + os.path.join(RESULT_DIR, args.out))
    print('Read the heads column, not the faulty percentage: the quorum holds at')
    print('4 faulty heads of 12 and cannot at 5. If the N = 8,192 rows track the')
    print('N = 500 rows, the published curve is not an artefact of running 16x')
    print('under the design size.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
