"""Regionally correlated degradation looks like collusion, and a vote is what stops it.

Two questions meet here: what evidence stands behind the fault model, and what
the same hierarchy does without consensus. Both come down to one thing --
what happens when degraded satellites are not independent?

The faults in BLT-SAND are benign (an oscillator degrades, its satellite keeps
reporting what it believes). Radiation is regional, though: satellites crossing
the South Atlantic Anomaly degrade together, and a cluster is
a region. So a regional fault turns several cluster heads wrong at the same time
and in the same direction. Nobody colludes; correlated benign
degradation merely produces what collusion would look like to a vote.

Part 1  placement   the same share of degraded satellites (20%, 30%) placed
                    scattered  uniformly at random
                    regional   one spatial neighbourhood, ignoring cluster borders
                    clustered  whole clusters (the manuscript's placement)
                    arms: BLT-SAND, the same hierarchy without the vote, ATS, FTSP
Part 2  correlation 2 / 4 / 6 of 12 clusters degraded; their heads' misreports
                    either share one cause and point the same way (correlated,
                    rho = 1) or each its own way (independent, rho = 0).
                    Arms: BLT-SAND, no vote.

Per run: healthy-satellite relative RMSE and absolute error, commit and wrong-
commit rates, the mean number of heads reporting wrongly per round ("wrong
heads"), and per-round vote records for the cross-cluster check table
(proposer wrong?, votes, committed?).

Warm-started clusters, as adopted. Output in result/runs/:
    correlated_faults_runs.csv     one row per run
    correlated_faults_rounds.csv   one row per global round of the BLT and no-vote arms

Run:  python experiments/faults/correlated_faults.py --seeds 4 --jobs 16
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

K = 12
BASE_SEED = 20260930
# How many members near the cluster centroid the ledger chooses the head from is an engine
# constant (main_all.HEAD_CANDIDATES = 10) that the manuscript does not state, and it is
# what decides how often the ledger fails to find a healthy head under scattered faults.
# --head-candidates sweeps it so the figure can say how much of its shape comes from there.
PLACEMENTS = {'scattered': dict(), 'regional': dict(concentrate_faults=True),
              'clustered': dict(cluster_aligned=True, cluster_pick='random')}
FRACTIONS = (0.20, 0.30)
HEADS = (2, 4, 6)
RHOS = (1.0, 0.0)


def _reset(main_all):
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[], rounds=[],
                            honest_spread=[], ref_err=[])


def _metrics(main_all, perf, ticks):
    steady = perf[-ticks // 4:]
    d = main_all.BC_DIAG
    # The first global round happens before any satellite has a ledger record, so the
    # heads are chosen without one: at 40% scattered that can put 8 of 12 degraded heads
    # in the room, which is past the 2/3 bound and a lie commits exactly as the protocol
    # says it would. The record exists from the next round on (1.75 degraded heads there).
    # Counting that first round would report a property of the cold start, not of the
    # consensus, so it is dropped here as it is on the head axis and in the ladder
    # (as in ablation_ladder's liars[3:]).
    rec = d.get('rounds', [])
    if rec:
        rec = rec[1:]
        committed = sum(1 for r in rec if r[3])
        bad = sum(1 for r in rec if r[0] and r[3])
        n_rounds = len(rec)
        d = dict(d, commit=committed, skip=n_rounds - committed, bad_commit=bad,
                 liars=[r[2] for r in rec],
                 ref_err=d.get('ref_err', [])[1:])
    rounds = d['commit'] + d['skip']
    return {'rel_ns': float(np.mean([x.rmse_normal for x in steady])) * 1e9,
            'abs_ns': float(np.mean([x.rmse_absolute for x in steady])) * 1e9,
            'commit': d['commit'] / rounds if rounds else np.nan,
            'wrong_commit': d['bad_commit'] / rounds if rounds else np.nan,
            'wrong_heads': float(np.mean(d['liars'])) if d.get('liars') else np.nan,
            # |adopted global value - mean of the honest clusters' own references|: how
            # wrong the reference the network agreed on is, measured against the healthy
            # part of the network itself (not against true time)
            'ref_err_ns': (float(np.mean(d['ref_err'])) * 1e9 if d.get('ref_err') else np.nan)}


def job(spec):
    import main_all
    import blt_config
    import ablation
    import fault_axes
    blt_config.apply(main_all)   # after ablation's import-time profile
    # one head-fault rule throughout (see ablation_ladder.CONDITIONS), and the
    # failed-round fallback so a refused round still reconciles toward the median, without it the
    # voting arm loses the global step in exactly the rounds the vote rejected
    main_all.HEAD_FAULT = 'both'
    main_all.FAILED_ROUND_FALLBACK = True
    # the published design chooses heads from the ledger record (manuscript III.B, and the
    # ladder's published arm): a cluster with healthy members gets a healthy head, and only
    # a cluster that is degraded through and through has none to offer. So "the head of a
    # degraded cluster misreports" comes out as a result instead of being assumed.
    main_all.HEAD_POLICY = 'history'
    part, case, level, seed, n, ticks, only, cand = spec
    if cand:
        main_all.HEAD_CANDIDATES = cand
    if part == 'placement':
        sats = main_all.initialize_satellites(
            n, int(round(level * n)), malfunction_mean=main_all.blt_params.value('osc_nominal_hz'),
            malfunction_stddev=blt_config.FAULTY_STDDEV_HZ, malfunction_drift_bias=blt_config.FAULTY_DRIFT_BIAS,
            seed=seed, **PLACEMENTS[case])
        arms = (('BLT-SAND', 'bc'), ('no vote', 'novote'), ('ATS', 'cluster'), ('FTSP', 'ftsp'))
        if only:
            arms = tuple(a for a in arms if a[1] in only)
        main_all.FAULT_CORRELATION = None
    else:
        sats = fault_axes.degraded_clusters(n, level, seed)
        arms = (('BLT-SAND', 'bc'), ('no vote', 'novote'))
        main_all.FAULT_CORRELATION = None if case == 1.0 else case
    rows, rounds = [], []
    for label, arm in arms:
        _reset(main_all)
        if arm == 'bc':
            perf = main_all.simulate_bc(sats, ticks, K, sim_seed=seed)
        elif arm == 'novote':
            perf = ablation.simulate_arm(sats, ticks, K, 'robust', 'direct', sim_seed=seed)
        elif arm == 'cluster':
            perf = main_all.simulate_cluster(sats, ticks, K, sim_seed=seed)
        else:
            perf = main_all.simulate_ftsp(sats, ticks, K, sim_seed=seed)
        m = _metrics(main_all, perf, ticks)
        if arm not in ('bc', 'novote'):
            m.update(commit=np.nan, wrong_commit=np.nan, wrong_heads=np.nan)
        base = {'part': part, 'case': case, 'level': level, 'seed': seed, 'arm': label}
        rows.append({**base, **m})
        if arm in ('bc', 'novote'):
            # the reference error of THAT round, so a figure can pool rounds instead of
            # averaging each run first: a wrong proposal is rare and discrete, and a
            # per-run average turns it into steps of (lie / rounds per run)
            re_ = main_all.BC_DIAG.get('ref_err', [])
            recs = main_all.BC_DIAG.get('rounds', [])
            for r, (wrong_prop, votes, wrong, committed) in enumerate(recs):
                rounds.append({**base, 'round': r, 'proposer_wrong': int(wrong_prop), 'votes': votes,
                               'wrong_heads': wrong, 'committed': int(committed),
                               'ref_err_ns': (float(re_[r]) * 1e9 if len(re_) == len(recs)
                                              else float('nan'))})
    main_all.FAULT_CORRELATION = None
    return rows, rounds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8192)
    ap.add_argument('--seeds', type=int, default=4)
    ap.add_argument('--ticks', type=int, default=40000)
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--parts', default='placement,correlation')
    ap.add_argument('--fractions', default=','.join(str(f) for f in FRACTIONS),
                    help='degraded shares for the placement part (default 0.2,0.3)')
    ap.add_argument('--arms', default='', help='limit the placement arms, e.g. bc,novote')
    ap.add_argument('--placements', default=','.join(PLACEMENTS),
                    help='limit the placement part, e.g. scattered. Scattered needs more '
                         'seeds than the concentrated placements: there the wrong-head count '
                         'is all but fixed within a run, while here a wrong proposal is a rare '
                         'event and the mean over rounds is its rate')
    ap.add_argument('--tag', default='', help='suffix for the output files, e.g. _sweep')
    ap.add_argument('--head-candidates', type=int, default=0,
                    help='members near the centroid the ledger picks the head from '
                         '(0 keeps the engine default of 10; a large number means the '
                         'whole cluster)')
    args = ap.parse_args()
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    parts = args.parts.split(',')
    fractions = tuple(float(x) for x in args.fractions.split(','))
    only = tuple(a for a in args.arms.split(',') if a)
    places = [p for p in PLACEMENTS if p in args.placements.split(',')]
    specs = []
    for r in range(args.seeds):
        seed = BASE_SEED + r
        if 'placement' in parts:
            specs += [('placement', p, f, seed, args.n, args.ticks, only, args.head_candidates)
                      for p in places for f in fractions]
        if 'correlation' in parts:
            specs += [('correlation', rho, h, seed, args.n, args.ticks, (), args.head_candidates)
                      for rho in RHOS for h in HEADS]
    print(f'correlated faults: N={args.n}, {args.seeds} seeds, {len(specs)} jobs', flush=True)
    runs, rounds = [], []

    def write():
        for name, data in ((f'correlated_faults_runs{args.tag}.csv', runs),
                           (f'correlated_faults_rounds{args.tag}.csv', rounds)):
            if data:
                with open(os.path.join(out_dir, name), 'w', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=list(data[0]))
                    w.writeheader()
                    w.writerows(data)

    def report(k, rw):
        for x in rw:
            print(f"  [{k}/{len(specs)}] {x['part']} {x['case']} {x['level']} seed {x['seed']} {x['arm']}: "
                  f"rel {x['rel_ns']:.2f} abs {x['abs_ns']:.1f} commit {x['commit']:.2f} "
                  f"wrong {x['wrong_commit']:.2f} wrong heads {x['wrong_heads']:.2f}", flush=True)

    if args.jobs > 1:
        import multiprocessing as mp
        with mp.get_context('spawn').Pool(args.jobs) as pool:
            for k, (rw, rd) in enumerate(pool.imap_unordered(job, specs), 1):
                runs += rw
                rounds += rd
                report(k, rw)
                write()
    else:
        for k, spec in enumerate(specs, 1):
            rw, rd = job(spec)
            runs += rw
            rounds += rd
            report(k, rw)
            write()
    print(f'wrote {out_dir}/correlated_faults_runs.csv and correlated_faults_rounds.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
