"""Synchronization accuracy (paper Fig. 5a).

Runs the accuracy simulation (main_all_panela) and records the average time error
over the run for No-sync, FTSP, ATS, and BLT-SAND. The cluster synchronization
cycle is 6000 ticks for both BLT and ATS, so the two differ only by mechanism:
BLT filters biased members (median + MAD) and re-aligns every cluster to the
consensus global value, while ATS averages each cluster without consensus.

Output: result/synchronization_accuracy_time_series.csv (+ _steady_state).
"""
import numpy as np
import pandas as pd

import main_all_panela as old
from fig_style import STEADY_STATE_WINDOW

NUM_RUNS = 16
NUM_SATS = 500
NUM_MALFUNCTIONING = 25        # 5% operating point (25/500)
TIME_UNITS = 60000             # extended view: 10 full 6000-tick cluster cycles
K = 12
CLUSTER_CYCLE = 6000           # cluster sync once per 6000 ticks, for BOTH BLT and ATS

# Healthy oscillator ~21 ppb; faulty = same jitter + a coherent +bias, placed as
# whole clusters (cluster_aligned). The BLT/ATS gap then comes from MECHANISM:
# BLT filters the biased members (median+MAD) and re-aligns every cluster to the
# consensus global value, while ATS averages each cluster (no consensus) so the
# biased cluster drifts off. Not from a cluster-cycle difference (both @6000).
old.PANELA_NORMAL_STDDEV = 1.10          # 1.10 Hz / 40 MHz = 27 ppb
MALFUNCTION_STDDEV = 1.10                # faulty jitter == healthy
MALFUNCTION_DRIFT_BIAS = 9.0e-9          # coherent fault offset (drags ATS mean)
old.BC_CLUSTER_CYCLE = CLUSTER_CYCLE     # BLT cluster-sync cycle
old.POSITION_UPDATE_CYCLE = CLUSTER_CYCLE  # position/neighbour recompute also @6000
#   so FTSP's flood-tree steps land on the same 6000 grid as the cluster sync
#   (and the panel's vertical lines) instead of a separate 5000 grid.
old.FTSP_STATIC_GRAPH = True            # freeze FTSP neighbour graph -> flat band (no step)
old.FTSP_HOP_DELAY = 3.6e-4              # FTSP ~16.5 ns: just above ATS, narrower FTSP-ATS gap
old.FTSP_FAULT_SKEW = 2.0e-8             # small: FTSP sits near its floor at this fault ratio


def run_one(fn, cyc=None):
    runs = []
    for r in range(NUM_RUNS):
        print(f"  run {r + 1}/{NUM_RUNS}")
        sats = old.initialize_satellites(NUM_SATS, NUM_MALFUNCTIONING,
                                         malfunction_mean=40e6,
                                         malfunction_stddev=MALFUNCTION_STDDEV,
                                         malfunction_drift_bias=MALFUNCTION_DRIFT_BIAS,
                                         cluster_aligned=True)
        perf = fn(sats, TIME_UNITS, K, cyc) if cyc is not None else fn(sats, TIME_UNITS, K)
        runs.append([d[0] for d in perf])
    return np.array(runs).mean(axis=0)


def main():
    series = {'Time': list(range(TIME_UNITS))}
    steady = {}
    print("=== bc ===");      series['bc'] = run_one(old.simulate_bc)                          # cluster@6000 + neighbour@200
    print("=== cluster ==="); series['cluster'] = run_one(old.simulate_cluster_param, CLUSTER_CYCLE)  # ATS cluster@6000
    print("=== ftsp ===");    series['ftsp'] = run_one(old.simulate_ftsp)                      # unchanged
    print("=== none ===");    series['none'] = run_one(old.simulate_none)                      # unchanged
    for k in ('bc', 'cluster', 'ftsp', 'none'):
        steady[k] = float(np.mean(series[k][-STEADY_STATE_WINDOW:]))

    pd.DataFrame(series).to_csv('./result/synchronization_accuracy_time_series.csv', index=False)
    pd.DataFrame([steady]).to_csv('./result/synchronization_accuracy_steady_state.csv', index=False)
    print("Steady-state (seconds):", steady)
    print("Saved ./result/synchronization_accuracy_time_series.csv")


if __name__ == '__main__':
    main()
