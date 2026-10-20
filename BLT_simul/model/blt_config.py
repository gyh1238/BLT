"""The simulation configuration, in one call.

    import blt_config
    blt_config.apply(main_all)

There is only one configuration and this is it: every result in the repository
was produced under these settings. docs/MODEL.md explains where each value
comes from and what bounds it.

What it sets:
  parameters    healthy oscillator 1 ppb; degraded oscillator 27.5 ppb spread with a
            19 ppb bias; local = global = 6 s; FTSP re-flood 0.45 s; timestamps
            from a 100 MHz counter (10 ns LSB) with 3 ns jitter
  engine    all four schemes on one profile (FAULT_PROFILE);
            distance-dependent ISL links; two-way timestamp noise on member
            exchanges; the derived thresholds recomputed from the parameters above

Two of these cost BLT-SAND accuracy rather than buy it, since the link model and
the measurement noise each only add error; the FTSP flood period, 13x faster
than the BLT-SAND commit, runs the other way and favours FTSP.

Some drivers bind their own profile and switch to this one when the environment
sets BLT_CONFIG=1 (see `active()`), writing to result/runs/ via BLT_SAND_RESULT_DIR.
"""

from __future__ import annotations

import dataclasses
import os

import blt_params
import engine_profiles

HEALTHY_PPB = 1.0
FAULTY_PPB = 27.5
FAULTY_BIAS_PPB = 19.0   # within the +-30 ppb/year ageing bound (blt_params)
CYCLE_TICKS = 6000
FLOOD_TICKS = 450
LSB_S = 1e-8
JITTER_S = 3e-9
ATS_ALPHA = 0.5
N_SATS = 8192

FAULTY_STDDEV_HZ = blt_params.ppb_to_hz(FAULTY_PPB)
FAULTY_DRIFT_BIAS = FAULTY_BIAS_PPB * 1e-9

_ORIGINAL = dict(blt_params.REGISTRY)


def active() -> bool:
    return os.environ.get('BLT_CONFIG', '').strip() not in ('', '0')


def apply(main_all) -> dict:
    params = {
        'osc_healthy_ppb': HEALTHY_PPB,
        'osc_faulty_ppb': FAULTY_PPB,
        'osc_faulty_bias_ppb': FAULTY_BIAS_PPB,
        'bc_local_cycle_ticks': CYCLE_TICKS,
        'bc_cluster_cycle_ticks': CYCLE_TICKS,
        'ftsp_flood_cycle_ticks': FLOOD_TICKS,
        'timestamp_resolution_s': LSB_S,
        'timestamp_jitter_s': JITTER_S,
        'ats_reconcile_alpha': ATS_ALPHA,
    }
    for name, value in params.items():
        blt_params.REGISTRY[name] = dataclasses.replace(_ORIGINAL[name], value=value)
    blt_params.REGISTRY['faulty_relay_timestamp_error_s'] = dataclasses.replace(
        _ORIGINAL['faulty_relay_timestamp_error_s'], value=blt_params.faulty_relay_error_s())

    engine_profiles.apply(engine_profiles.FAULT_PROFILE, main_all)
    for key in ('BC_LOCAL_CYCLE', 'BC_CLUSTER_CYCLE', 'ATS_LOCAL_CYCLE',
                'ATS_GLOBAL_CYCLE', 'POSITION_UPDATE_CYCLE'):
        setattr(main_all, key, CYCLE_TICKS)
    main_all.FTSP_FLOOD_CYCLE = FLOOD_TICKS
    main_all.NORMAL_OSC_STDDEV = blt_params.ppb_to_hz(HEALTHY_PPB)
    main_all.BC_AGREE_TOL = blt_params.agree_tol_s()
    main_all.FAULTY_REPORT_ERROR = blt_params.faulty_report_error_s()
    main_all.ATS_RECONCILE_ALPHA = ATS_ALPHA
    main_all.ISL_LINK_MODEL = True
    main_all.CLUSTER_WARM_START = True  # stable clusters across re-clustering
    main_all.LOCAL_MEASUREMENT_NOISE = True
    return params


def describe() -> str:
    return (f'configuration: healthy {HEALTHY_PPB} ppb, degraded {FAULTY_PPB}+{FAULTY_BIAS_PPB} ppb, '
            f'cycles {CYCLE_TICKS / 1000:.0f} s, FTSP flood {FLOOD_TICKS} ms, '
            f'timestamps {LSB_S * 1e9:.0f} ns LSB + {JITTER_S * 1e9:.0f} ns jitter, ISL links on, warm-start clusters')
