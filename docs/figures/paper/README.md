# Paper figures

The four figures as the paper carries them, each as a PDF and as a PNG of the same page. Figures 1–3
are concept diagrams drawn by hand, which is why they live here as images rather than as a script.
Figure 4 is the design assessment, and the results in it come from this repository.

| File | Figure |
|---|---|
| `fig1_rev` | Fig. 1. System model: ISL-interconnected LEO constellation, the ≤10 ns pointing tolerance, clock drift and TWTT |
| `fig2_rev` | Fig. 2. Decentralized synchronization procedure: the constellation, consensus and blockchain layers, and one synchronization cycle |
| `fig3_rev` | Fig. 3. Block structure (header 222 B + body 6,386 B + vote evidence 70 B = 6,678 B = 6,678 B; the body is derived field by field in [the chain readme](../../../BLT_bft_chain/readme.md#what-the-blt-module-does)) and the propose → prepare → commit mechanism |
| `fig4_rev` | Fig. 4. Digital-twin testbed and design assessment: component ablation, accuracy, fault tolerance, communication efficiency, deployment flexibility |

## Where Fig. 4 comes from

Every part of it is a panel in [`docs/FIGURES.md`](../../FIGURES.md), rendered from the same CSVs by
`BLT_simul/figures/evaluation_panels.py`:

| In Fig. 4 | The panel it is drawn from |
|---|---|
| component ablation | [§3.1](../../FIGURES.md#31-the-ablation-as-one-table) |
| synchronization accuracy | [§1.1](../../FIGURES.md#11-synchronization-accuracy-over-time) |
| fault tolerance | [§2.1](../../FIGURES.md#21-member-faults) and [§2.2](../../FIGURES.md#22-cluster-head-faults) |
| comm. efficiency | [§6.3](../../FIGURES.md#63-communication-efficiency) |
| deployment flexibility | [§6.4](../../FIGURES.md#64-deployment-flexibility) |

Fig. 4 carries one fault-tolerance panel against the two in `FIGURES.md`, which measure the member
axis and the head axis separately: a page of panels has the room for both and a quarter-page panel
does not.

The testbed image inside Fig. 4 is a capture of the Unity scene in [`BLT_dt/`](../../../BLT_dt),
running against a live chain.
