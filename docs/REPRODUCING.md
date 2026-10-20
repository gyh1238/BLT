# Reproducing the evaluation

Every number quoted in the paper, the top-level README and [`FIGURES.md`](FIGURES.md) comes from one
of the commands below: a driver writes a CSV or a chain log, and the figure code reads it. [`SIMULATION.md`](SIMULATION.md) explains what the simulation does, [`MODEL.md`](MODEL.md)
what its parameters are and where they come from.

**Contents**
[1. Installing](#1-installing) ·
[2. The simulation drivers](#2-the-simulation-drivers) ·
[3. The chain measurements](#3-the-chain-measurements) ·
[4. Rendering the figures](#4-rendering-the-figures) ·
[5. Checking a change](#5-checking-a-change)

---

## 1. Installing

```bash
pip install numpy scipy scikit-learn pandas geopy skyfield matplotlib requests
```

Go 1.25, as `BLT_bft_chain/go.mod` pins, and `make` are needed for the chain; see [`../BLT_bft_chain/readme.md`](../BLT_bft_chain/readme.md).
The constellation comes from real Starlink two-line element sets, which are not redistributed here;
[`../BLT_simul/data/README.md`](../BLT_simul/data/README.md) says how to obtain them. **The file is
required**: with no `BLT_simul/data/STARLINK_TLE.txt` every driver stops before it simulates
anything. If the file holds fewer than the 8,192 the run asks for, the engine completes the rest by
rotating satellites already in the set, which the data readme describes.

Every script under `BLT_simul/` finds that directory itself, so it runs from any working directory
and its inputs and outputs always resolve against `BLT_simul/` rather than against where it was
invoked.

## 2. The simulation drivers

Each driver states its question, its design and its run command in its own docstring. All of them
run at N = 8,192 under the adopted configuration. Long sweeps take `--jobs` and filter flags
(`--nc`, `--t`, `--fault`, `--axis`, `--sizes`, `--arms`), so a sweep can be split across processes
and merged.

Three of these need options the defaults do not give, because the panel they feed is not the
quick run. Every driver chdirs to `BLT_simul/` before it starts, so `--out` is relative to that
directory however the script was invoked:

```bash
# accuracy time series, 8 seeds at every tick
python BLT_simul/experiments/accuracy/timeseries.py --seeds 8 --stride 1

# the head-fault axis, with the failed-round fallback the panel is drawn under
python BLT_simul/experiments/faults/fault_axes.py --axis head --seeds 8 --fallback

# the timestamp-jitter sweep at the adopted operating point: 8,192 satellites,
# 8 seeds, measurement noise on, one row per jitter value
mkdir -p BLT_simul/result/fit
python BLT_simul/experiments/accuracy/sensitivity_sweep.py \
  --n 8192 --seeds 8 --healthy 1 --faulty 27.5 --bias 19 --flood 450 \
  --lsb 1e-8 --jitter 2e-9,2.5e-9,3e-9,3.5e-9,4e-9 \
  --out result/fit/jitter_sweep.csv
```

| Script | Question it answers | Output (`BLT_simul/result/…`) |
|---|---|---|
| `accuracy/timeseries.py` | Accuracy time series of the three schemes and no-sync (8 seeds, per tick) | `runs/timeseries.csv` |
| `accuracy/sensitivity_sweep.py` | What each oscillator, aggregation and ranging parameter reaches; `--jitter` sweeps the timestamp counter | `fit/sweep_*.csv`, `fit/jitter_sweep.csv` |
| `accuracy/effect_budget.py` | Each modelling effect measured on its own, as an error budget | `fit/effect_budget.csv` |
| `faults/fault_axes.py` | Member faults (scattered) vs cluster-head faults (whole clusters) | `runs/fault_axes_*.csv` |
| `faults/measurement_faults.py` | Outlier and biased measurements | `runs/measurement_faults.csv` |
| `faults/correlated_faults.py` | Scattered vs regional vs whole-cluster faults; correlated vs independent misreports; per-round vote records | `runs/correlated_faults_*.csv` |
| `faults/fault_concentration.py` | How a fault placement fills individual clusters | `runs/fault_concentration.csv` |
| `faults/median_breakdown.py` | Where the median the head reports breaks down as its cluster fills with degraded members | printed; quoted in `SIMULATION.md` |
| `faults/intermittent_faults.py` | Intermittent degradation: full history vs latest round vs none | `runs/intermittent_faults.csv` |
| `ledger/ablation.py` | Remove the filter, the vote or the global phase, as sweeps | `runs/ablation.csv` |
| `ledger/ablation_ladder.py` | The same removals as one table, one operating point per fault condition | `runs/ablation_ladder.csv` |
| `ledger/ledger_history.py` | Choosing heads from recorded precision vs no ledger | `runs/ledger_history.csv` |
| `ledger/cluster_migration.py` | How fast cluster membership turns over, and where the record has to live | `runs/cluster_migration*.csv` |
| `ledger/timescale_drift.py` | How far the common time walks from true time under wrong commits | `runs/timescale_drift.csv` |
| `design/cycle_sweep.py` | Local and global cycle swept separately | `runs/cycle_sweep.csv` |
| `design/collection_time.py` | Member collection time per cluster count, from the orbit geometry and link routes | `runs/collection_time.csv` |
| `design/deployment_grid.py` | Cluster count × block interval (Fig. 4(d)); `--local-equals-block` is the adopted model | `runs/deployment_grid_block*.csv` |
| `design/comm_periods.py` | Longest cycle meeting 10 ns per scheme (Fig. 4(c) message rates) | `runs/comm_periods.csv` |
| `scale/isl_link_run.py` | Ideal links vs the link model vs softer pointing | `runs/isl_link_run.csv` |
| `scale/scale_run.py` | N = 500 vs N = 8,192 head-fault curves | `runs/scale_run.csv` |

A sweep at N = 8,192 over many seeds is hours of CPU. `--jobs` is the first thing to set.

## 3. The chain measurements

These run a real CometBFT testnet, not a simulation of one.

```bash
mkdir -p BLT_simul/result/chain
N=12 K=10 TAMPER=1 RECOVERY=1 CROSS=1 bash BLT_bft_chain/scripts/chain_scale.sh \
  | tee BLT_simul/result/chain/chain_n12_full.log
```

`N` is the validator count and `K` the number of synchronization epochs to measure, not the cluster
count. The script writes its summary to standard output, so redirect it to the path the figure code
reads.

| Part | What it does |
|---|---|
| A | Latency, block size, CPU, memory and bandwidth at N validators |
| B | Attempts tampering: rewind, replay, forged time, duplicate head, non-delegate proposer |
| C | Disconnects a node, lets the chain advance, measures what rejoining costs |
| D | Cross-cluster consistency: summaries that contradict the block's own tables |

Validators run as native `leochaind` processes on one host rather than in containers, so the CPU,
memory and p2p figures belong to the process itself rather than to a runtime around it. The figure
code reads the log from `BLT_simul/result/chain/`, which is why the command above redirects there.

`N` was measured at 4, 8, 12 and 16. The scripts report
sizes in KiB because that is what the counters give; everything shown in the figures and documents is
SI, converted in one place.

## 4. Rendering the figures

```bash
python BLT_simul/figures/evaluation_panels.py   # -> BLT_simul/result/evaluation/
```

This writes the twenty panels of [`FIGURES.md`](FIGURES.md) as PNG and vector PDF.

It simulates nothing. A missing CSV or chain log skips its panel and is listed at the end of
the run, so a partial reproduction still renders what it has.

## 5. Checking a change

```bash
python BLT_simul/tools/verify_units.py     # every parameter has a unit, a source and a range
python BLT_simul/tools/verify_engines.py   # one engine, parameters bound, the vote is a vote
python BLT_simul/tools/check_doc_links.py  # every image path and anchor in the markdown resolves
```

`verify_engines.py` reads the engine rather than running it. It checks that the four schemes share
one implementation instead of having been forked, that every parameter the profiles name is
actually bound onto the module, and that the global phase is a proposer-and-voters round whose
failed-round branch writes nothing to the ledger. It does not execute a simulation, so it cannot
tell you that an edit left the numbers alone; for that, run a driver before and after and compare
the CSV.

`tools/isl_parity.py` checks that the Unity link model and the Python one agree; it compiles a file
from `BLT_dt/` and is the only script that reaches outside its own component.
