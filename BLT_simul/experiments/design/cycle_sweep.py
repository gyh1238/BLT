"""Local and global cadence, swept one at a time.

The adopted configuration holds the two equal at 6 s, which answers what the
design costs but not which of the two the accuracy depends on. Moving one at a
time separates them.

They do different jobs:

    local   median + MAD inside each cluster. Bounds how far a cluster's own
            members drift apart, and how much a degraded member can move the
            cluster reference before the trim catches it.
    global  agreement among cluster heads. Bounds how far whole clusters drift
            apart from each other.

The measurement inverts the guess this file was written with. Shortening the
local period was expected to matter most under faults, and the global period to
matter regardless. It is the other way round:

    no faults    local 3.5x across its range, global 2.0x
    15% faulty   local 1.7x,                  global 3.3x

With healthy oscillators the error is drift accumulating inside each cluster,
and only the local phase bounds that, the clusters have little to disagree
about, so the global phase has little to fix. Once oscillators degrade, a bad
cluster's own reference walks away; trimming members cannot pull a cluster back
toward the others, and only the global phase re-anchors them. The stage that
helps is the one that addresses the error actually dominating.

Which gives the design rule directly: tighten the LOCAL cadence when the fleet
is healthy and drift dominates, tighten the GLOBAL cadence when a meaningful
fraction has degraded.

Each sweep holds one period at its profile value and varies the other, so a
difference is attributable to the axis being moved.

Run:  python experiments/design/cycle_sweep.py
      python experiments/design/cycle_sweep.py --quick
      BLT_CONFIG=1 python experiments/design/cycle_sweep.py --fault 0.15 --axis global --value 6000 --out part.csv

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

import engine_profiles
import main_all
from fig_style import UNIT_SCALE, ISL_REQUIREMENT_NS

RESULT_DIR = os.environ.get('BLT_SAND_RESULT_DIR', './result')
os.makedirs(RESULT_DIR, exist_ok=True)

engine_profiles.apply(engine_profiles.FAULT_PROFILE, main_all)
import blt_config  # noqa: E402
FAULTY_STDDEV_HZ, FAULTY_DRIFT_BIAS = engine_profiles.FAULTY_STDDEV_HZ, engine_profiles.FAULTY_DRIFT_BIAS
if blt_config.active():
    blt_config.apply(main_all)
    FAULTY_STDDEV_HZ, FAULTY_DRIFT_BIAS = blt_config.FAULTY_STDDEV_HZ, blt_config.FAULTY_DRIFT_BIAS
    RESULT_DIR = os.environ.get('BLT_SAND_RESULT_DIR', './result/runs')
    os.makedirs(RESULT_DIR, exist_ok=True)

BASE_LOCAL = main_all.BC_LOCAL_CYCLE      # 2700 ticks = 2.7 s
BASE_GLOBAL = main_all.BC_CLUSTER_CYCLE   # 5500 ticks = 5.5 s

NUM_RUNS = 3 if blt_config.active() else 6
NUM_SATS = blt_config.N_SATS if blt_config.active() else 500
TIME_UNITS = 40000
K = 12
STEADY_WINDOW = 12000
BASE_SEED = 20260911

LOCAL_TICKS = (900, 1800, 2700, 4500, 6750)
GLOBAL_TICKS = (2000, 3500, 5500, 8000, 11000)
if blt_config.active():   # the same 1/3x .. 2x span around the adopted 6 s cadence
    LOCAL_TICKS = GLOBAL_TICKS = (2000, 3000, 6000, 9000, 12000)
FAULT_FRACTIONS = (0.0, 0.15)


ONLY_VALUE = None


def run_point(local_ticks, global_ticks, fault_frac, n_sats, ticks, k, steady, runs):
    main_all.BC_LOCAL_CYCLE = local_ticks
    main_all.BC_CLUSTER_CYCLE = global_ticks
    n_faulty = int(round(fault_frac * n_sats))
    rel, absol = [], []
    for r in range(runs):
        seed = BASE_SEED + r
        sats = main_all.initialize_satellites(
            n_sats, n_faulty,
            malfunction_mean=engine_profiles.blt_params.value('osc_nominal_hz'),
            malfunction_stddev=FAULTY_STDDEV_HZ,
            malfunction_drift_bias=FAULTY_DRIFT_BIAS,
            cluster_aligned=True, seed=seed)
        perf = main_all.simulate_bc(sats, ticks, k, sim_seed=seed)
        rel.append(np.mean([d.rmse_normal for d in perf[-steady:]]))
        absol.append(np.mean([d.rmse_absolute for d in perf[-steady:]]))
    return float(np.mean(rel)) * UNIT_SCALE, float(np.mean(absol)) * UNIT_SCALE


def sweep(axis, values, fault_frac, n_sats, ticks, k, steady, runs, rows):
    print(f"  {'period s':>9} {'rel ns':>8} {'ABS ns':>9} {'vs 10 ns':>9}")
    for v in values:
        if ONLY_VALUE is not None and v != ONLY_VALUE:
            continue
        if axis == 'local':
            lt, gt = v, BASE_GLOBAL
        else:
            lt, gt = BASE_LOCAL, v
        rel, absol = run_point(lt, gt, fault_frac, n_sats, ticks, k, steady, runs)
        print(f"  {v/1000:>9.1f} {rel:>8.2f} {absol:>9.2f} "
              f"{'PASS' if rel <= ISL_REQUIREMENT_NS else 'over':>9}", flush=True)
        rows.append({'axis': axis, 'period_ticks': v, 'period_s': v / 1000,
                     'fault_pct': 100 * fault_frac,
                     'local_ticks': lt, 'global_ticks': gt,
                     'rmse_normal_ns': rel, 'rmse_absolute_ns': absol})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--fault', type=float, default=None, help='run one fault fraction only')
    ap.add_argument('--axis', choices=('local', 'global'), default=None, help='run one axis only')
    ap.add_argument('--value', type=int, default=None, help='run one period [ticks] only')
    ap.add_argument('--seeds', type=int, default=None)
    ap.add_argument('--out', default='cycle_sweep.csv')
    args = ap.parse_args()
    global ONLY_VALUE
    ONLY_VALUE = args.value

    n_sats = 200 if args.quick else NUM_SATS
    ticks = 8000 if args.quick else TIME_UNITS
    steady = 2500 if args.quick else STEADY_WINDOW
    k = 6 if args.quick else K
    runs = args.seeds or (2 if args.quick else NUM_RUNS)

    print(f"cycle sweep: {n_sats} sats, k={k}, {ticks} ticks, {runs} seeds")
    print(f"baseline local {BASE_LOCAL/1000:.1f} s, global {BASE_GLOBAL/1000:.1f} s\n")

    rows = []
    for frac in (FAULT_FRACTIONS if args.fault is None else (args.fault,)):
        for axis, values in (('local', LOCAL_TICKS), ('global', GLOBAL_TICKS)):
            if args.axis is not None and axis != args.axis:
                continue
            other = 'global' if axis == 'local' else 'local'
            held = BASE_GLOBAL if axis == 'local' else BASE_LOCAL
            print(f"--- {axis} period swept, {other} held at {held/1000:.1f} s, "
                  f"{100*frac:.0f}% faulty ---")
            sweep(axis, values, frac, n_sats, ticks, k, steady, runs, rows)
            print()
            pd.DataFrame(rows).to_csv(os.path.join(RESULT_DIR, args.out), index=False)

    main_all.BC_LOCAL_CYCLE = BASE_LOCAL
    main_all.BC_CLUSTER_CYCLE = BASE_GLOBAL
    print("Saved " + os.path.join(RESULT_DIR, args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
