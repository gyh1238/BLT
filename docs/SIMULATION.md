# How the simulation works

What is simulated and in what order, at the level of the code. Parameter values and where they come
from are in [`MODEL.md`](MODEL.md); the results are in [`FIGURES.md`](FIGURES.md); the sources
behind the assumptions are in [`REFERENCES.md`](REFERENCES.md). This document is the mechanism.

**Contents**
[1. The constellation](#1-the-constellation) ·
[2. Clocks and faults](#2-clocks-and-faults) ·
[3. Measurement](#3-measurement-two-way-exchange) ·
[4. Local phase](#4-local-phase-cluster-aggregation) ·
[5. Global phase](#5-global-phase-consensus-among-heads) ·
[6. What it is compared against](#6-what-it-is-compared-against) ·
[7. The fault constants](#7-the-fault-constants) ·
[8. Metrics](#8-metrics) ·
[9. Running it](#9-running-it)

---

## 1. The constellation

8,192 satellites, built from real Starlink two-line element sets
(`main_all._get_or_synthesize_constellation`).

Space-Track's user agreement does not allow the elements to be redistributed, so **no element set
is shipped here**, you fetch your own, and [`BLT_simul/data/README.md`](../BLT_simul/data/README.md)
says how.

**Every run here is at N = 8,192**, the full constellation. Nothing runs without an element file:
each driver builds its constellation from one and stops if it is absent. The file supplies as many
of the 8,192 as it covers and the engine completes the rest rather than refusing to start: it picks a
satellite already in the set and rotates it about the z-axis, keeping its altitude and inclination
and giving it a new longitude. Completed satellites are named `SYNTH-k`, the choice is seeded, and
one file always gives one constellation, so a result is reproducible from the same inputs. The
altitude band and the inclination spread are those of the real set; the spacing within an orbital
plane is not, and spacing is what the link graph and the hop counts are built from.

k-means partitions them by position into **12 clusters**. Nothing constrains the sizes, so they
follow the geometry: at N = 8,192 a partition runs from about 450 to about 810 members, averaging
8,192/12 = 683. The cadence is budgeted on that average, 683 members over two ISL terminals, so a
head with more members than average spends more of its cycle collecting, and the largest cluster
in a given partition can need longer than the 6 s the cycle allows.

Twelve is the reference point the rest of this document uses. It is one configuration rather than a
required one, and §4.4 of the [README](../README.md#44-deployment-flexibility) sweeps the cluster
count against the block interval to show which others are feasible; twelve at a 6 s interval sits
inside that region. What fixes it here is the collection time: with two ISL terminals a head needs
5.69 s to poll 683 members over an average 1.97 hops, which is what fits inside 6 s.

Positions are propagated every 6 s and the clustering is re-run from the previous centroids rather
than from scratch, a warm start, so that a satellite drifting a few hundred kilometres does not
cause the whole partition to be redrawn.

Because the satellites move, membership keeps changing: 0.47% change cluster every 5 s, and 48.7%
within ten minutes. That turnover is measured, not assumed
([`FIGURES.md` §3.5](FIGURES.md#34-how-fast-cluster-membership-turns-over)).

Each cluster has one **head**. The adopted design picks it from the ledger record: among the ten
members nearest the cluster centroid, the one whose recorded precision is best
(`HEAD_POLICY='history'`). The candidates are restricted to the centroid's neighbourhood because a
head has to be in ISL reach of its members. The alternative, `'centroid'`, simply the member
nearest the centre, with no memory, is the no-ledger arm of the ablation.

This interacts with the head fault rule in a way worth being explicit about. If a cluster contains
healthy satellites, the ledger selects one of them. If a cluster is degraded throughout, there is
nothing healthy to select and its head reports a wrong value. So "the head of a mostly-degraded
cluster misreports" is a **consequence of the selection rule**, not a separate assumption bolted on.

## 2. Clocks and faults

Oscillators run at 40 MHz. A healthy one has **1 ppb** of fractional frequency spread; a degraded
one has **27.5 ppb of spread plus a 19 ppb bias**. The bias is what makes a fault accumulate rather
than average away, a zero-mean spread would cancel over enough members, and a one-directional
offset does not.

**The faults are not malicious.** A degraded satellite stays up, follows the protocol, and reports
the value it believes. Nothing forges a signature, withholds a message or lies on purpose.

**When:** degradation is permanent for the whole run by default. Only the intermittent experiment
turns it on and off, independently each round with probability 1/3, memoryless, so a satellite's
newest measurement says little about its next one.

**Where** (the placement, which matters more than the share):

| Placement | What it does |
|---|---|
| `scattered` | uniformly at random over all satellites |
| `cluster_aligned` | fills whole clusters |
| `concentrate_faults` | fills one spatial neighbourhood, ignoring cluster borders |

**When a head misreports** (`HEAD_FAULT`):

| Rule | Condition |
|---|---|
| `'majority'` | most of its cluster is degraded. The 0.5 threshold is the **breakdown point of the median** the head reports, and it is measured rather than asserted (§7) |
| `'own'` | the head's own oscillator is degraded |
| `'both'` | either, one rule that covers both an individually degraded head and a degraded cluster, so every figure can run under the same rule |

## 3. Measurement: two-way exchange

Members exchange timestamps with their head by TWTT. **The symmetric part of the delay cancels in
the round trip**; only the asymmetry survives, and halved (`blt_links.twoway_sigma_s`).

What is left: timestamp quantization (100 MHz counter, 10 ns LSB), 3 ns of jitter, and 5 cm of path
asymmetry. A member several hops from its head accumulates independent errors at each hop, so the
term grows as **√hops**.

The ISL link model is on, so an exchange fails with distance. A member not heard from in a round
enters neither the aggregation nor the correction, it is absent, not assumed.

Collection takes time: 683 members over two ISL terminals at a 16.7 ms round trip is about 5.7 s,
which is what the 6 s cycle has to accommodate.

What the head does with that time is a choice the engine exposes. By default, and in every result
here, it reads every member's clock at one instant (`LOCAL_COLLECT_WINDOW = 0`). Setting the window
instead takes **each member's value as of when that member answered**, so a different amount of
staleness is mixed into each cluster. Turning it on leaves BLT-SAND unmoved, because a median
ignores a symmetric perturbation, and improves ATS, because staleness understates a fast drifter
that a mean would otherwise chase. It is off so that neither effect is folded silently into a
headline.

## 4. Local phase: cluster aggregation

`main_all.sync_local_robust`

1. The head collects its members' values, exchange noise included.
2. It takes the **median**, and discards anything beyond **MAD × 1.4826 × 3**.
3. The **median of what remains** is the cluster reference.
4. Members are corrected toward it.

A minority of degraded members is absorbed here. Once a majority is degraded, the median itself
moves and the head emits a wrong reference, which is §1's point about selection, seen from the
other side.

**The ledger record is produced here.** Each member's residual against the cluster reference is
accumulated as an exponential moving average (decay 0.7, so an effective memory of 3.3 rounds).
When head selection is `'history'`, this is the record it reads. The memory is deliberately short:
a long one keeps condemning a satellite that has recovered, which is what the intermittent-fault
experiment is about.

## 5. Global phase: consensus among heads

`main_all.sync_with_cluster_bc_vec`

1. The twelve heads each report their cluster reference. A degraded head reports an anomalous
   reading of about 165 ns (`FAULTY_REPORT_ERROR`, the degraded oscillator's drift over one
   local cycle). How far several wrong heads agree with each
   other is set by `FAULT_CORRELATION`.
2. **The proposer is fixed by round number** (`round_no % 12`), not chosen by value. A satellite
   cannot become proposer by reporting something extreme.
3. Each head votes for the proposal if it is within **18 ns** (`BC_AGREE_TOL`, 3 sigma on the
   spread of healthy heads) of its own reference.
   A head the proposal did not reach abstains, and the quorum is counted against all twelve.
4. **Two thirds commit.** What commits is **the proposal itself**, not an average of the voters, so
   a value that failed the vote does not leak into the result through an aggregate.
5. The committed value propagates over the head network, per-hop delay included, and every satellite
   corrects to it.
6. If the quorum is missed, nothing commits and the proposer is not replaced; the round is skipped.
   With `FAILED_ROUND_FALLBACK` on, the heads instead reconcile toward the **median of the reports**
   which is what the same hierarchy would do with no consensus at all, so the comparison past the
   bound stays meaningful.

**Where the 1/3 bound comes from.** An honest proposal is supported only by honest heads, so it
commits while the wrong heads are under 1/3. A wrong proposal is supported only by wrong heads, so
it commits only past 2/3. Between those, nothing commits. The bound is a property of the quorum
rather than a number asserted about the design.

## 6. What it is compared against

Same engine, same seeds, same clustering, same cycles, same links, same noise. Only the named thing
differs.

| Arm | Local | Global |
|---|---|---|
| **BLT-SAND** | median + MAD filter | propose, vote, commit on quorum |
| Same hierarchy, no vote | same | the proposal is distributed unverified |
| BLT-SAND without the ledger | same, but the record is not read | same |
| **ATS** | plain mean of the members | heads reconcile by averaging, no verification |
| **FTSP** | none | one reference flooded hop by hop, 0.45 s period |

The second row is the one that isolates consensus: everything else about the design is held fixed
and only the quorum is removed. Comparing against ATS does not isolate it, because ATS differs in
its aggregation and its correction strength as well.

## 7. The fault constants

| Constant | Value | Basis | Weakness |
|---|---:|---|---|
| `majority_frac` | 0.5 | The head reports its cluster's **median**, and a median breaks down once more than half its input is corrupted. Measured with `experiments/faults/median_breakdown.py`: reference error 0.13 ns at 40% degraded, 0.34 at 50%, 2.74 at 60%, 11.0 at 70%, while the share the filter discards peaks at 38% at the 50% mark and falls after, the degraded side has become the majority and healthy members start being thrown out | A step is an approximation; the real transition is gradual across 45–60% |
| `FAULTY_REPORT_ERROR` | 165 ns | The anomalous reading of a degraded satellite, sensor noise, a bad timestamp, a disturbed link. The degraded oscillator drifts this far over one local cycle | It exceeds the 18 ns agreement window, so it is always caught. The sensitivity to a lie *smaller* than the window has not been measured |
| `BC_AGREE_TOL` | 18 ns | Derived at 3σ from the spread of healthy heads (`blt_params.agree_tol_s`) | 3σ is a convention |
| `FAULT_CORRELATION` | full, or a stated ρ | Satellites in one orbital plane share an eclipse cycle; a production batch ages alike; a region delivers similar radiation dose. They err in the same direction without anyone colluding | Swept, not fixed |
| `MEAS_OUTLIER_P`, `MEAS_BIAS_S` | off by default | For the faulty-measurement experiment only |, |

## 8. Metrics

| Metric | Definition | Used for |
|---|---|---|
| **Relative RMSE** | RMSE of the nominal satellites about their own mean, per tick | the headline; every accuracy claim |
| Absolute RMSE | the same satellites against true time | recorded, not used as an axis |
| Commit rate | committed rounds / all rounds | availability |
| Wrong commit | rounds committed while the proposer was a misreporting head | what the vote contributes |
| Adopted reference error | \|committed value − mean of the honest clusters' references\| | correlated-fault figures; an internal reference, not true time |
| Common-time drift | slope of (nominal-satellite mean − true time), in ppb | the timescale figure, in the same unit as an oscillator spec |

Why relative: the claim is inter-satellite time, which is what pointing, acquisition and tracking
need. [`MODEL.md` section 1b](MODEL.md#1b-the-metric-nominal-satellites) says why the nominal
satellites and not all of them.

## 9. Running it

[`REPRODUCING.md`](REPRODUCING.md) lists every driver against the question it answers and the
file it writes. What follows is what a reader of this document needs to know about running it.

- Every driver calls `blt_config.apply(main_all)`. Passing a seed fixes both the oscillator draw and the
  fault placement, so two schemes run from **identical initial conditions**, which is what lets a
  difference be attributed to the mechanism rather than to the draw.
- The default run is 40 s (40,000 ticks) and steady state is the mean of the last quarter. The
  timescale-drift experiment runs ten minutes.
- **Run length interacts with proposer rotation.** The proposer is `round % 12` and a global round
  is 6 s, so a 40 s run has only six or seven rounds and **only half the heads ever propose**. A
  wrong head late in the rotation never gets a turn, and the run reports "0% wrong commits" for a
  reason that is about the run length. Experiments measuring how often consensus adopts a wrong
  value therefore run **150 s (25 rounds)**. Accuracy comparisons stay at 40 s; at 150 s the
  satellites have moved further and relative RMSE rises from 8.8 to about 9.0 through accumulated
  re-clustering and migration.
- **The first global round is excluded from the diagnostics.** No satellite has a ledger record yet,
  so heads are chosen without regard to health. With 40% of satellites degraded and scattered, eight
  of twelve heads came out degraded in that round and filled a 2/3 quorum among themselves, which
  is outside the regime the bound describes, and is a property of the cold start rather than of the
  consensus.
- After any change to the engine, run `python BLT_simul/tools/verify_units.py` and
  `python BLT_simul/tools/verify_engines.py`, which check the units and the wiring. With the
  switchable effects off the engine must stay **bit-identical**, and that is established by
  re-running a driver and comparing its CSV, not by either tool.
