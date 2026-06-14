# BLTi-SAND Simulator

**Balanced Lightweight Time Synchronization for Autonomous Networked Devices**

A clock-synchronization simulator for LEO satellite constellations (Starlink-based).
It compares three time-synchronization algorithms — **FTSP**, **ATS** (cluster
averaging), and **BLT-SAND** (the proposed hierarchical-PBFT protocol) — under
both normal and partially faulty satellite conditions, and reproduces the four
evaluation panels of the paper.

## Requirements

```bash
pip install numpy scipy scikit-learn pandas geopy skyfield matplotlib
```

## Reproducing the figures

Each panel is produced by a standalone driver that runs the simulation (or the
analytical model) and writes a CSV into `result/`. `make_figures.py` then reads
those CSVs and renders the figures. Run the drivers first, then the renderer:

```bash
python synchronization_accuracy.py   # → result/synchronization_accuracy_time_series.csv
python fault_tolerance.py            # → result/fault_tolerance_sweep.csv
python communication_efficiency.py   # → result/communication_efficiency.csv   (analytical)
python deployment_flexibility.py     # → result/deployment_flexibility.csv      (analytical)
python make_figures.py               # → result/{synchronization_accuracy,fault_tolerance,
                                     #           communication_efficiency,deployment_flexibility}.{png,pdf}
                                     #   + result/combined.{png,pdf}
```

`make_figures.py` only reads the CSVs and applies display-side smoothing
(EMA / shape-preserving PCHIP spline); it does not modify the simulated values,
and each algorithm's curve is plotted at its true amplitude. CSV and image
outputs are not version-controlled (see `.gitignore`); regenerate them with the
commands above.

## Source files

| File | Role |
|---|---|
| `function_get_tle.py` | Loads satellite TLE data |
| `main_all.py` | Simulation engine — fault-sweep model |
| `main_all_panela.py` | Simulation engine — accuracy time series |
| `synchronization_accuracy.py` | Accuracy panel driver → `result/synchronization_accuracy_*.csv` |
| `fault_tolerance.py` | Fault-tolerance sweep driver → `result/fault_tolerance_sweep.csv` |
| `communication_efficiency.py` | Analytical communication-cost model |
| `deployment_flexibility.py` | Analytical feasibility model |
| `fig_style.py` | Shared colors, labels, unit scale |
| `make_figures.py` | Reads the CSVs and renders the figures |

## Satellite data

`function_get_tle.py` provides two TLE sources:

- `get_sat_from_text()` — reads cached TLE from `data/STARLINK_TLE.txt` at a fixed
  epoch (2022-09-02 06:00 UTC). **This is the default used by the simulations.**
- `get_sat_from_spacetrack()` — live fetch from [Space-Track.org](https://www.space-track.org),
  reading credentials from `data/SLTrack.ini`.

`data/SLTrack.ini` contains personal credentials and is **not** included in this
repository. To use the live fetch, create it yourself:

```ini
[configuration]
identity = your-spacetrack-email
password = your-spacetrack-password
```

## Algorithms

- **FTSP (Flooding Time Sync Protocol)** — a single reference floods its clock to
  all satellites hop-by-hop; by-hop error accumulates along the flood paths.
- **ATS (cluster averaging)** — satellites within each K-Means cluster align to the
  intra-cluster average; clusters reconcile toward the global mean. No consensus,
  so faults are diluted but not excluded.
- **BLT-SAND** — hierarchical PBFT: a robust within-cluster median+MAD filter plus
  a cross-cluster quorum that excludes outlier clusters, holding the sync error
  bounded up to the 1/3 Byzantine fault threshold.
