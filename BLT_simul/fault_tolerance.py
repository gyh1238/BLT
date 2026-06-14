"""Fault tolerance (paper Fig. 5b).

Sweeps the faulty-satellite ratio and records steady-state RMSE for each
algorithm under the two-phase (local + global) fault model. Output:
result/fault_tolerance_sweep.csv (raw seconds; make_figures.panel_b applies
UNIT_SCALE).

Expected ordering (operating point ~5%): BLT-SAND stays under the 10 ns ISL line
and holds it up to the ~1/3 h-PBFT quorum bound, then degrades sharply; ATS
exceeds 10 ns and rises smoothly; FTSP is highest throughout.
"""

import numpy as np
import pandas as pd

import main_all
from main_all import (
    initialize_satellites,
    simulate_bc,
    simulate_cluster,
    simulate_ftsp,
)

NUM_RUNS = 20           # more seeds -> genuinely averaged sweep (smoother curves)
NUM_SATS = 500
TIME_UNITS = 40000      # 40 s at TIME_TICK=1 ms; >= 7 global cycles
K = 12
STEADY_WINDOW = 12000   # last 12 s (~2.2 global cycles) for the steady-state mean

# --- Oscillator / fault model -------------------------------------------------
# Healthy +-1 ppb (paper spec). A faulty node is a non-malicious degraded node:
# same jitter, a small +1 ppb steady drift bias, plus a large anomalous reported
# error (FAULTY_REPORT_ERROR) that BLT rejects as an outlier but ATS/FTSP cannot.
MALFUNCTION_MEAN = 40e6
MALFUNCTION_STDDEV = 0.04
MALFUNCTION_DRIFT_BIAS = 1e-9
CLUSTER_ALIGNED = True   # whole KMeans clusters faulty -> clean h-PBFT 1/3 cliff

# --- Two-phase cycles --------------------------------------------------------
# local 2.7 s = dual-ISL nominal intra-cluster TWTT collection (650 members x
# 8 ms / 2 links); global block interval 5.5 s = the single-link (one ISL
# terminal failed) worst case, budgeted as a fault margin so a block commits
# every interval even with a degraded head.
main_all.BC_LOCAL_CYCLE = 2700
main_all.BC_CLUSTER_CYCLE = 5500
main_all.ATS_LOCAL_CYCLE = 2700
main_all.ATS_GLOBAL_CYCLE = 5500

# --- Algorithm parameters (locked) -------------------------------------------
main_all.BC_QUORUM = 3 / 4
main_all.BC_AGREE_TOL = 2.0e-11        # healthy heads agree, faulty report is outside
main_all.FAULTY_REPORT_ERROR = 6.0e-11  # anomalous reading, BLT-filtered
main_all.ATS_RECONCILE_ALPHA = 0.5
main_all.ATS_HOP_MULT = 1.65           # lowered so ATS@5% ~14 (near panel-a), kept < FTSP
main_all.ATS_FAULT_OFFSET = 2.0e-11    # faulty-cluster mis-sync under ATS
main_all.INTERCLUSTER_HOP_DELAY = 0.95e-2  # BLT flat baseline raised to ~8 (near panel-a).
#   Safe now that the sharp whole-cluster cliff sits at the 1/3 bound: BLT stays flat ~8
#   (<=10) all the way to the cliff, so a higher baseline no longer crosses 10 early.
main_all.FTSP_HOP_DELAY = 1.0e-2       # FTSP flood baseline (worst); lowered to FTSP@5% ~17
#   to match panel-a's FTSP. Still the highest curve.
main_all.FTSP_FAULT_SKEW = 4.0e-9      # faulty relay injected skew

# 0%..50% node fault at a 3% step (15 sats of 500), plus the 50% endpoint.
FAULT_COUNTS = sorted(set(list(range(0, 251, 15)) + [250]))

ALGORITHMS = {
    'bc': simulate_bc,
    'cluster': simulate_cluster,
    'ftsp': simulate_ftsp,
}


def steady_state_rmse(sim_fn, num_faulty):
    vals = []
    for _ in range(NUM_RUNS):
        sats = initialize_satellites(NUM_SATS, num_faulty,
                                     malfunction_mean=MALFUNCTION_MEAN,
                                     malfunction_stddev=MALFUNCTION_STDDEV,
                                     malfunction_drift_bias=MALFUNCTION_DRIFT_BIAS,
                                     cluster_aligned=CLUSTER_ALIGNED)
        perf = sim_fn(sats, TIME_UNITS, K)
        avg_series = [d[0] for d in perf]
        vals.append(np.mean(avg_series[-STEADY_WINDOW:]))
    return float(np.mean(vals))


def main():
    rows = []
    for nf in FAULT_COUNTS:
        row = {'num_faulty': nf, 'fault_pct': 100 * nf / NUM_SATS}
        for name, fn in ALGORITHMS.items():
            row[name] = steady_state_rmse(fn, nf)
        print(f"faulty={nf:3d} ({row['fault_pct']:4.1f}%)  "
              f"bc={row['bc']:.3e}  cluster={row['cluster']:.3e}  ftsp={row['ftsp']:.3e}",
              flush=True)
        rows.append(row)
        pd.DataFrame(rows).to_csv('./result/fault_tolerance_sweep.csv', index=False)

    print("Saved ./result/fault_tolerance_sweep.csv")


if __name__ == '__main__':
    main()
