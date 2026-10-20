"""Which part of BLT-SAND does the work?

The contributions of the hierarchy, the robust filter and the consensus have to
be separated. They cannot be read off the existing figures,
because the comparison there is against ATS and FTSP, different protocols that
differ from BLT-SAND in several ways at once. Using ATS as "BLT without
consensus" is the specific trap: its neighbour selection and its correction
strength differ too, so the gap it shows is not the consensus alone.

Here every arm runs the same engine, the same clusters, the same cycles, the
same head network and the same correction strength. Exactly one stage is
changed at a time:

    local   robust  median + MAD trim (BLT-SAND)      vs  mean  plain average
    global  consensus  proposal carries on a quorum   vs  direct  proposal
                                                          distributed with no
                                                          vote
                                                      vs  off  no global phase

    full          robust + consensus     BLT-SAND as published
    no_filter     mean   + consensus     what the median+MAD trim buys
    no_consensus  robust + direct        what the vote buys
    neither       mean   + direct        hierarchy and cadence only
    local_only    robust + off           no global phase at all

`no_consensus` distributes the same proposal the full arm would have committed,
over the same head network. The only thing removed is the vote, so a lying head
is no longer rejected, which is the mechanism under test.

Run:  python experiments/ledger/ablation.py            # the operating point plus a fault sweep
      python experiments/ledger/ablation.py --quick
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
import engine_profiles
import main_all
from fig_style import UNIT_SCALE

RESULT_DIR = os.environ.get('BLT_SAND_RESULT_DIR', './result')
os.makedirs(RESULT_DIR, exist_ok=True)

engine_profiles.apply(engine_profiles.FAULT_PROFILE, main_all)
import blt_config  # noqa: E402  (BLT_CONFIG=1 switches to the adopted settings)
FAULTY_STDDEV_HZ = engine_profiles.FAULTY_STDDEV_HZ
FAULTY_DRIFT_BIAS = engine_profiles.FAULTY_DRIFT_BIAS
if blt_config.active():
    blt_config.apply(main_all)
    FAULTY_STDDEV_HZ, FAULTY_DRIFT_BIAS = blt_config.FAULTY_STDDEV_HZ, blt_config.FAULTY_DRIFT_BIAS
    RESULT_DIR = os.environ.get('BLT_SAND_RESULT_DIR', './result/runs')
    os.makedirs(RESULT_DIR, exist_ok=True)

NUM_RUNS = 8
NUM_SATS = 500
TIME_UNITS = 40000
K = 12
STEADY_WINDOW = 12000
BASE_SEED = 20260911

# Healthy, the 5% operating point, and past the point where the vote matters.
FAULT_FRACTIONS = (0.0, 0.05, 0.20, 0.35)

ARMS = {
    'full':         ('robust', 'consensus'),
    'no_filter':    ('mean',   'consensus'),
    'no_consensus': ('robust', 'direct'),
    'neither':      ('mean',   'direct'),
    'local_only':   ('robust', 'off'),
}


def simulate_arm(satellites, time_units, k, local, global_, sim_seed=None):
    """One ablation arm. A trimmed copy of main_all.simulate_bc with the two
    stages made selectable; everything else is the engine's own code."""
    m = main_all
    positions, velocities, ang_vels, drifts, frequencies, clocks = m._extract_arrays(satellites)
    normal_mask = ~blt_core.fault_mask(satellites)
    cluster_idx_list = m.cluster_indices_from_kmeans(positions, k)
    drift_step = blt_core.clock_error_step(drifts)
    skew_rate = drifts - 1.0
    is_faulty = ~normal_mask

    # Same engine hooks as simulate_bc, so the arms run under whatever links and
    # measurement noise the profile turned on (the adopted configuration turns both on).
    links = m._link_model(len(clocks), sim_seed) if m.ISL_LINK_MODEL else None
    if links is not None:
        links.update(positions, cluster_idx_list, 0.0)
    noise_rng = (np.random.default_rng((sim_seed or 0) + 4241)
                 if m.LOCAL_MEASUREMENT_NOISE else None)
    m._measurement_setup(len(clocks), sim_seed)
    # the ledger record the head selection reads, when the caller asked for it: the arms
    # differ in one stage, so an arm that drops the vote keeps the published head choice
    m._LEDGER['score'] = np.zeros(len(clocks)) if m.HEAD_POLICY == 'history' else None

    perf = []
    pos_t = 0
    for i in range(time_units):
        clocks += drift_step
        perf.append(m.measure_sync_performance_vec(clocks, normal_mask))

        if i % m.BC_LOCAL_CYCLE == 0:
            reach = links.local_reach() if links is not None else None
            hops = m._member_hops(links, len(clocks))
            if local == 'robust':
                m.sync_local_robust(clocks, cluster_idx_list, reach=reach,
                                    noise_rng=noise_rng, hops=hops)
            else:
                m.sync_with_cluster_vec(clocks, cluster_idx_list, reach=reach,
                                        noise_rng=noise_rng, hops=hops)
        if global_ != 'off' and i % m.BC_CLUSTER_CYCLE == 0:
            round_no = i // m.BC_CLUSTER_CYCLE
            head_reach = (links.head_reach(round_no % len(cluster_idx_list))
                          if links is not None else None)
            m.sync_with_cluster_bc_vec(
                clocks, cluster_idx_list, positions, skew_rate, is_faulty,
                round_no=round_no, require_quorum=(global_ == 'consensus'),
                head_reach=head_reach)

        pos_t += 1
        if pos_t >= m.POSITION_UPDATE_CYCLE:
            positions = m.update_positions_vec(positions, velocities, ang_vels,
                                               m.POSITION_UPDATE_CYCLE)
            pos_t = 0
            cluster_idx_list = m.recluster(positions, k, cluster_idx_list)
            if links is not None:
                links.update(positions, cluster_idx_list, (i + 1) * m.TIME_TICK)
    return perf


def messages_per_global_round(arm: str, k: int) -> int:
    """Head-to-head messages one global round costs, from the protocol shape.

    Counted, not measured: a proposal reaches k-1 heads, and a vote arm adds one
    vote back from each. `off` spends nothing because there is no global phase.
    This is what makes the accuracy differences comparable on cost.
    """
    _, global_ = ARMS[arm]
    if global_ == 'off':
        return 0
    if global_ == 'direct':
        return k - 1
    return 2 * (k - 1)


def run_point(fault_frac: float, time_units: int, n_sats: int, k: int,
              steady: int, runs: int) -> list:
    n_faulty = int(round(fault_frac * n_sats))
    rows = []
    acc = {a: {'rmse': [], 'abs': [], 'commit': [], 'bad': []} for a in ARMS}

    for r in range(runs):
        seed = BASE_SEED + r
        sats = main_all.initialize_satellites(
            n_sats, n_faulty,
            malfunction_mean=engine_profiles.blt_params.value('osc_nominal_hz'),
            malfunction_stddev=FAULTY_STDDEV_HZ,
            malfunction_drift_bias=FAULTY_DRIFT_BIAS,
            cluster_aligned=True, seed=seed)

        for arm, (local, global_) in ARMS.items():
            main_all.BC_DIAG.update(commit=0, skip=0, bad_commit=0, flagged=[])
            perf = simulate_arm(sats, time_units, k, local, global_, sim_seed=seed)
            tail = [d.rmse_normal for d in perf[-steady:]]
            tail_abs = [d.rmse_absolute for d in perf[-steady:]]
            rounds = main_all.BC_DIAG['commit'] + main_all.BC_DIAG['skip']
            acc[arm]['rmse'].append(np.mean(tail))
            acc[arm]['abs'].append(np.mean(tail_abs))
            if rounds:
                acc[arm]['commit'].append(main_all.BC_DIAG['commit'] / rounds)
                acc[arm]['bad'].append(main_all.BC_DIAG['bad_commit'] / rounds)

    for arm in ARMS:
        rows.append({
            'fault_pct': 100 * fault_frac,
            'arm': arm,
            'local': ARMS[arm][0],
            'global': ARMS[arm][1],
            'rmse_normal_ns': float(np.mean(acc[arm]['rmse'])) * UNIT_SCALE,
            'rmse_absolute_ns': float(np.mean(acc[arm]['abs'])) * UNIT_SCALE,
            'commit_rate': float(np.mean(acc[arm]['commit'])) if acc[arm]['commit'] else float('nan'),
            'bad_commit_rate': float(np.mean(acc[arm]['bad'])) if acc[arm]['bad'] else float('nan'),
            'msgs_per_global_round': messages_per_global_round(arm, k),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()

    n_sats = 200 if args.quick else int(os.environ.get('BLT_SATS', NUM_SATS))
    ticks = 8000 if args.quick else TIME_UNITS
    steady = 2500 if args.quick else STEADY_WINDOW
    k = 6 if args.quick else K
    runs = 2 if args.quick else int(os.environ.get('BLT_RUNS', NUM_RUNS))

    print(f"ablation: {n_sats} sats, k={k}, {ticks} ticks, {runs} seeds, "
          f"quorum={main_all.BC_QUORUM:.3f}")
    print("every arm shares clusters, cycles, head network and correction strength\n")

    rows = []
    for frac in FAULT_FRACTIONS:
        print(f"--- faulty members {100*frac:.0f}% ---")
        hdr = (f"  {'arm':14} {'local':>7} {'global':>10} {'rel ns':>8} "
               f"{'ABS ns':>9} {'commit':>7} {'BAD':>6} {'msg':>5}")
        print(hdr)
        pts = run_point(frac, ticks, n_sats, k, steady, runs)
        for r in pts:
            print(f"  {r['arm']:14} {r['local']:>7} {r['global']:>10} "
                  f"{r['rmse_normal_ns']:>8.2f} {r['rmse_absolute_ns']:>9.2f} "
                  f"{r['commit_rate']:>7.2f} {r['bad_commit_rate']:>6.2f} "
                  f"{r['msgs_per_global_round']:>5}", flush=True)
        rows.extend(pts)
        pd.DataFrame(rows).to_csv(os.path.join(RESULT_DIR, 'ablation.csv'), index=False)
        print()

    print("Saved " + os.path.join(RESULT_DIR, 'ablation.csv'))
    print("\nRead the arms in pairs: full vs no_filter isolates the median+MAD")
    print("trim, full vs no_consensus isolates the vote, and local_only shows")
    print("what the hierarchy alone achieves.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
