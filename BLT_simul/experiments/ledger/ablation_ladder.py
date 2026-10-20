"""One condition, one component removed per row.

The contribution of the blockchain layer has to be isolated from the hierarchy,
the filter and the cadence. experiments/ledger/ablation.py removes
stages one at a time and reports them as sweeps; this measures the whole ladder
at a single operating point, so the rows can be read as one table:

  BLT-SAND (published)   hierarchy + vote + the ledger record used to choose
                         the heads. The manuscript already says so: "reliability
                         information stored in previous blocks assists
                         participant selection and continuity across topology
                         changes" (SS III.B). The engine's HEAD_POLICY default of
                         'centroid' is a simulator simplification, not the design.
  - ledger               same, but heads are chosen by position alone
  - vote                 same, but the proposal is distributed unverified
  - global consensus     ATS: heads average, nothing verifies
  - hierarchy            FTSP: one flood from a root

The ladder therefore REMOVES one component per row, and the published system is
the top row. Reading it the other way round would say the paper shipped the
wrong design, which is not what is being measured: every arm runs the same
engine, clusters, cycles, head network, correction strength and fault draw.

Reported per arm: RMSE of the satellites that never degrade, commit rate, wrong
commits, and degraded heads per round. Read down the columns rather than across:
the hierarchy moves RMSE, the vote moves wrong commits, the ledger moves the
head quality and with it the commit rate. No single column shows all three,
which is the answer to "isolate the contribution".

Three conditions, because each component answers a different fault:

  5%           the headline point: the headline draw (cluster_aligned, random cluster
               order) under the union head rule, HEAD_FAULT 'both', a head misreports
               when its OWN oscillator is degraded, even if its cluster is otherwise
               healthy. ATS and FTSP are unchanged by that choice (14.45 / 18.38, the
               manuscript's numbers), while it leaves the ledger something to act on:
               a head is degraded in about 5% of draws. Under the published 'majority'
               rule a 5% budget cannot fill a ~683-satellite cluster, so no head
               misreports at all and the three top rows would be exactly identical.
  25% regional a spatial patch of degradation that ignores cluster borders, so several
               heads misreport at once, which is what a vote is for. The patch is the
               geometry the fault model argues for and the one panel 12b uses.
  25% own      scattered degradation, where the union rule reduces to 'own', a head misreports because
               its own oscillator degraded while its cluster is otherwise healthy. This
               is where the record earns its place: it keeps that satellite out of the
               role. The vote matters less, since the liars are a small minority.

So the division of labour is: hierarchy sets the accuracy, the vote covers a degraded
REGION, the ledger covers a degraded INDIVIDUAL. The adopted configuration otherwise, with the failed-round
fallback on for every BLT arm: a rejected round reconciles toward the median of
the reports instead of skipping the global step. Without it the arms that vote lose the
correction in precisely the rounds they rejected, so dropping the vote would read as an
accuracy improvement, an artefact of the model rather than a property of the
design. With the fallback on, the comparison is fair.

The three conditions run together because the comparison only means something
across them: a placement that spares every head makes the vote look idle, and
one that takes whole clusters makes the ledger look powerless.

Output: result/runs/ablation_ladder.csv (+ _runs.csv per seed)

Run:  python experiments/ledger/ablation_ladder.py --seeds 4 --jobs 10
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

import blt_core
import blt_params
import main_all
import blt_config

K = 12
BASE_SEED = 20260918

# (label, hierarchy, vote, ledger used for head selection). Ordered as removals
# from the published system, so row 1 is BLT-SAND as the paper describes it.
ARMS = [('BLT-SAND (published)', True, True, True),
        ('no ledger record', True, True, False),
        ('no vote', True, False, True),
        ('no global consensus (ATS)', True, False, False),
        ('no hierarchy (FTSP)', False, False, False)]


# (label, degraded fraction, placement, head-fault rule)
# Labelled by the KIND of fault, not by the amount: the columns are not a severity
# ladder, and reading them as one invites the wrong question (ATS does better under
# 25% scattered degradation than under the 5% headline draw, because what hurts a plain
# cluster mean is concentration, not count).
# One head-fault rule across every condition and every figure: a head misreports
# when its OWN oscillator is degraded or when its cluster is mostly degraded. The
# two halves answer different placements, scattered degradation reaching a head
# through its own part and regional degradation through its cluster, and applying
# only one of them would make a placement look harmless on the head axis while the
# same faults showed up on the member axis.
# Placements, named as panel 12b names them, so the two are read together.
# 'regional' is a spatial patch that ignores cluster borders, which is what the
# fault model argues for: an eclipse cycle or a radiation belt does not stop at a
# partition boundary.
PLACEMENTS = {'aligned': dict(cluster_aligned=True, cluster_pick='random'),
              'scattered': dict(),
              'regional': dict(concentrate_faults=True)}
CONDITIONS = [('headline draw (5%)', 0.05, 'aligned', 'both'),
              ('a degraded region (25%, regional)', 0.25, 'regional', 'both'),
              ('degraded individuals (25%, scattered)', 0.25, 'scattered', 'both')]


def degraded(n, frac, seed, placement):
    """placement: one of PLACEMENTS, the headline draw fills whole clusters in a
    random order ('aligned'), 'scattered' spreads the faults uniformly as on the member
    axis, and 'regional' puts them in one spatial neighbourhood regardless of borders."""
    return main_all.initialize_satellites(
        n, int(round(frac * n)),
        malfunction_mean=blt_params.value('osc_nominal_hz'),
        malfunction_stddev=blt_config.FAULTY_STDDEV_HZ,
        malfunction_drift_bias=blt_config.FAULTY_DRIFT_BIAS,
        seed=seed, **PLACEMENTS[placement])


def simulate_blt_arm(satellites, ticks, k, vote, ledger, sim_seed=None):
    """BLT with the vote and the ledger-based head selection made selectable.
    A trimmed copy of main_all.simulate_bc; every stage is the engine's own code
    so the arms differ only in the two flags."""
    m = main_all
    positions, velocities, ang_vels, drifts, frequencies, clocks = m._extract_arrays(satellites)
    normal_mask = ~blt_core.fault_mask(satellites)
    cluster_idx_list = m.cluster_indices_from_kmeans(positions, k)
    drift_step = blt_core.clock_error_step(drifts)
    skew_rate = drifts - 1.0
    is_faulty = ~normal_mask

    m.HEAD_POLICY = 'history' if ledger else 'centroid'
    # A round that misses the quorum still reconciles toward the median of the
    # reports. Without it the voting arms skip the global step in exactly the rounds
    # the vote rejected, so removing the vote would *improve* RMSE, an artefact of
    # the model, not a property of consensus.
    m.FAILED_ROUND_FALLBACK = True
    links = m._link_model(len(clocks), sim_seed) if m.ISL_LINK_MODEL else None
    if links is not None:
        links.update(positions, cluster_idx_list, 0.0)
    noise_rng = (np.random.default_rng((sim_seed or 0) + 4241)
                 if m.LOCAL_MEASUREMENT_NOISE else None)
    m._measurement_setup(len(clocks), sim_seed)
    m._LEDGER['score'] = np.zeros(len(clocks)) if ledger else None
    collect_rng = np.random.default_rng((sim_seed or 0) + 9973)

    perf = []
    pos_t = 0
    for i in range(ticks):
        clocks += drift_step
        perf.append(m.measure_sync_performance_vec(clocks, normal_mask))
        if i % m.BC_LOCAL_CYCLE == 0:
            m.sync_local_robust(clocks, cluster_idx_list, drift_step=drift_step, rng=collect_rng,
                                reach=links.local_reach() if links is not None else None,
                                noise_rng=noise_rng, hops=m._member_hops(links, len(clocks)))
        if i % m.BC_CLUSTER_CYCLE == 0:
            round_no = i // m.BC_CLUSTER_CYCLE
            m.sync_with_cluster_bc_vec(
                clocks, cluster_idx_list, positions, skew_rate, is_faulty,
                round_no=round_no, require_quorum=vote,
                head_reach=links.head_reach(round_no % len(cluster_idx_list))
                if links is not None else None)
        pos_t += 1
        if pos_t >= m.POSITION_UPDATE_CYCLE:
            positions = m.update_positions_vec(positions, velocities, ang_vels,
                                               m.POSITION_UPDATE_CYCLE)
            pos_t = 0
            cluster_idx_list = m.recluster(positions, k, cluster_idx_list)
            if links is not None:
                links.update(positions, cluster_idx_list, (i + 1) * m.TIME_TICK)
    return perf


_W = {}


def _init_worker(n, ticks):
    _W.update(n=n, ticks=ticks)
    blt_config.apply(main_all)


def one_run(job):
    label, hier, vote, ledger, cond, r = job
    cond_label, frac, placement, head_rule = cond
    seed = BASE_SEED + r
    sats = degraded(_W['n'], frac, seed, placement)
    main_all.HEAD_FAULT = head_rule
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[], migrated=[],
                            ref_err=[])
    if 'FTSP' in label:
        perf = main_all.simulate_ftsp(sats, _W['ticks'], K, sim_seed=seed)
    elif 'ATS' in label:
        perf = main_all.simulate_cluster(sats, _W['ticks'], K, sim_seed=seed)
    else:
        perf = simulate_blt_arm(sats, _W['ticks'], K, vote, ledger, sim_seed=seed)
    d = main_all.BC_DIAG
    rounds = d['commit'] + d['skip']
    blt = 'ATS' not in label and 'FTSP' not in label
    row = {'arm': label, 'seed': seed, 'condition': cond_label, 'faulty_frac': frac,
           'hierarchy': hier, 'vote': vote, 'ledger': ledger,
           'rmse': float(np.mean([p.rmse_normal for p in perf[-(_W['ticks'] // 4):]])) * 1e9,
           # the same satellites against true time: a genuine RMSE that does NOT cancel a
           # shift every cluster took together, which is what a wrong commit is
           'rmse_true': float(np.mean([p.rmse_absolute for p in perf[-(_W['ticks'] // 4):]])) * 1e9,
           # the reference the network adopted, against the honest cluster references
           'ref_err': (float(np.mean(d['ref_err'])) * 1e9 if d.get('ref_err') else float('nan'))
                      if blt else float('nan'),
           'commit': (d['commit'] / rounds if rounds else float('nan')) if blt else float('nan'),
           'bad': (d['bad_commit'] / rounds if rounds else float('nan')) if blt else float('nan'),
           # the first rounds carry no record under any arm, so they are dropped
           'liars': (float(np.mean(d['liars'][3:])) if len(d['liars']) > 3 else float('nan'))
                    if blt else float('nan')}
    main_all.HEAD_FAULT, main_all.HEAD_POLICY = 'majority', 'centroid'
    main_all.FAILED_ROUND_FALLBACK = False
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=blt_config.N_SATS)
    ap.add_argument('--seeds', type=int, default=4)
    ap.add_argument('--ticks', type=int, default=40000)
    ap.add_argument('--head-rule', default='', choices=('', 'own', 'majority', 'both'),
                    help="override every condition's head-fault rule (use 'both' for the "
                         'union rule: a head misreports when its own oscillator is degraded '
                         'OR its cluster is mostly degraded)')
    ap.add_argument('--tag', default='', help='suffix for the output files, e.g. _both')
    ap.add_argument('--conditions', default='all',
                    help="'all' or a comma-separated subset of condition indices, e.g. '0,2'")
    ap.add_argument('--jobs', type=int, default=1)
    args = ap.parse_args()
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    blt_config.apply(main_all)
    print(blt_config.describe())
    conds = (CONDITIONS if args.conditions == 'all'
             else [CONDITIONS[int(i)] for i in args.conditions.split(',')])
    if args.head_rule:
        conds = [(lbl, fr, al, args.head_rule) for lbl, fr, al, _ in conds]
    print(f'\n== ladder over {len(conds)} conditions, N={args.n}, {args.seeds} seeds')

    import multiprocessing as mp
    jobs = [(label, h, v, l, c, r) for c in conds for label, h, v, l in ARMS
            for r in range(args.seeds)]
    runs = []
    with mp.get_context('spawn').Pool(args.jobs, _init_worker, (args.n, args.ticks)) as pool:
        for row in pool.imap_unordered(one_run, jobs):
            runs.append(row)
            print(f"  [{len(runs)}/{len(jobs)}] {row['condition']:>30} "
                  f"{row['arm']:>26} seed {row['seed']}: RMSE {row['rmse']:.2f}  "
                  f"commit {row['commit']:.2f}  wrong {row['bad']:.2f}  "
                  f"bad heads {row['liars']:.2f}", flush=True)
    with open(os.path.join(out_dir, f'ablation_ladder_runs{args.tag}.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0])); w.writeheader()
        w.writerows(sorted(runs, key=lambda x: (x['arm'], x['seed'])))

    out = []
    for cond_label, frac, placement, head_rule in conds:
        print(f"\n{cond_label}  {'arm':>26} {'hier':>5} {'vote':>5} {'ledg':>5} | "
              f"{'RMSE ns':>8} {'RMSE true':>10} {'ref err':>10} {'commit':>7} {'wrong':>6} {'bad heads':>9}")
        for label, h, v, l in ARMS:
            sel = [x for x in runs if x['arm'] == label and x['condition'] == cond_label]
            m = {k: float(np.nanmean([x[k] for x in sel])) if
                 not all(np.isnan(x[k]) for x in sel) else float('nan')
                 for k in ('rmse', 'rmse_true', 'ref_err', 'commit', 'bad', 'liars')}
            sd = float(np.nanstd([x['rmse'] for x in sel], ddof=1)) if len(sel) > 1 else 0.0
            f_ = lambda x, pct=False: '-' if np.isnan(x) else (f'{100 * x:.0f}%' if pct else f'{x:.2f}')
            print(f"{'':>12}  {label:>26} {str(h):>5} {str(v):>5} {str(l):>5} | {m['rmse']:>8.2f} "
                  f"{f_(m['rmse_true']):>10} {f_(m['ref_err']):>10} {f_(m['commit'], True):>7} {f_(m['bad'], True):>6} "
                  f"{f_(m['liars']):>9}", flush=True)
            out.append({'n': args.n, 'condition': cond_label, 'faulty_frac': frac,
                        'head_rule': head_rule, 'arm': label, 'seeds': len(sel),
                        'hierarchy': h, 'vote': v, 'ledger': l, **m, 'rmse_sd': sd})
    with open(os.path.join(out_dir, f'ablation_ladder{args.tag}.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print(f'wrote {out_dir}/ablation_ladder.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
