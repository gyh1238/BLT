"""Timestamp and link error model: where synchronization error actually comes from.

The simplest thing a simulation can inject at a link is `skew * hop_delay`
-- the staleness a relay adds because its own clock has drifted since it last
synced. That term is real, but on its own it is tiny: at 1 ppb and a 0.36 ms hop
it is 0.4 picoseconds, which is why FTSP looked artificially good once the clock
units were corrected. FTSP's disadvantage in the literature does not come from
that term at all.

The three error sources that matter, and which of them each protocol pays:

1. **Timestamp quantization.** A timestamp is read from a counter with a finite
   LSB, so it carries a uniform error of LSB/sqrt(12). Every protocol pays this,
   twice per exchange (transmit and receive).

2. **Timestamping jitter.** Interrupt, modem and PHY jitter at the moment of
   stamping. Every protocol pays this, twice per exchange.

3. **Propagation delay.** This is the one that separates the protocols, and it
   is the physically correct reason FTSP is worse in a constellation:

   - **One-way flooding (FTSP)** cannot separate clock offset from propagation
     delay. It receives a timestamp and must subtract a *predicted* range. What
     survives is the range prediction error divided by c. At an ISL range known
     to a metre that is 3.3 ns, per hop, and FTSP is multi-hop.
   - **Two-way exchange (BLT, ATS)** measures the round trip, so the symmetric
     propagation delay cancels exactly. Only the forward/return *asymmetry*
     survives, and it survives halved. At 5 cm of asymmetry that is 0.08 ns.

   That is a factor of ~40 per exchange, before FTSP's multi-hop accumulation.

Accumulation along a flood path: the errors at successive hops are independent,
so a node h hops from the reference inherits the sum of h independent draws --
a random walk, growing as sqrt(h). `flood_error_sigma_s` gives the per-hop
sigma; the flood itself accumulates it.

Every quantity here is in SI seconds, and every parameter comes from
blt_params.REGISTRY so that its dimension, provenance and credible range are
declared in one place.
"""

from __future__ import annotations

import numpy as np

import blt_params as params
from blt_params import C_KM_S, C_M_S


def hop_delay_s(distance_km, overrides=None):
    """Per-hop latency: propagation over the link plus store-and-forward.

    Propagation follows from the link length, so the processing term is the only
    part of this that is a choice.
    """
    processing = params.value('relay_processing_s', overrides)
    return np.asarray(distance_km, dtype=float) / C_KM_S + processing


def _stamp_variance_s2(overrides=None):
    """Variance contributed by reading two timestamps (transmit and receive)."""
    lsb = params.value('timestamp_resolution_s', overrides)
    jitter = params.value('timestamp_jitter_s', overrides)
    quant_var = (lsb ** 2) / 12.0
    return 2.0 * quant_var + 2.0 * (jitter ** 2)


def oneway_sigma_s(overrides=None):
    """Per-hop error sigma of a ONE-WAY timestamp transfer (FTSP).

    Pays the full range-prediction residual: a one-way message carries offset
    and propagation delay summed, and nothing in the protocol separates them.
    """
    range_residual = params.value('range_uncertainty_m', overrides) / C_M_S
    return float(np.sqrt(_stamp_variance_s2(overrides) + range_residual ** 2))


def twoway_sigma_s(overrides=None):
    """Per-exchange error sigma of a TWO-WAY exchange (BLT, ATS).

    The round trip cancels the symmetric delay; the asymmetry enters halved,
    because the offset estimate is the half-difference of the two directions.
    """
    asym_residual = params.value('path_asymmetry_m', overrides) / C_M_S
    return float(np.sqrt(_stamp_variance_s2(overrides) + (asym_residual / 2.0) ** 2))


def error_budget(overrides=None) -> dict:
    """Per-term breakdown in nanoseconds, for the paper's assumptions table."""
    lsb = params.value('timestamp_resolution_s', overrides)
    jitter = params.value('timestamp_jitter_s', overrides)
    rng_m = params.value('range_uncertainty_m', overrides)
    asym_m = params.value('path_asymmetry_m', overrides)
    ns = 1e9
    return {
        'quantization_per_stamp_ns': lsb / np.sqrt(12.0) * ns,
        'jitter_per_stamp_ns': jitter * ns,
        'oneway_range_residual_ns': rng_m / C_M_S * ns,
        'twoway_asymmetry_residual_ns': asym_m / C_M_S / 2.0 * ns,
        'oneway_total_per_hop_ns': oneway_sigma_s(overrides) * ns,
        'twoway_total_per_exchange_ns': twoway_sigma_s(overrides) * ns,
    }


def twoway_noise(shape, rng, overrides=None):
    """Measurement noise for one two-way exchange, in seconds.

    Injected where the offset is *measured*, not added to the result afterwards:
    a protocol that averages many exchanges should be able to average this down,
    and one that does not, should not.
    """
    if rng is None:
        return 0.0
    return rng.normal(0.0, twoway_sigma_s(overrides), size=shape)


if __name__ == '__main__':
    print("link error budget at the default parameters:\n")
    for k, v in error_budget().items():
        print(f"  {k:34} {v:9.4f} ns")
    o, t = oneway_sigma_s(), twoway_sigma_s()
    print(f"\n  one-way / two-way ratio: {o / t:.1f}x per exchange")
    print(f"  after a 5-hop flood, one-way random walk: {o * np.sqrt(5) * 1e9:.3f} ns")
    print("\n  This is why a constellation uses two-way time transfer, and it is")
    print("  the physically correct reason FTSP trails, not the relay staleness")
    print("  term, which is sub-picosecond at these link delays.")
