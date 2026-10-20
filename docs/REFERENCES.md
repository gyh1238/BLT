# Where the assumptions come from

Each number the model rests on, against the measurement or specification that backs it. Sections 1
to 6 take the assumptions that need an argument; [§7](#7-every-parameter-against-its-source) is the
complete registry, every value against its source.

Every entry below was checked against the source text rather than against a secondary citation.

---

## 1. Assumptions with a measured counterpart

| Our assumption | What was measured, in orbit or in the lab | Source |
|---|---|---|
| Healthy oscillator 1 ppb | Mean in-orbit OCXO offset **1.6 ppb**; drift "in the order of nanoseconds per second" | Kunzi & Montenbruck, *NAVIGATION* 69(3), 2022 |
| Degraded oscillator in the tens of ppb | Space-grade OCXO **ageing ±30 ppb/year**; short-term σ_y 2.5 / 3.5 / 5 × 10⁻¹³ at 1 / 10 / 100 s, so about 2 ps over a 6 s cycle | Rakon RK409AVNS datasheet |
| Inter-satellite range known to 1 m | Real-time onboard GNSS, **28 cm 3D RMS** | Hauschild & Montenbruck, *NAVIGATION* 68(2), 2021 |
| Timestamping at the nanosecond level | Flight event timer **2.8 ps RMS**; chronometers 10–70 ps | Samain et al., *Metrologia* 51, 2014 |
| Relay processing 100 µs | SpaceWire router 0.69–1.81 µs, jitter 160–800 ns (3σ), **ground measurement** | Terada et al., *JATIS* 4(1), 2018 |
| Two-way optical ISL is precise enough to measure against | BDS-3 ISL over 421 links, **2.5 cm RMS**; ISL clock-difference noise **0.1 ns** | Zhang et al., *Adv. Space Res.* 73, 2024; Liu et al., 2022 |
| A two-way exchange holds between platforms in relative motion | Femtosecond optical two-way time-frequency transfer **with the terminals moving**, demonstrating that the symmetric part of the delay still cancels when the range is changing | Sinclair et al., *Phys. Rev. A* 99, 023844, 2019 |
| Oscillator stability is characterised by the Allan variance over power-law noise | The standard treatment this model's clock terms are drawn from | Rutman & Walls, *Proc. IEEE* |
| Anomalous measurements occur and are removable | Phase jumps coinciding with thruster firings, several per orbit, detectable and removable; re-acquisition < 5 min; 55.5 days uninterrupted | Abich et al., *PRL* 123, 2019 |
| Quorum of 2/3 | PBFT n > 3f, 2f+1; CometBFT "+2/3" | Buchman et al., arXiv:1807.04938; CometBFT v0.38.17 docs |
| Median + MAD filtering of offset reports | "The Median Absolute Deviation (MAD) can indicate gross errors", MAD used for outlier detection in clock-offset preprocessing | Yang et al., *Satellite Navigation* 5:15, 2024 |
| Hierarchical aggregation improves stability | "a time scale algorithm can merge multiple atomic clocks into a virtual atomic clock that exhibits better frequency stability" | Yang et al., 2024 |
| Optical ISL measurement is not limited by the atmosphere | "Future laser intersatellite links are basically not affected by these [ionospheric/tropospheric] errors" | Yang et al., 2024 |

Three of these deserve emphasis because they run **against** the design rather than for it. The
timestamping assumption is about two orders of magnitude worse than flight hardware, so better
hardware only lowers the floor. The range assumption is an order of magnitude looser than measured
onboard GNSS, and it cancels in a two-way exchange anyway. The relay-processing figure is two
orders above the measured router latency, and contributes picoseconds.

## 2. Why the faults are regional

The case for a quorum does not rest on anyone behaving maliciously. It rests on degraded satellites
being **correlated**, and that is a measured property of oscillators in low Earth orbit.

| What is established | The measurement | Source |
|---|---|---|
| Degradation is tied to a region, and recurs on every pass through it | The Jason-2 USO frequency shifts on **every South Atlantic Anomaly crossing** (up to 10 minutes), in proportion to dose rate, recovering logarithmically with a time constant of about 8 minutes | Belli et al., *Adv. Space Res.* 58, 2016; Belli & Exertier, *IEEE TUFFC* 65(10), 2018 |
| It holds across spacecraft, missions and oscillator generations | Radiation effects identified unambiguously on **Jason-1, SPOT-5 and CryoSat-2**, modelled on **Jason-2 and Jason-3**, and measured independently on **Sentinel-3A** | Belli & Exertier 2018; Belli, Exertier & Jayles; Jalabert & Mercier, *Adv. Space Res.*, 2018 |
| Two satellites on one trajectory were observed together | Jason-2 and Jason-3 flew the same trajectory during Jason-3's commissioning, and both oscillators were characterised over it | Belli, Exertier & Jayles |
| The size of the effect is per-unit, not per-region | Jason-1 reached **6 × 10⁻¹¹** peak-to-peak; the pre-irradiated DGXX generation on Jason-2/-3 stays at **a few 10⁻¹²**, and Jason-3 showed twice Jason-2's effect at the same age. "Two satellites with the same SAA area won't necessarily be affected the same way: each USO reacts differently" | Jalabert & Mercier 2018; Belli, Exertier & Jayles |
| Several satellites failing from one common cause is a standard category | ARAIM splits faults into independent per-satellite faults (P_sat) and **constellation faults**, "affecting multiple satellites simultaneously due to a common cause" (P_const), both estimated from three years of Galileo clock and ephemeris errors | R. Wang & T. Walter, *ION ITM*, 2023 |
| LEO radiation risk concentrates in the SAA and at high latitude, and shifts during storms | Single-event-upset rates in LEO analysed through the May 2024 space-weather event | Q. Wu *et al.*, *Space Weather*, 2025 |

**What the model takes from this.** The region sets *when*: satellites crossing together are
disturbed together, on the same passes, and a cluster is a region. The unit sets *how much*: the
same crossing moves two oscillators by different amounts, by a factor of two between sister
spacecraft and by more between generations.

That shape is why correlation is a parameter in the fault model rather than an assumption built
into it. `FAULT_CORRELATION` sweeps how closely degraded heads agree with one another, from
independent to fully correlated, and the results are reported across that axis
([`FIGURES.md` §4.1](FIGURES.md#41-where-the-faults-sit-and-what-that-does-to-the-agreed-time)).
A vote has to hold when several heads are wrong *together but not identically*, which is the case
these measurements describe, so that is the case the evaluation covers.

**The magnitude is set separately.** The radiation signatures above are 10⁻¹² to 10⁻¹¹; the fault
model injects tens of ppb, which is the ageing specification in §1. Radiation gives the timing and
the grouping of a fault; ageing gives its size.

## 3. Comparison protocols

| Scheme | Source | What the source actually says |
|---|---|---|
| **FTSP** | Maróti et al., SenSys 2004 | MAC-layer timestamping with linear regression over eight reference points; root is the lowest ID. Explicitly: it "does not and cannot compensate for the propagation delay", which is why its error accumulates along the flooding path in our model too |
| **ATS** | Yang et al., *Satellite Navigation* 5:15, 2024 | Two-stage autonomous timekeeping for a navigation constellation: four atomic clocks are combined per satellite, then six timekeeping nodes send relative clock offsets over two-way ISL and a compute node forms constellation time by a **stability-weighted average**, broadcast back. Aggregation by weighted averaging with no consensus and no exclusion, which is the structure the ATS arm models |

## 4. Why a decentralized timescale at all

> "from July 12th to 17th, 2019, Galileo experienced a service interruption of **139 h** due to a
> timing facility failure at the ground control center."
>, Yang et al., *Satellite Navigation* 5:15, 2024

A single ground timing facility is a single point of failure, and this is what that looks like in
service. It is the concrete motivation for a timescale that no one node determines.

## 5. The clock model, and what it leaves out

The reference clock model in the literature is

&nbsp;&nbsp;&nbsp;&nbsp;*x*(*t*) = *x*₀ + *y*₀*t* + *Dt*²/2 + ε(*t*)

with power-law noise (random-walk FM, flicker FM, white FM, white PM), characterised by the Allan
variance (Yang et al., 2024).

**This model uses the first two terms only.** Over a 6 s round the quadratic drift *D* and the noise
term ε are negligible against the terms that are kept: an OCXO at σ_y 2.5 × 10⁻¹³ contributes about
2 ps over that interval, against roughly 6 ns from timestamping. Stating it this way makes the
omission a bounded approximation rather than a silence.

## 6. Modelling assumptions in the link layer

Three values in the ISL link model are set by this work rather than taken from a measurement, and
the registry records each as an assumption.

- **Pointing jitter, 2 µrad**, against a 20 µrad beam, a tenth of the beam width, which is the
  regime a terminal has to hold for the link to close at all. It sets how sharply outage rises into
  the range limit, so its effect is swept rather than asserted: at 4 µrad members route around
  short links, the mean hop count goes 2.0 → 5.5, and BLT-SAND goes 8.8 → 14.3 ns
  ([`MODEL.md` §4](MODEL.md#4-sensitivity)).
- **Acquisition time, 30 s.** GRACE-FO re-acquires its laser interferometer in under five minutes
  (Abich et al., 2019) over an inter-satellite range of 220 km; 30 s is the optimistic end for the
  shorter, pre-pointed links modelled here.
- **Grazing altitude, 100 km**, below which a link is considered blocked by the atmosphere. At the
  550 km shell within 2,500 km the limb is about 4,900 km away, so the value is inactive; it exists
  so that lower shells break correctly.

---

## 7. Every parameter against its source

Every physical assumption in the engine is a registry entry with a value, a kind and the source
behind it. `python BLT_simul/model/blt_params.py` prints this with each entry's credible range;
`BLT_simul/tools/verify_units.py` checks that an entry computed from others names the helper that
computes it.

### Oscillator

| Parameter | Value | Kind |
|---|---:|---|
| `osc_nominal_hz` | 40 MHz | design |
| `osc_healthy_ppb` | 1 ppb | physical |
| `osc_faulty_ppb` | 27.5 ppb | design |
| `osc_faulty_bias_ppb` | 19 ppb | design |

### Timestamping, range and relaying

| Parameter | Value | Kind |
|---|---:|---|
| `timestamp_resolution_s` | 10 ns | design |
| `timestamp_jitter_s` | 3 ns | physical |
| `range_uncertainty_m` | 1 m | physical |
| `path_asymmetry_m` | 5 cm | physical |
| `relay_processing_s` | 100 µs | design |
| `faulty_relay_timestamp_error_s` | derived | derived |
| `intercluster_hop_delay_s` | derived | derived |

### Cycles, structure, consensus

| Parameter | Value | Kind |
|---|---:|---|
| `bc_local_cycle_ticks` | 6 s | design |
| `bc_cluster_cycle_ticks` | 6 s | design |
| `ftsp_flood_cycle_ticks` | 0.45 s | design |
| `isl_range_km` | 2,500 km | design |
| `cluster_count` | 12 | design |
| `bc_quorum` | 2/3 | design |
| `agree_tol_sigmas` | 3 | design |
| `ats_reconcile_alpha` | 0.5 | design |
| `neighbour_alpha` | 0.5 | design |

### ISL link model

| Parameter | Value | Kind |
|---|---:|---|
| `isl_divergence_full_rad` | 20 µrad | physical |
| `isl_pointing_jitter_rad` | 2 µrad | design |
| `isl_grazing_altitude_km` | 100 km | design |
| `isl_route_hop_cost` | 0.01 | design |
| `isl_acquisition_s` | 30 s | design |

---

## 8. Sources

Everything cited anywhere in these documents, with its identifier, so a reader can fetch the
original. The PDFs themselves are not redistributed here.

### Oscillators and radiation

| | |
|---|---|
| A. Kunzi and O. Montenbruck, "Precise onboard time synchronization for LEO satellites," *NAVIGATION* 69(3), 2022 | [10.33012/navi.531](https://doi.org/10.33012/navi.531) |
| A. Belli, P. Exertier, E. Samain *et al.*, "Temperature, radiation and aging analysis of the DORIS Ultra Stable Oscillator by means of the Time Transfer by Laser Link experiment on Jason-2," *Adv. Space Res.* 58, 2016 | [10.1016/j.asr.2015.11.025](https://doi.org/10.1016/j.asr.2015.11.025) |
| A. Belli and P. Exertier, "Long-term behavior of the DORIS oscillator under radiation: the Jason-2 case," *IEEE Trans. Ultrason. Ferroelectr. Freq. Control* 65(10), 2018 | [10.1109/TUFFC.2018.2855085](https://doi.org/10.1109/TUFFC.2018.2855085) |
| A. Belli, P. Exertier and C. Jayles, "DORIS-class oscillator under radiations: the Jason family of satellites," *IEEE IFCS*, 2017 | [10.1109/FCS.2017.8088804](https://doi.org/10.1109/FCS.2017.8088804) |
| E. Jalabert and F. Mercier, "Analysis of South Atlantic Anomaly perturbations on Sentinel-3A Ultra Stable Oscillator," *Adv. Space Res.*, 2018 | [10.1016/j.asr.2018.04.005](https://doi.org/10.1016/j.asr.2018.04.005) |
| J. Rutman and F. L. Walls, "Characterization of frequency stability in precision frequency sources," *Proc. IEEE* 79(6), 1991 | [10.1109/5.84972](https://doi.org/10.1109/5.84972) |
| Rakon RK409AVNS, 10⁻⁹ stability class OCXO, datasheet 51003083.110, 2024 | [datasheet](https://www.alldatasheet.com/datasheet-pdf/download/2017584/RAKON/RK409AVNS.html) |

Four of these carry the regional-degradation argument between them, over three spacecraft and two
instrument classes: Jason-2 across repeated SAA crossings, the Jason family as a group, and
Sentinel-3A independently.

### Time transfer and ranging

| | |
|---|---|
| E. Samain *et al.*, "Time transfer by laser link (T2L2): characterization and calibration of the flight instrument," *Metrologia* 51, 503, 2014 | [10.1088/0026-1394/51/5/503](https://doi.org/10.1088/0026-1394/51/5/503) |
| L. C. Sinclair *et al.*, "Femtosecond optical two-way time-frequency transfer in the presence of motion," *Phys. Rev. A* 99, 023844, 2019 | [10.1103/PhysRevA.99.023844](https://doi.org/10.1103/PhysRevA.99.023844) |
| A. Hauschild and O. Montenbruck, "Precise real-time navigation of LEO satellites using GNSS broadcast ephemerides," *NAVIGATION* 68(2), 2021 | [10.1002/navi.416](https://doi.org/10.1002/navi.416) |
| C. Zhang, T. Geng, X. Xie *et al.*, "Analysis of BDS inter-satellite link ranging performance," *Adv. Space Res.* 73, 2024 | [10.1016/j.asr.2024.02.023](https://doi.org/10.1016/j.asr.2024.02.023) |
| K. Abich *et al.*, "In-orbit performance of the GRACE follow-on laser ranging interferometer," *Phys. Rev. Lett.* 123, 031101, 2019 | [10.1103/PhysRevLett.123.031101](https://doi.org/10.1103/PhysRevLett.123.031101) |
| Y. Terada *et al.*, "Time assignment system and its performance aboard the Hitomi satellite," *JATIS* 4(1), 2018 | [arXiv:1712.01484](https://arxiv.org/abs/1712.01484) |

### Synchronization protocols and timekeeping

| | |
|---|---|
| M. Maróti, B. Kusy, G. Simon and Á. Lédeczi, "The flooding time synchronization protocol," *SenSys*, 2004 | [10.1145/1031495.1031501](https://doi.org/10.1145/1031495.1031501) |
| S. Liu, X. Guo, J. Lai and J. Yang, "Distributed timekeeping in BeiDou inter-satellite link network," *IEEE Commun. Lett.* 26(12), 2022 | [10.1109/LCOMM.2022.3198986](https://doi.org/10.1109/LCOMM.2022.3198986) |
| S. Yang *et al.*, "Long-term autonomous time-keeping of navigation constellations based on sparse sampling LSTM algorithm," *Satellite Navigation* 5:15, 2024 (open access) | [10.1186/s43020-024-00137-6](https://doi.org/10.1186/s43020-024-00137-6) |

### Consensus

| | |
|---|---|
| E. Buchman, J. Kwon and Z. Milosevic, "The latest gossip on BFT consensus," 2018 | [arXiv:1807.04938](https://arxiv.org/abs/1807.04938) |
| E. Buchman, "Tendermint: Byzantine fault tolerance in the age of blockchains," M.A.Sc. thesis, Univ. Guelph, 2016 | [hdl:10214/9769](http://hdl.handle.net/10214/9769) |
| CometBFT v0.38 documentation | <https://docs.cometbft.com/v0.38/> |

### Fault modelling

| | |
|---|---|
| R. Wang and T. Walter, "Characterization and comparison of Galileo and GPS anomalies," *ION ITM*, 2023 | [10.33012/2023.18679](https://doi.org/10.33012/2023.18679) |
| Q. Wu *et al.*, "Analyzing SEU rate in LEO satellites during the space weather event of May 2024," *Space Weather*, 2025 | [10.1029/2025SW004608](https://doi.org/10.1029/2025SW004608) |
