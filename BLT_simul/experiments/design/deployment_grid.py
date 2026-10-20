"""Measure the (cluster count, block interval) surface.

The deployment panel draws a smooth surface,

    RMSE(Nc, T) = R_FLOOR + R_MAX * (1 - exp(-T / TAU)) + NC_COEF * (Nc - 12)

and this is where its constants come from. The two axes are swept through the
engine on a coarse grid, the closed form is least-squares fitted to the points
that come back, and `deployment_fit.csv` carries the result. The panel keeps a
smooth surface, which a coarse grid cannot give directly, while every constant
in it is answerable to simulation output.

Coarse on purpose: a full 241 x 17 grid is 4,097 configurations. Five values per
axis with several seeds each captures the curvature the panel needs, and the fit
interpolates between them.

Run:  python experiments/design/deployment_grid.py
      python experiments/design/deployment_grid.py --quick
      BLT_CONFIG=1 python experiments/design/deployment_grid.py --nc 12 --t 6 --out part.csv   # one grid point
      python experiments/design/deployment_grid.py --fit result/runs/deployment_grid.csv  # fit a merged grid

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
_sys.path.insert(0, _os.path.join(_ROOT, "experiments"))

import numpy as np
import pandas as pd

import engine_profiles
import main_all
from fig_style import UNIT_SCALE

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

NUM_RUNS = 3 if blt_config.active() else 4
NUM_SATS = blt_config.N_SATS if blt_config.active() else 500
TIME_UNITS = 30000
STEADY_WINDOW = 9000
BASE_SEED = 20260911
FAULT_FRACTION = 0.05          # the operating point the panels quote

NC_GRID = (6, 12, 18, 24, 30)
T_GRID_S = (2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0)


LOCAL_FROM_MEMBERS = False
LOCAL_EQUALS_BLOCK = False   # the manuscript's model: one local + global round per block
IDEAL_LINKS = False          # members reach their head directly (ISL link model off)


def local_cycle_ticks(nc, n_sats):
    """Local cycle for a cluster count: the time a head needs to poll its members
    (experiments/design/collection_time.py), as the manuscript derives the 6 s cycle."""
    import collection_time
    return int(round(collection_time.collection_time(n_sats, nc)['T_local_s'] * 1000))


# The steady-state window is a whole number of block intervals. A fixed window
# is shorter than one cycle from T = 10 s up, and then the value samples wherever
# the sawtooth happens to sit at the end of the run rather than its mean, which
# can make a longer interval measure better than a shorter one.
# The window is now a whole number of cycles and the run is long enough to hold
# them after the transient.
STEADY_CYCLES = 3        # whole block cycles averaged
MIN_CYCLES = 12          # cycles simulated before the window is taken


def cycle_window(t_s, ticks, steady):
    """(ticks, steady) for one block interval: at least MIN_CYCLES cycles long,
    with the last STEADY_CYCLES whole cycles averaged."""
    cyc = int(round(t_s * 1000))
    return max(ticks, MIN_CYCLES * cyc), max(steady, STEADY_CYCLES * cyc)


def measure(nc, t_s, n_sats, ticks, steady, runs):
    """Steady-state healthy-satellite RMSE in ns for one (Nc, T) configuration.

    T sets the global block interval. The local cadence is the profile value, or
    with --local-from-members the collection time of an Nc-cluster constellation.
    The run length and the averaging window both scale with T (see cycle_window).
    """
    ticks, steady = cycle_window(t_s, ticks, steady)
    main_all.BC_CLUSTER_CYCLE = int(round(t_s * 1000))
    if LOCAL_FROM_MEMBERS:
        main_all.BC_LOCAL_CYCLE = local_cycle_ticks(nc, n_sats)
    if LOCAL_EQUALS_BLOCK:
        main_all.BC_LOCAL_CYCLE = main_all.BC_CLUSTER_CYCLE
    if IDEAL_LINKS:
        main_all.ISL_LINK_MODEL = False
    n_faulty = int(round(FAULT_FRACTION * n_sats))
    vals = []
    for r in range(runs):
        seed = BASE_SEED + r
        sats = main_all.initialize_satellites(
            n_sats, n_faulty,
            malfunction_mean=engine_profiles.blt_params.value('osc_nominal_hz'),
            malfunction_stddev=FAULTY_STDDEV_HZ,
            malfunction_drift_bias=FAULTY_DRIFT_BIAS,
            cluster_aligned=True, seed=seed)
        perf = main_all.simulate_bc(sats, ticks, nc, sim_seed=seed)
        vals.append(np.mean([d.rmse_normal for d in perf[-steady:]]))
    return float(np.mean(vals)) * UNIT_SCALE


def fit_surface(df):
    """Least-squares fit of the panel's functional form to the measured grid.

    Returns (R_FLOOR, R_MAX, TAU, NC_COEF). TAU enters non-linearly, so it is
    scanned over a small grid and the linear coefficients solved at each value.
    """
    nc = df['Nc'].values.astype(float)
    T = df['T_s'].values.astype(float)
    y = df['rmse_ns'].values.astype(float)

    best = None
    for tau in np.linspace(1.0, 15.0, 141):
        # y ~ a + b * (1 - exp(-T/tau)) + c * (Nc - 12)
        A = np.column_stack([np.ones_like(T), 1 - np.exp(-T / tau), nc - 12.0])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = float(np.sum((A @ coef - y) ** 2))
        if best is None or resid < best[0]:
            best = (resid, tau, coef)
    resid, tau, (a, b, c) = best
    rms = float(np.sqrt(resid / len(y)))
    return dict(R_FLOOR=a, R_MAX=b, TAU=tau, NC_COEF=c, fit_rms_ns=rms)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--nc', type=int, default=None, help='run one cluster count only')
    ap.add_argument('--t', type=float, default=None, help='run one block interval [s] only')
    ap.add_argument('--seeds', type=int, default=None)
    ap.add_argument('--out', default='deployment_grid.csv')
    ap.add_argument('--fit', default=None, help='only fit an existing (merged) grid csv')
    ap.add_argument('--local-from-members', action='store_true',
                    help='local cycle = member collection time for each Nc (feasible iff T >= it)')
    ap.add_argument('--local-equals-block', action='store_true',
                    help='local cycle = block interval (manuscript Fig. 4(d) model); feasibility from collection time')
    ap.add_argument('--ideal-links', action='store_true', help='ISL link model off: members reach the head in one hop')
    args = ap.parse_args()
    global LOCAL_FROM_MEMBERS, LOCAL_EQUALS_BLOCK, IDEAL_LINKS
    LOCAL_FROM_MEMBERS = args.local_from_members
    LOCAL_EQUALS_BLOCK = args.local_equals_block
    IDEAL_LINKS = args.ideal_links
    if args.fit:
        fit = fit_surface(pd.read_csv(args.fit))
        for k, v in fit.items():
            print(f"  {k:12} = {v:.4f}")
        out = os.path.join(os.path.dirname(args.fit), 'deployment_fit.csv')
        pd.DataFrame([fit]).to_csv(out, index=False)
        print('Saved ' + out)
        return 0

    n_sats = 200 if args.quick else NUM_SATS
    ticks = 8000 if args.quick else TIME_UNITS
    steady = 2500 if args.quick else STEADY_WINDOW
    runs = args.seeds or (2 if args.quick else NUM_RUNS)

    print(f"deployment grid: {n_sats} sats, {ticks} ticks, {runs} seeds, "
          f"{100*FAULT_FRACTION:.0f}% faulty")
    print(f"local cadence held at {main_all.BC_LOCAL_CYCLE/1000:.1f} s\n")

    rows = []
    hdr = "  Nc \\ T" + "".join(f"{t:>9.1f}s" for t in T_GRID_S)
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for nc in (NC_GRID if args.nc is None else (args.nc,)):
        line = f"  {nc:>6}"
        for t in (T_GRID_S if args.t is None else (args.t,)):
            v = measure(nc, t, n_sats, ticks, steady, runs)
            row = {'Nc': nc, 'T_s': t, 'rmse_ns': v}
            if LOCAL_FROM_MEMBERS:
                row['T_local_s'] = main_all.BC_LOCAL_CYCLE / 1000
                row['feasible'] = int(t >= row['T_local_s'])
            elif LOCAL_EQUALS_BLOCK:
                row['T_collect_s'] = local_cycle_ticks(nc, n_sats) / 1000
                row['feasible'] = int(t >= row['T_collect_s'])
                row['links'] = 'ideal' if IDEAL_LINKS else 'model'
            rows.append(row)
            line += f"{v:>10.2f}"
        print(line, flush=True)
        pd.DataFrame(rows).to_csv(os.path.join(RESULT_DIR, args.out), index=False)
    if args.nc is not None or args.t is not None:
        print('Saved ' + os.path.join(RESULT_DIR, args.out) + ' (partial grid; merge, then --fit)')
        return 0

    df = pd.DataFrame(rows)
    fit = fit_surface(df)
    print("\nfitted to the measured grid (same form panel_d expects):")
    for k, v in fit.items():
        print(f"  {k:12} = {v:.4f}")
    pd.DataFrame([fit]).to_csv(os.path.join(RESULT_DIR, 'deployment_fit.csv'),
                               index=False)

    print(f"\nSaved deployment_grid.csv and deployment_fit.csv in {RESULT_DIR}")
    print("deployment_flexibility.py can take R_FLOOR/R_MAX/TAU/NC_COEF from")
    print("deployment_fit.csv instead of the hand-set constants.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
