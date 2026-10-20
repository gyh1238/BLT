# The model: configuration, parameter provenance, and sensitivity

Everything the simulation depends on is a named parameter in `BLT_simul/model/blt_params.py`, and
every one of them carries its kind, its credible range, and the sentence that justifies it. This
document says what the adopted configuration is, what the accuracy metric means, which assumptions
the result is sensitive to, and what the model does not cover.

`python BLT_simul/model/blt_params.py` prints the whole registry. This document summarises it; the registry
is the authority, because it is what the code reads.

**Contents**
[1. The adopted configuration](#1-the-adopted-configuration) ·
[1b. The metric](#1b-the-metric-nominal-satellites) ·
[2. The schemes being compared](#2-the-schemes-being-compared) ·
[3. Where the parameter values come from](#3-where-the-parameter-values-come-from) ·
[4. Sensitivity](#4-sensitivity) ·
[5. Verification](#5-verification) ·
[6. What the model does not include](#6-what-the-model-does-not-include)

---

## 1. The adopted configuration

There is exactly one configuration. Every figure, table and number in this repository was produced
under it, and `BLT_simul/model/blt_config.py` applies it in one call, a script does
`blt_config.apply(main_all)` and gets all of it. Nothing else is switched on anywhere:
if a caption does not say that it changed something, this is what ran.

Two of those settings cost BLT-SAND accuracy rather than buy it: the link model and the
measurement noise are both on, and each only adds error. A third favours a baseline: FTSP re-floods
13× more often than BLT-SAND commits, which gives every relay a fresher reference.

| | Value | Why this value |
|---|---|---|
| Satellites / clusters | 8,192 / 12 (about 683 each) | The paper's design point; real Starlink TLEs give the geometry |
| ISL range | 2,500 km | 2.5 W, 1,550 nm, 20 µrad beam divergence |
| Local cycle | 6 s | A head polls 683 members over two ISL terminals in 5.69 s (§6) |
| Global block interval | 6 s | Set equal to the local cycle; the two were swept apart to check |
| Healthy oscillator | 1 ppb | Disciplined-oscillator spread; 1 ppb is 1 ns/s |
| Degraded oscillator | 27.5 ppb spread + 19 ppb bias | Ageing of ±30 ppb/year left uncorrected for most of a year |
| Degraded fraction | 5% (headline); swept 0–50% | |
| Timestamping | 100 MHz counter (10 ns LSB) + 3 ns jitter | A general counter synthesised from a 10 MHz oscillator |
| FTSP re-flood | 0.45 s | 13× more often than BLT-SAND commits. Matching the two cadences would make FTSP worse, since re-flooding often is what gives each relay a fresh reference |
| Quorum | 2/3 of the twelve heads | Classical PBFT, 2f+1 of 3f+1 |
| ISL link model | on | Distance-dependent outage, acquisition delay, relay routing |
| Measurement noise | on | Timestamp error per member exchange, growing with √hops |
| Warm-started clusters | on | Re-clustering continues from the previous centroids |

## 1b. The metric: nominal satellites

RMSE is reported over the **nominal** satellites, those whose oscillators were not degraded, and
against the mean of those same clocks.
The alternative, averaging over all 8,192 including the degraded ones, is also computed and
recorded in the same CSV, and the two differ a lot:
8.79 / 14.55 / 17.07 ns over the nominal satellites against 22.24 / 31.02 / 17.35 over all of them.

The gap is the degraded oscillators' own clocks, and it is not something a protocol can close. A
satellite whose oscillator is 27.5 ppb wide accumulates error locally between corrections, so an
all-satellite average measures how hard the fault injection was turned up as much as it measures the
protocol. The clearest sign of that is FTSP, which barely moves between the two metrics
(17.07 → 17.35) because its own error already exceeds what the degraded satellites contribute, while
the other two jump.

The claim is also about relative time, what one satellite's clock reads against its neighbour's,
which is what pointing needs, and a degraded satellite is not a satellite anyone is trying to point
at. `blt_core.py` computes both, `tools/verify_units.py` checks that the relative metric is blind to
a common-mode shift while the absolute one is not, and both columns are written out, so the choice
is visible rather than implied.

## 2. The schemes being compared

Three schemes run on the same engine, the same seeds, the same clustering and the same links. They
differ in how a cluster's members are combined and in how that result reaches the rest of the
constellation, and that is where their errors separate.

| | Local | Global | Where its error comes from |
|---|---|---|---|
| **BLT-SAND** | median, then a MAD filter | propose, vote, commit on a quorum | drift between rounds, plus the timestamp error of one two-way exchange. Outliers are removed before they reach the cluster reference |
| **ATS** | mean | heads reconcile by averaging, unverified | the same two terms, but a degraded member is diluted rather than removed, so a one-directional bias pulls the cluster reference with it |
| **FTSP** | none | one reference flooded hop by hop | each relay adds its own timestamping error to everything behind it, so the error accumulates along the flooding path instead of being bounded by a cluster |

Two consequences follow from that last column and are worth stating before the results.

**A filter bounds an error; an average spreads it.** BLT-SAND and ATS see the same measurements. The
difference is that a median with a MAD filter discards a report that disagrees with the cluster,
while a mean keeps a fraction of it. That costs nothing while degraded members are a minority and
everything once they are not, which is why the fault *placement* matters more than the fault
fraction ([`FIGURES.md` §4.1](FIGURES.md#41-where-the-faults-sit-and-what-that-does-to-the-agreed-time)).

**A flood cannot get below its own path.** Most of FTSP's error is the one-way timestamp budget
accumulated over the hops a reference crosses, and that is set by the path, not by how often the
reference is sent. Flooding more often does cut the drift that accrues between floods, so the error
does fall, but onto that floor: from a 0.1 s cycle out to 6 s it moves only between **17.3 and
18.5 ns**, so no flood rate meets the 10 ns requirement.

## 3. Where the parameter values come from

Every physical assumption in the engine is a registry entry carrying its value, its kind and the
source behind it. [`REFERENCES.md` §7](REFERENCES.md#7-every-parameter-against-its-source) is the
complete list; `python BLT_simul/model/blt_params.py` prints the same thing with each entry's
credible range, and `BLT_simul/tools/verify_units.py` checks that a value computed from others
names the helper that computes it.

## 4. Sensitivity

Each assumption was swept across its credible range, five values each, and the result measured
(`BLT_simul/result/sensitivity.csv`). Two things the sweep shows are worth stating before the
results.

**The result is sensitive to the fault model and to the timestamping, in that order.** Nothing else
reaches the output at a comparable scale: a delay, for instance, reaches it only as skew × hop
delay, which is 8 ps at 1 ppb over an 8.4 ms hop.

**The oscillator assumptions act on different schemes.** The healthy spread moves BLT-SAND and ATS
together, because both are bounded by how far a healthy clock drifts between corrections. The
degraded bias moves **ATS alone**, a one-directional bias survives a mean but not a median, and the
flooding path never sees it. That asymmetry is worth knowing before reading either curve.

Being fixed by a datasheet does not make an assumption inert. One ppb of healthy oscillator spread
moves BLT-SAND by 6.6×, and that figure is a hardware specification: how well a value is pinned and
how much it matters are different questions.

**The ordering BLT-SAND < ATS < FTSP held at all 70 measured points.**

## 5. Verification

| Check | What it covers |
|---|---|
| `python BLT_simul/tools/verify_units.py` | Units and metrics: the relative RMSE is blind to a common-mode shift while the absolute one is not, derived parameters match their formulas, the ISL outage law matches both its closed form and a Monte Carlo pointing fade, routing depth and reachability are consistent |
| `python BLT_simul/tools/verify_engines.py` | One engine, not a fork; the parameters actually bind onto it; the proposal is fixed by rotation rather than derived from the values; the committed value is the proposal itself with no aggregate surviving in the commit path; the quorum is the classical PBFT 2/3 |
| `python BLT_simul/tools/isl_parity.py` | The Unity C# ISL model equals the Python one |

Every engine toggle defaults to **off**, and off is bit-identical to the engine without it,
`verify_engines` reads the engine source for this. It does not run a simulation, so an edit that
changes the numbers is caught by re-running a driver and comparing its CSV, not by this check.

The ISL parity check compiles `BLT_dt/Assets/Scripts/IslLinkModel.cs` with the Roslyn compiler inside
a Unity editor and compares it against `BLT_simul/model/blt_isl.py` on the same constellation:

| | N = 500 | N = 8,192 |
|---|---|---|
| Outage exponent | identical | identical |
| Max difference in outage probability | 0.0e+00 | 0.0e+00 |
| Link set | 4,725 = 4,725 | 1,301,382 = 1,301,382 |
| Routable / unroutable members | 488 / 0 | 8,180 / 0 |
| Mean hops to the head | 2.150 = 2.150 | 1.975 = 1.975 |
| Expected path loss | 0.00254 = 0.00254 | 0.00155 = 0.00155 |

## 6. What the model does not include

Stated so that a reader does not have to infer it from absence.

- **Malicious behaviour.** The fault model is benign: an oscillator degrades and its satellite keeps
  reporting what it believes. Nothing lies on purpose, forges a signature or withholds a message.
  What makes the vote necessary is not malice but *correlation*, radiation is regional and a cluster
  is a region, so several heads err alike and alike-erring is what collusion looks like to a vote.
- **Absolute time.** The claim is relative, inter-satellite time, which is what pointing,
  acquisition and tracking need. The constellation's common timescale does drift against true time,
  and the ablation table in [`FIGURES.md` §3.1](FIGURES.md#31-the-ablation-as-one-table) reports
  how fast: 0.04 ppb as designed, 8.08 ppb with the vote removed under regional faults.
- **Doppler.** A two-way exchange cancels the symmetric delay, so only the forward/return asymmetry
  survives, and at 1 m/s of velocity knowledge the residual is under 20 ps, three orders of
  magnitude below the timestamping term. It is not in the model.
- **Atmospheric and weather effects on the ISL.** The links are satellite-to-satellite above
  100 km of grazing altitude, so the beam does not traverse weather; the grazing-altitude parameter exists
  so that lower shells break correctly rather than because it is active at 550 km.
- **Ground segment.** There is no ground station, no uplink and no external time reference. That is
  the point of the design, but it also means the model cannot speak to hybrid operation.
- **Pointing jitter has no cited source**, and unlike the other assumptions it changes the answer.
  `isl_pointing_jitter_rad` is 2 µrad by assumption, and doubling it is measured rather than argued
  about (`experiments/scale/isl_link_run.py`, 4 seeds, 5% degraded, everything else held):

  | N | Links | BLT-SAND | ATS | FTSP | Commit rate | Mean hops to head |
  |---:|---|---:|---:|---:|---:|---:|
  | 8,192 | ideal | 6.62 | 13.51 | 16.74 | 100% |, |
  | 8,192 | model, 2 µrad (adopted) | **8.80** | 14.74 | 16.62 | 100% | 1.98 |
  | 8,192 | model, 4 µrad | **14.31** | 19.14 | 16.69 | 96% | 5.51 |

  Going from ideal links to the adopted model costs BLT-SAND 6.6 → 8.8 ns, and that is the relay
  hops: a member reaching its head over two hops carries two exchanges' worth of timestamp noise.
  **Doubling the jitter takes it past the requirement**, 14.3 ns, because members route around the
  short links that now fail and the mean hop count rises to 5.5. The ordering BLT-SAND < ATS holds
  throughout; at 4 µrad BLT-SAND and FTSP converge. So the assumption matters, and it is published
  with its sensitivity rather than stated and left alone.
