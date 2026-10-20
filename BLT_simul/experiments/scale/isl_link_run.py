"""What the distance-dependent ISL model changes: BLT / ATS / FTSP with ideal links
and with blt_isl links, at the fault-profile operating point.

The adopted configuration runs with the link model on. This isolates what the
model contributes by running the same seeds against a perfect link anywhere
inside 2,500 km, so the difference between the arms is the model and nothing
else. It also prints the loss rates each arm produced, because a difference of
zero only means something alongside evidence that links did in fact fail.

Arms:
  ideal       ISL_LINK_MODEL = False (a perfect link inside 2,500 km)
  isl         blt_isl at the registry defaults (pointing jitter 2 urad)
  isl-soft    pointing jitter 4 urad: a soft knee, outages from ~1,000 km out

Columns: member loss = member-to-head exchanges that failed in a local round;
head loss = heads a global round did not reach; flood miss = satellites an FTSP
flood failed to deliver to; hops = mean relay hops from member to head.

Run:  python experiments/scale/isl_link_run.py                 # N = 500 and 8,192, 4 seeds
      python experiments/scale/isl_link_run.py --quick         # smoke test
      BLT_CONFIG=1 python experiments/scale/isl_link_run.py --sizes 8192 --arms isl --out result/runs/part.csv

With BLT_CONFIG=1 every arm uses the adopted settings (timestamp noise, 6 s cycles,
warm-started clusters); the arms differ only in the link model.
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
import engine_profiles
import main_all

K = 12
BASE_SEED = 20260913
UNIT_SCALE = 1e9
ARMS = {
    'ideal': None,
    'isl': {},
    'isl-soft': {'isl_pointing_jitter_rad': 4e-6},
}


def run_arm(sats, ticks, steady, seed, arm):
    overrides = ARMS[arm]
    main_all.ISL_LINK_MODEL = overrides is not None
    main_all.ISL_OVERRIDES = overrides or None
    out, diag = {}, {}
    for name, fn in (('bc', main_all.simulate_bc),
                     ('cluster', main_all.simulate_cluster),
                     ('ftsp', main_all.simulate_ftsp)):
        if name == 'bc':
            main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[])
        main_all.ISL_DIAG.clear()
        perf = fn(sats, ticks, K, sim_seed=seed)
        out[name] = float(np.mean([d.rmse_normal for d in perf[-steady:]])) * UNIT_SCALE
        if name == 'bc':
            d = main_all.BC_DIAG
            rounds = d['commit'] + d['skip']
            out['commit'] = d['commit'] / rounds if rounds else float('nan')
        diag[name] = dict(main_all.ISL_DIAG)
    main_all.ISL_LINK_MODEL = False
    main_all.ISL_OVERRIDES = None
    return out, diag


def _faulty():
    import blt_config
    if blt_config.active():
        return blt_config.FAULTY_STDDEV_HZ, blt_config.FAULTY_DRIFT_BIAS
    return engine_profiles.FAULTY_STDDEV_HZ, engine_profiles.FAULTY_DRIFT_BIAS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', default='500,8192')
    ap.add_argument('--seeds', type=int, default=4)
    ap.add_argument('--fault', type=float, default=0.05)
    ap.add_argument('--arms', default=','.join(ARMS))
    ap.add_argument('--out', default='isl_link_run.csv')
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()

    ticks, steady = (8000, 2500) if args.quick else (40000, 10000)
    seeds = 1 if args.quick else args.seeds
    arms = args.arms.split(',')
    engine_profiles.apply(engine_profiles.FAULT_PROFILE, main_all)
    import blt_config
    if blt_config.active():
        blt_config.apply(main_all)
    faulty_sd, faulty_bias = _faulty()
    print(f'ISL link model run: {ticks} ticks, {seeds} seeds, {100 * args.fault:.0f}% faulty, '
          f'k={K}, range {blt_params.value("isl_range_km"):.0f} km')

    rows = []
    for n in (int(x) for x in args.sizes.split(',')):
        print(f'\n=== N = {n} ===')
        hdr = (f"{'arm':>9} {'BLT':>7} {'ATS':>7} {'FTSP':>7} {'commit':>7}  "
               f"{'member loss':>11} {'head loss':>9} {'flood miss':>10} {'hops':>5}")
        print(hdr)
        print('-' * len(hdr))
        acc = {a: [] for a in arms}
        for r in range(seeds):
            seed = BASE_SEED + r
            sats = main_all.initialize_satellites(
                n, int(round(args.fault * n)),
                malfunction_mean=blt_params.value('osc_nominal_hz'),
                malfunction_stddev=faulty_sd,
                malfunction_drift_bias=faulty_bias,
                cluster_aligned=True, cluster_pick='random', seed=seed)
            for arm in arms:
                acc[arm].append(run_arm(sats, ticks, steady, seed, arm))
        for arm in arms:
            res = {key: float(np.mean([o[key] for o, _ in acc[arm]]))
                   for key in ('bc', 'cluster', 'ftsp', 'commit')}

            def diag(algs, key):
                vals = [dg[a].get(key, np.nan) for _, dg in acc[arm] for a in algs]
                vals = [v for v in vals if not np.isnan(v)]
                return float(np.mean(vals)) if vals else float('nan')
            res.update(member_loss=diag(('bc', 'cluster'), 'local_loss'),
                       head_loss=diag(('bc', 'cluster'), 'head_loss'),
                       flood_unreached=diag(('ftsp',), 'flood_unreached'),
                       hops=diag(('bc',), 'member_hops_mean'))
            fmt = lambda x, pct=False: ('-' if np.isnan(x) else
                                        (f'{100 * x:.2f}%' if pct else f'{x:.2f}'))
            print(f"{arm:>9} {res['bc']:>7.2f} {res['cluster']:>7.2f} {res['ftsp']:>7.2f} "
                  f"{100 * res['commit']:>6.0f}%  {fmt(res['member_loss'], True):>11} "
                  f"{fmt(res['head_loss'], True):>9} {fmt(res['flood_unreached'], True):>10} "
                  f"{fmt(res['hops']):>5}", flush=True)
            rows.append({'n': n, 'arm': arm, **res})

    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'\nwrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
