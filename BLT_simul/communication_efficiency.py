"""Communication efficiency (paper Fig. 5c) — analytical communication overhead vs constellation size N.

Each algorithm's message rate at its natural operating point is computed from
the algorithm structure (no simulation needed):

  ATS  : cluster sync floods N msgs every ATS_PERIOD_S
  BC   : cluster sync (N msgs / BC_PERIOD_S)
         + BFT consensus among k cluster heads (PBFT_ROUNDS × k² msgs / BC_PERIOD_S)
  FTSP : global flood (N msgs / FTSP_PERIOD_S)

Local neighbor-sync messages are excluded — they are 1-hop pairwise exchanges
with negligible per-message cost compared to cluster aggregation or global
flooding, and they run at the same fixed rate (5 Hz) for both BC and ATS so
they would not differentiate the two anyway.

Output: result/communication_efficiency.csv.
"""

import numpy as np
import pandas as pd

N_VALUES = [500, 1000, 2000, 4000, 6000, 8000, 10000]
K = 12

BC_PERIOD_S = 5.0      # longest cluster cycle that still keeps BC steady-state ≤ 10 ns
ATS_PERIOD_S = 1.5     # shortest cycle ATS can stretch to before steady-state exceeds 10 ns
FTSP_PERIOD_S = 0.6    # shortest flooding cycle FTSP needs to keep steady-state ≤ 10 ns

PBFT_ROUNDS = 3        # h-PBFT propose / prepare / commit


def msgs_per_sec_ats(n):
    return n / ATS_PERIOD_S


def msgs_per_sec_bc(n):
    cluster = n / BC_PERIOD_S
    bft_consensus = (PBFT_ROUNDS * K * K) / BC_PERIOD_S
    return cluster + bft_consensus


def msgs_per_sec_ftsp(n):
    return n / FTSP_PERIOD_S


def main():
    rows = []
    for n in N_VALUES:
        rows.append({
            'N': n,
            'bc': msgs_per_sec_bc(n),
            'cluster': msgs_per_sec_ats(n),
            'ftsp': msgs_per_sec_ftsp(n),
        })
    df = pd.DataFrame(rows)
    df.to_csv('./result/communication_efficiency.csv', index=False)
    print(df.to_string(index=False))
    print("\nSaved ./result/communication_efficiency.csv")


if __name__ == '__main__':
    main()
