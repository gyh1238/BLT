# BLT_simul, the simulator

The constellation-scale evaluation: 8,192 satellites, their clocks, the two-phase synchronization
and the two benchmark protocols it is measured against. Everything in §IV of the paper that is not
the real chain or the Unity scene is produced here.

This is a *simulation of the protocol*, not of the blockchain. The consensus among cluster heads is
modelled as propose–vote–commit with a quorum; what a real CometBFT deployment costs to run that is
measured separately in [`../BLT_bft_chain/`](../BLT_bft_chain).

## Layout

```
model/          the engine; every script imports it flat (`import main_all`)
experiments/    one driver per question, grouped by the question
  accuracy/     what the schemes reach, and what each assumption is worth
  faults/       the three fault axes and how faults are placed
  ledger/       what the vote and the recorded history each contribute
  design/       cadence, cluster count, collection time, message rate
  scale/        link model and constellation size
figures/        fig_style.py and the evaluation panels
tools/          verification, Unity/Python ISL parity, the live state server
data/           TLE input, not redistributed, see data/README.md
result/         outputs, written by the scripts; not tracked
```

### The engine

| File | What it holds |
|---|---|
| `main_all.py` | The simulation loop and the four arms: `simulate_bc`, `simulate_cluster` (ATS), `simulate_ftsp`, `simulate_none` |
| `blt_core.py` | Clocks, oscillator draw, fault masks, the per-tick error step |
| `blt_params.py` | Every physical assumption as a registry entry with a unit, a source and a range |
| `blt_links.py` | The two-way exchange error budget: what cancels in a round trip and what does not |
| `blt_isl.py` | Distance-dependent ISL availability, pointing, divergence, range limit |
| `blt_config.py` | The adopted settings in one call: `blt_config.apply(main_all)` |
| `engine_profiles.py` | Named parameter sets for the comparison arms |
| `function_get_tle.py` | Reads the element file (any line ending, name lines allowed) and completes a short one |

Two things to know before changing anything here.

**Every assumption is registered.** `blt_params.py` holds each one as an entry: a value, its unit,
whether it is physical, design or derived, a plausible range, and the source behind it. An entry
computed from others must name the helper that computes it, which `tools/verify_units.py` enforces,
so a value and its formula cannot drift apart.

**Switchable effects must be free when off.** The link model, measurement noise, the collect window
and the warm-started clustering can each be turned off, and with all of them off the engine must
produce the error series it produced before any of them existed. `tools/verify_engines.py` checks
the wiring that this rests on, that there is one engine and that each toggle is read where it
should be; it reads the source and does not run a simulation, so confirming that an edit left the
numbers alone means re-running a driver and comparing its CSV.

### The switchable effects

All of these are off by default, and off is bit-identical to the engine without them:

| Option | Effect when on |
|---|---|
| `ISL_LINK_MODEL` | Distance-dependent link outage; members reach their head over 1-3 relay hops |
| `LOCAL_MEASUREMENT_NOISE` | Timestamp error on every member exchange, growing with the square root of the hop count |
| `CLUSTER_WARM_START` | Re-clustering continues from the previous centroids instead of starting over |
| `LOCAL_COLLECT_WINDOW` | Collection staleness |

Further hooks cover head-selection policy (`HEAD_POLICY`), the head fault rule (`HEAD_FAULT`),
measurement outliers and bias (`MEAS_*`), intermittent faults (`FAULT_SCHEDULE`) and correlated
misreports (`FAULT_CORRELATION`).

`model/blt_config.py` holds the configuration. There is only one, every result here was produced
under it, and `blt_config.apply(main_all)` applies all of it: healthy oscillator 1 ppb, degraded
27.5 ppb spread with 19 ppb bias, local and global cycle 6 s, FTSP re-flood 0.45 s, 100 MHz counter
timestamps with 3 ns jitter, and the link model, measurement noise and warm-started clusters on.

After any change to the engine:

```bash
python tools/verify_units.py && python tools/verify_engines.py
```

These check the units, the metrics, the registry wiring, the ISL model and the vote rule. They read
the engine rather than running it, so they do not establish that the numbers are unchanged; for
that, re-run a driver and compare its CSV against the one before the edit.

---

### Writing a new script

Copy the bootstrap block from any existing driver. It climbs until it sees `model/`, puts `model/`
and `figures/` on the import path, and chdirs there. That is why imports are flat and why `data/`
and `result/` resolve against this directory rather than against wherever the script was invoked.

## Running it

[`../docs/REPRODUCING.md`](../docs/REPRODUCING.md) lists every driver, what it answers and what it
writes. The short version:

```bash
pip install numpy scipy scikit-learn pandas geopy skyfield matplotlib requests
python experiments/accuracy/timeseries.py          # a driver; --jobs splits a long sweep
python figures/evaluation_panels.py                # every panel in docs/FIGURES.md
python tools/verify_units.py && python tools/verify_engines.py
```

Each driver's docstring states its question, its design and its own run command. A sweep at
N = 8,192 over many seeds is hours of CPU, so `--jobs` is the first flag to set.

## Where the explanations are

| | |
|---|---|
| [`../docs/SIMULATION.md`](../docs/SIMULATION.md) | What the simulation does, step by step |
| [`../docs/MODEL.md`](../docs/MODEL.md) | The configuration, the metric, and what moves the result |
| [`../docs/REFERENCES.md`](../docs/REFERENCES.md) | Each assumption against the measurement behind it |
| [`../docs/FIGURES.md`](../docs/FIGURES.md) | The twenty evaluation panels, with their numbers |
| [`../docs/REPRODUCING.md`](../docs/REPRODUCING.md) | Every command that produces a result |
