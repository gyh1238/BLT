"""Member faults and cluster-head faults, measured on separate axes.

A head misreports when its own cluster has degraded, so raising the member
fault ratio moves both axes at once and the quorum bound, which is defined
over the twelve heads, ends up read against a denominator of all satellites.
The two are driven separately here.

  member axis   faults scattered at random over all satellites, 0-50%. At these
                ratios no cluster has a faulty majority, so every head reports
                honestly: what is tested is the local filter alone.
  head axis     0..HEADS_MAX of the 12 clusters degrade as a whole, so their heads
                misreport because their own cluster degraded, the regional,
                correlated fault the paper argues for. 33% = 4 heads; the vote
                needs 8 of 12. No other satellite is faulty.

The head axis degrades whole clusters rather than labelling heads faulty while
their members stay healthy. A head alone carries no error into the relative
RMSE: past the bound BLT-SAND simply stops committing, and with healthy members
the clusters do not drift apart inside 40 s, so the axis would move nothing.
What a degraded cluster changes is both the head's report and its members'
clocks, which is the case the quorum exists for.

Reported: healthy-satellite RMSE (BLT, ATS, FTSP), BLT commit rate and wrong commits.

On the head axis WHICH clusters degrade matters (their size, and where they sit on
the flood paths), so each seed can draw several cluster combinations (--combos).
Within one combination the sets are nested: j+1 clusters are the j clusters plus one.
Every (seed, combination, heads) run is written to fault_axes_head_runs.csv, and
fault_axes_head.csv holds the mean with the min, max and standard deviation.

--fallback makes a round that misses the quorum reconcile toward the median of
the reported values instead of skipping the global step entirely
(main_all.FAILED_ROUND_FALLBACK). Nothing is written to the ledger either way.
That median is the correction the same hierarchy would make with no consensus
at all, so past the bound the axis measures what the vote adds rather than what
losing the global step costs. It writes fault_axes_*_fallback.csv.

Run:  python experiments/faults/fault_axes.py --seeds 8 --jobs 16        # member axis
      python experiments/faults/fault_axes.py --axis head --seeds 8 --combos 4 --jobs 16
      python experiments/faults/fault_axes.py --axis head --seeds 8 --combos 4 --jobs 16 --fallback
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

import blt_core
import blt_params
import main_all
import blt_config

K = 12
BASE_SEED = 20260915
MEMBER_FRACTIONS = (0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50)
HEADS_MAX = 6


def satellites(n, frac, seed, aligned=False):
    return main_all.initialize_satellites(
        n, int(round(frac * n)),
        malfunction_mean=blt_params.value('osc_nominal_hz'),
        malfunction_stddev=blt_config.FAULTY_STDDEV_HZ,
        malfunction_drift_bias=blt_config.FAULTY_DRIFT_BIAS,
        cluster_aligned=aligned, cluster_pick='random', seed=seed)


def degraded_clusters(n, j, seed, combo=0):
    """Satellites with exactly j whole KMeans clusters degraded, chosen at random.
    combo selects another random order of the clusters (combo 0 = the original draw)."""
    sats = main_all.initialize_satellites(n, 0, seed=seed)
    pos = np.array([s['position'] for s in sats], dtype=float)
    clusters = main_all.cluster_indices_from_kmeans(pos, K)
    rng = np.random.default_rng(seed + 1000 + 100 * combo)
    mean = blt_params.value('osc_nominal_hz')
    for c in rng.permutation(K)[:j]:
        for i in clusters[c]:
            f = rng.normal(mean, blt_config.FAULTY_STDDEV_HZ)
            sats[i].update(oscillator_mean=mean, oscillator_stddev=blt_config.FAULTY_STDDEV_HZ,
                           frequency=f, drift=(f / mean,), drift_bias=blt_config.FAULTY_DRIFT_BIAS)
    return sats


def run(fn, sats, ticks, seed, **kw):
    main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[], liars=[])
    perf = fn(sats, ticks, K, sim_seed=seed, **kw)
    rmse = float(np.mean([d.rmse_normal for d in perf[-ticks // 4:]])) * 1e9
    d = main_all.BC_DIAG
    rounds = d['commit'] + d['skip']
    return rmse, (d['commit'] / rounds if rounds else np.nan), (d['bad_commit'] / rounds if rounds else np.nan)


_WORKER_N = _WORKER_TICKS = None


def _init_worker(n, ticks, fallback=False):
    global _WORKER_N, _WORKER_TICKS
    _WORKER_N, _WORKER_TICKS = n, ticks
    blt_config.apply(main_all)
    main_all.FAILED_ROUND_FALLBACK = fallback


def member_job(job):
    """One member-axis run: (seed index, faulty fraction) -> row."""
    r, frac = job
    seed = BASE_SEED + r
    sats = satellites(_WORKER_N, frac, seed)
    row = {'seed': seed, 'faulty_frac': frac}
    row['bc'], row['commit'], row['bad'] = run(main_all.simulate_bc, sats, _WORKER_TICKS, seed)
    row['cluster'] = run(main_all.simulate_cluster, sats, _WORKER_TICKS, seed)[0]
    row['ftsp'] = run(main_all.simulate_ftsp, sats, _WORKER_TICKS, seed)[0]
    return row


def head_job(job):
    """One head-axis run: (seed index, combination, degraded clusters) -> row."""
    r, combo, h = job
    seed = BASE_SEED + r
    sats = degraded_clusters(_WORKER_N, h, seed, combo)
    row = {'seed': seed, 'combo': combo, 'faulty_heads': h,
           'faulty_sats': float(np.mean(blt_core.fault_mask(sats)))}
    row['bc'], row['commit'], row['bad'] = run(main_all.simulate_bc, sats, _WORKER_TICKS, seed)
    row['cluster'] = run(main_all.simulate_cluster, sats, _WORKER_TICKS, seed)[0]
    row['ftsp'] = run(main_all.simulate_ftsp, sats, _WORKER_TICKS, seed)[0]
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--axis', choices=('member', 'head', 'both'), default='both')
    ap.add_argument('--n', type=int, default=blt_config.N_SATS)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--ticks', type=int, default=40000)
    ap.add_argument('--combos', type=int, default=1, help='cluster combinations per seed (head axis)')
    ap.add_argument('--jobs', type=int, default=1, help='parallel processes')
    ap.add_argument('--fallback', action='store_true',
                    help='a round that fails to reach quorum falls back to the unverified '
                         'head median (main_all.FAILED_ROUND_FALLBACK); writes *_fallback.csv')
    args = ap.parse_args()
    out_dir = os.environ.get('BLT_SAND_RESULT_DIR', 'result/runs')
    os.makedirs(out_dir, exist_ok=True)
    import multiprocessing as mp
    tag = '_fallback' if args.fallback else ''
    blt_config.apply(main_all)
    main_all.FAILED_ROUND_FALLBACK = args.fallback
    print(blt_config.describe())
    print(f'N={args.n}, {args.seeds} seeds, {args.ticks} ticks'
          + (', failed rounds fall back to the unverified head median' if args.fallback else ''))

    if args.axis in ('member', 'both'):
        print('\n== member axis: faults scattered over all satellites, heads honest')
        jobs = [(r, frac) for frac in MEMBER_FRACTIONS for r in range(args.seeds)]
        runs = []
        with mp.get_context('spawn').Pool(args.jobs, _init_worker,
                                          (args.n, args.ticks, args.fallback)) as pool:
            for row in pool.imap_unordered(member_job, jobs):
                runs.append(row)
                print(f"  seed {row['seed']} faulty {100 * row['faulty_frac']:.0f}%: "
                      f"BLT {row['bc']:.2f} ATS {row['cluster']:.2f} FTSP {row['ftsp']:.2f} "
                      f"[{len(runs)}/{len(jobs)}]", flush=True)
                runs.sort(key=lambda x: (x['faulty_frac'], x['seed']))
                with open(os.path.join(out_dir, f'fault_axes_member_runs{tag}.csv'), 'w', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=list(runs[0])); w.writeheader(); w.writerows(runs)

        print(f"\n{'faulty':>7} | {'BLT':>6} {'ATS':>6} {'FTSP':>6} | {'commit':>6} {'wrong':>5}")
        rows = []
        for frac in MEMBER_FRACTIONS:
            sel = [r for r in runs if r['faulty_frac'] == frac]
            m = {k: float(np.nanmean([r[k] for r in sel]))
                 for k in ('bc', 'cluster', 'ftsp', 'commit', 'bad')}
            sd = {f'{k}_sd': float(np.nanstd([r[k] for r in sel])) for k in ('bc', 'cluster', 'ftsp')}
            print(f"{100 * frac:>6.0f}% | {m['bc']:>6.2f} {m['cluster']:>6.2f} {m['ftsp']:>6.2f} | "
                  f"{100 * m['commit']:>5.0f}% {100 * m['bad']:>4.0f}%", flush=True)
            rows.append({'axis': 'member', 'faulty_frac': frac, 'runs': len(sel), **m, **sd})
        with open(os.path.join(out_dir, f'fault_axes_member{tag}.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    if args.axis in ('head', 'both'):
        print(f'\n== head axis: whole clusters degraded (quorum 8 of 12), '
              f'{args.seeds} seeds x {args.combos} combinations')
        # 0 degraded clusters is the same run for every combination.
        jobs = [(r, c, h) for h in range(0, HEADS_MAX + 1) for r in range(args.seeds)
                for c in (range(args.combos) if h else (0,))]
        runs = []
        runs_path = os.path.join(out_dir, f'fault_axes_head_runs{tag}.csv')
        with mp.get_context('spawn').Pool(args.jobs, _init_worker,
                                          (args.n, args.ticks, args.fallback)) as pool:
            for row in pool.imap_unordered(head_job, jobs):
                runs.append(row)
                print(f"  seed {row['seed']} combo {row['combo']} heads {row['faulty_heads']}: "
                      f"BLT {row['bc']:.2f} ATS {row['cluster']:.2f} FTSP {row['ftsp']:.2f} "
                      f"commit {100 * row['commit']:.0f}%  [{len(runs)}/{len(jobs)}]", flush=True)
                runs.sort(key=lambda x: (x['faulty_heads'], x['seed'], x['combo']))
                with open(runs_path, 'w', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=list(runs[0])); w.writeheader(); w.writerows(runs)

        print(f"\n{'heads':>5} {'sats':>6} | {'BLT':>6} {'ATS':>6} {'FTSP':>6} | "
              f"{'ATS min-max':>12} {'FTSP min-max':>12} | {'commit':>6} {'wrong':>5}")
        rows = []
        for h in range(0, HEADS_MAX + 1):
            g = [x for x in runs if x['faulty_heads'] == h]
            m = {'axis': 'head', 'faulty_heads': h, 'runs': len(g)}
            for k in ('bc', 'cluster', 'ftsp', 'commit', 'bad', 'faulty_sats'):
                v = np.array([x[k] for x in g], dtype=float)
                m[k] = float(np.nanmean(v))
                if k in ('bc', 'cluster', 'ftsp'):
                    m[k + '_min'], m[k + '_max'] = float(np.nanmin(v)), float(np.nanmax(v))
                    m[k + '_sd'] = float(np.nanstd(v, ddof=1)) if len(v) > 1 else 0.0
            print(f"{h:>5} {100 * m['faulty_sats']:>5.0f}% | {m['bc']:>6.2f} {m['cluster']:>6.2f} "
                  f"{m['ftsp']:>6.2f} | {m['cluster_min']:>5.1f}-{m['cluster_max']:<6.1f} "
                  f"{m['ftsp_min']:>5.1f}-{m['ftsp_max']:<6.1f} | {100 * m['commit']:>5.0f}% "
                  f"{100 * m['bad']:>4.0f}%", flush=True)
            rows.append(m)
        with open(os.path.join(out_dir, f'fault_axes_head{tag}.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
