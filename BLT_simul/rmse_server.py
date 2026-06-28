"""Real-time BLT-SAND network-RMSE server for the Unity digital twin.

Runs the BLT-SAND synchronization simulation (the same machinery as
synchronization_accuracy.py / main_all_panela.simulate_bc) LIVE, stepping in
wall-clock time, and serves the current network RMSE over a tiny HTTP endpoint.
The Unity DT (SimulationRmseSource.cs, "Auto" mode) polls it; when this server
is not running the DT falls back to the static StreamingAssets playback file.

Why this works in real time: the per-tick step is fully numpy-vectorized, so a
60000-tick run completes in well under a second. The challenge is the opposite
of "too slow" — we deliberately PACE it to wall-clock time (1 tick = 1 ms, so a
6000-tick cluster cycle takes 6 real seconds, exactly like the paper figure).

The served value uses the same transform as the published Fig. 5a curve
(raw_mean_error * UNIT_SCALE, then EMA), except the EMA is *causal* (span only):
real time has no future samples for the offline centered window. Steady-state
magnitude is unchanged (~6-9 ns band).

Endpoints:
    GET /rmse    -> {"rmse_ns": 7.43, "tick": 12345, "sats": 500,
                     "faulty": 25, "clusters": 12}
    GET /health  -> {"status": "ok"}

No third-party web deps (stdlib http.server). Requires the same scientific
stack main_all_panela already uses (numpy, scikit-learn, scipy, geopy, pandas).

Usage:
    python rmse_server.py                 # :8000, 500 sats, 25 faulty, real-time
    python rmse_server.py --port 8000 --speed 1.0 --sats 500 --faulty 25
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import main_all_panela as sim
from fig_style import UNIT_SCALE

# --- Match synchronization_accuracy.py's panel-(a) operating point exactly so
# --- the live curve coincides with the offline/exported one. -----------------
NUM_SATS = 500
NUM_FAULTY = 25                 # 5% operating point (25/500)
K = 12
CLUSTER_CYCLE = 6000            # cluster sync once per 6000 ticks (6 s)
NEIGHBOR_CYCLE = 200            # neighbour sync cadence (from simulate_bc)
EMA_SPAN = 1250                 # causal EMA span in ticks (EMA_SPAN_A in make_figures)

sim.PANELA_NORMAL_STDDEV = 1.10          # 27 ppb healthy oscillator
MALFUNCTION_STDDEV = 1.10                # faulty jitter == healthy
MALFUNCTION_DRIFT_BIAS = 9.0e-9          # coherent fault offset
sim.BC_CLUSTER_CYCLE = CLUSTER_CYCLE
sim.POSITION_UPDATE_CYCLE = CLUSTER_CYCLE

# Shared state published by the stepper thread, read by the HTTP handler.
# Single dict-item assignments are atomic under the GIL; no lock needed.
#
# local_cycle_sec is the hook for driving the DT's "Local Cycle" cell from the
# simulation. The sim's intra-cluster/neighbour sync cadence is NEIGHBOR_CYCLE
# ticks (= NEIGHBOR_CYCLE * TIME_TICK seconds). It is published as 0.0 by default
# so the DT derives the cell from the chain (half the block interval); set it to
# a positive value here to let the simulation drive that cell instead.
LOCAL_CYCLE_SEC = 0.0   # e.g. NEIGHBOR_CYCLE * TIME_TICK == 0.2 to drive from sim
STATE = {"rmse_ns": 0.0, "tick": 0, "sats": NUM_SATS,
         "faulty": NUM_FAULTY, "clusters": K,
         "local_cycle_sec": LOCAL_CYCLE_SEC}


class LiveSim:
    """Holds the live simulation arrays and advances them one tick at a time,
    mirroring main_all_panela.simulate_bc but unbounded (runs forever)."""

    def __init__(self, num_sats, num_faulty, k):
        self.k = k
        sats = sim.initialize_satellites(
            num_sats, num_faulty,
            malfunction_mean=40e6,
            malfunction_stddev=MALFUNCTION_STDDEV,
            malfunction_drift_bias=MALFUNCTION_DRIFT_BIAS,
            cluster_aligned=True,
        )
        (self.positions, self.velocities, self.ang_vels,
         self.drifts, self.frequencies, self.clocks) = sim._extract_arrays(sats)
        self.n = len(self.positions)

        self.cluster_idx_list = sim.cluster_indices_from_kmeans(self.positions, k)
        labels = sim._labels_from_clusters(self.n, self.cluster_idx_list)
        self.best = sim.compute_best_neighbor_array(
            self.positions, self.frequencies, 2500, labels=labels)
        self.drift_step = self.drifts * sim.TIME_TICK * sim.TIME_TICK

        self.tick = 0
        self.pos_t = 0
        self.cls_t = 0
        self.alpha = 2.0 / (EMA_SPAN + 1.0)   # causal EMA coefficient
        self.ema_ns = None

    def step(self):
        """Advance exactly one simulation tick and return the smoothed RMSE (ns)."""
        self.clocks += self.drift_step
        raw_mean, _ = sim.measure_sync_performance_vec(self.clocks)   # seconds
        val_ns = raw_mean * UNIT_SCALE
        self.ema_ns = val_ns if self.ema_ns is None \
            else self.ema_ns + self.alpha * (val_ns - self.ema_ns)

        self.tick += 1
        if self.tick % NEIGHBOR_CYCLE == 0:
            sim.sync_with_neighbor_pre(self.clocks, self.best)

        self.pos_t += 1
        if self.pos_t >= sim.POSITION_UPDATE_CYCLE:
            self.positions = sim.update_positions_vec(
                self.positions, self.velocities, self.ang_vels, sim.POSITION_UPDATE_CYCLE)
            self.pos_t = 0
            self.cluster_idx_list = sim.cluster_indices_from_kmeans(self.positions, self.k)
            labels = sim._labels_from_clusters(self.n, self.cluster_idx_list)
            self.best = sim.compute_best_neighbor_array(
                self.positions, self.frequencies, 2500, labels=labels)

        self.cls_t += 1
        if self.cls_t >= sim.BC_CLUSTER_CYCLE:
            sim.sync_with_cluster_bc_vec(self.clocks, self.cluster_idx_list)
            self.cls_t = 0

        return self.ema_ns


def stepper_thread(live, speed, stop_evt):
    """Pace the simulation to wall-clock time: TIME_TICK (1 ms) of sim time per
    1 ms of real time, scaled by `speed`. Catches up on small hiccups but never
    runs more than a bounded burst, so it cannot spiral."""
    ticks_per_sec = speed / sim.TIME_TICK          # 1/0.001 = 1000 ticks/s at speed 1
    last = time.perf_counter()
    acc = 0.0
    MAX_BURST = 2000                               # cap catch-up per wake
    while not stop_evt.is_set():
        now = time.perf_counter()
        acc += (now - last) * ticks_per_sec
        last = now
        nsteps = int(acc)
        if nsteps > 0:
            acc -= nsteps
            if nsteps > MAX_BURST:                 # fell far behind → drop, stay real-time
                nsteps = MAX_BURST
            rmse = 0.0
            for _ in range(nsteps):
                rmse = live.step()
            STATE["rmse_ns"] = round(float(rmse), 4)
            STATE["tick"] = live.tick
        time.sleep(0.02)                           # ~50 publishes/sec


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")  # harmless; helps WebGL
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/rmse":
            self._send(200, STATE)
        elif path in ("/health", "/"):
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *args):
        pass   # silence per-request logging


def main():
    ap = argparse.ArgumentParser(description="Real-time BLT-SAND RMSE server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--speed", type=float, default=1.0, help="sim seconds per real second")
    ap.add_argument("--sats", type=int, default=NUM_SATS)
    ap.add_argument("--faulty", type=int, default=NUM_FAULTY)
    args = ap.parse_args()

    STATE["sats"] = args.sats
    STATE["faulty"] = args.faulty

    print(f"[rmse_server] initializing {args.sats} satellites "
          f"({args.faulty} faulty, k={K}) ...")
    live = LiveSim(args.sats, args.faulty, K)
    print(f"[rmse_server] warming up EMA ...")
    for _ in range(EMA_SPAN):      # prime the causal EMA so the first reading is steady
        live.step()
    STATE["rmse_ns"] = round(float(live.ema_ns), 4)
    STATE["tick"] = live.tick

    stop_evt = threading.Event()
    t = threading.Thread(target=stepper_thread, args=(live, args.speed, stop_evt), daemon=True)
    t.start()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[rmse_server] serving http://{args.host}:{args.port}/rmse "
          f"(speed={args.speed}x).  Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[rmse_server] stopping ...")
    finally:
        stop_evt.set()
        srv.shutdown()


if __name__ == "__main__":
    main()
