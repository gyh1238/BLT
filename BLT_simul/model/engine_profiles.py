"""Named parameter profiles for the BLT-SAND simulation engines.

Each experiment's parameter set is one named dict, applied explicitly, rather
than globals rebound inline in each driver. Two things follow: the settings a
figure was produced under are stated in one place, and where the accuracy track
and the fault track differ is enumerable rather than something found by
diffing two drivers. `differences()` prints that list.

One engine. Both experiment tracks run the same code in `main_all` and differ
only by the profile applied here, so a difference between two results is the
profile and not the implementation.
"""

from __future__ import annotations

import blt_params

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
#
# Every value below is in SI seconds, dimensionless, or ticks, as marked. The
# engines accumulate clock error in real seconds (blt_core.clock_error_step),
# so the three classes of parameter stay distinct:
#
#   offset  [s]            absolute time error injected into a clock
#   delay   [s]            physical relay/propagation latency; the clock error
#                          it induces is (fractional freq error) x delay
#   rate    [dimensionless] fractional frequency error, e.g. 1e-9 = 1 ppb
#   cycle   [ticks]        TIME_TICK = 1 ms, so 6000 ticks = 6 s
#
# The tags are load-bearing: a tick count applied as a period, or a frequency
# spread applied as a drift, is a unit error the engine cannot detect.

# One healthy-oscillator value serves both tracks, read from the parameter
# registry, so the accuracy results and the fault results describe the same
# system. 27.5 ppb is what a *degraded* oscillator looks like and lives in
# osc_faulty_ppb; the healthy figure is osc_healthy_ppb.
HEALTHY_STDDEV_HZ = blt_params.ppb_to_hz(blt_params.value('osc_healthy_ppb'))
FAULTY_STDDEV_HZ = blt_params.ppb_to_hz(blt_params.value('osc_faulty_ppb'))
FAULTY_DRIFT_BIAS = blt_params.value('osc_faulty_bias_ppb') * 1e-9   # rate

ACCURACY_PROFILE = {
    # --- oscillator -------------------------------------------------------
    'NORMAL_OSC_STDDEV': HEALTHY_STDDEV_HZ,   # 1 ppb
    # --- cycles [ticks] ---------------------------------------------------
    'BC_CLUSTER_CYCLE': 6000,
    'POSITION_UPDATE_CYCLE': 6000,       # same grid as the cluster sync
    # --- FTSP -------------------------------------------------------------
    'FTSP_STATIC_GRAPH': True,           # frozen neighbour graph -> flat band
    'FTSP_FAULT_SKEW': 2.0e-8,           # rate [dimensionless] = 20 ppb
}

FAULT_PROFILE = {
    # --- cycles [ticks] ---------------------------------------------------
    # local 2.7 s = dual-ISL nominal intra-cluster TWTT collection (650 members
    # x 8 ms / 2 links); global 5.5 s = the single-link (one ISL terminal
    # failed) worst case, budgeted so a block commits even with a degraded head.
    'BC_LOCAL_CYCLE': 2700,
    'BC_CLUSTER_CYCLE': 5500,
    'ATS_LOCAL_CYCLE': 2700,
    'ATS_GLOBAL_CYCLE': 5500,
    # --- consensus --------------------------------------------------------
    'BC_QUORUM': blt_params.value('bc_quorum'),   # 2/3, classical PBFT
    # Both computed from the oscillator specification and the local cadence.
    'BC_AGREE_TOL': blt_params.agree_tol_s(),
    'FAULTY_REPORT_ERROR': blt_params.faulty_report_error_s(),
    # --- ATS --------------------------------------------------------------
    'ATS_RECONCILE_ALPHA': 0.5,          # dimensionless
    # --- link delays ------------------------------------------------------
    # INTERCLUSTER_HOP_DELAY not set: derived from isl_range_km and
    # relay_processing_s by blt_params.intercluster_hop_delay().
    # FTSP_FAULT_SKEW not set: it reaches the result only as skew x hop delay,
    # which over an 8.4 ms hop is a small fraction of a nanosecond. The fault
    # channel that matters is faulty_relay_timestamp_error_s.
}



def apply(profile: dict, module) -> dict:
    """Bind every parameter in `profile` onto `module`, returning what was set.

    Raises on a name the module does not define, which catches a parameter
    renamed in the engine but not in the profile; without the check that would
    set an unused attribute and leave the engine on its default.
    """
    applied = {}
    for name, value in profile.items():
        if not hasattr(module, name):
            raise AttributeError(
                f"{module.__name__} has no parameter {name!r}; "
                "the profile and the engine have diverged")
        setattr(module, name, value)
        applied[name] = value
    return applied


def differences() -> dict:
    """{parameter: (accuracy value, fault value)} for every parameter the two
    experiment tracks set differently or that only one of them sets."""
    out = {}
    for name in sorted(set(ACCURACY_PROFILE) | set(FAULT_PROFILE)):
        a = ACCURACY_PROFILE.get(name, '(unset)')
        f = FAULT_PROFILE.get(name, '(unset)')
        if a != f:
            out[name] = (a, f)
    return out


if __name__ == '__main__':
    print("parameters the two experiment tracks do not share:\n")
    print(f"{'parameter':26} {'accuracy':>14} {'fault':>14}")
    print("-" * 58)
    for name, (a, f) in differences().items():
        print(f"{name:26} {str(a):>14} {str(f):>14}")
