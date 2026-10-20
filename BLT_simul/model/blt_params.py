"""Every parameter of the BLT-SAND simulation, in one registry.

One place where a value, its unit and the reason for it sit together, instead of
bare module constants spread across the engine and its drivers.

Each entry carries:

  kind    the dimension, so a rate can never be compared against a delay
  source  'physical' (follows from a constant or a hardware specification),
          'design'   (a deliberate architectural choice),
          'derived'  (computed from other entries by a documented formula)
  low/high the range the value can credibly take
  why     the justification, in one sentence

`python blt_params.py` prints the table. `sensitivity.py` sweeps a parameter across
its declared range and reports how far the result actually moves.

Nothing here is applied automatically; engine_profiles.py binds the values a
given experiment uses onto its engine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict

# Physical constants (not parameters - these are not adjustable).
C_KM_S = 299_792.458          # speed of light in vacuum, km/s
C_M_S = 299_792_458.0         # m/s


@dataclass(frozen=True)
class Parameter:
    name: str
    value: float
    unit: str
    kind: str        # rate | offset_s | delay_s | length_m | cycle_ticks | ratio | count
    # physical: a measured or specified property of hardware or space
    # design:   a choice about how the protocol is built, stated as such
    # derived:  computed from other entries by a documented formula, changing
    #           it means changing an input, not this number
    source: str      # physical | design | derived
    low: float
    high: float
    why: str

    def scaled(self, factor: float) -> 'Parameter':
        return replace(self, value=self.value * factor)


def _L(name, value, unit, kind, source, low, high, why) -> Parameter:
    assert low <= value <= high, f"{name}: default {value} outside [{low}, {high}]"
    assert source in ('physical', 'design', 'derived'), name
    return Parameter(name, value, unit, kind, source, low, high, why)


# ---------------------------------------------------------------------------
# Oscillator
# ---------------------------------------------------------------------------
#
# A healthy satellite carries a disciplined oscillator; a malfunctioning one is
# the SAME hardware degraded, so it has both a larger random frequency spread
# and a coherent one-directional bias. Modelling the faulty jitter as equal to
# the healthy jitter (which both experiment tracks did) removes the very thing
# that makes a fault detectable by a spread test.

OSCILLATOR = [
    _L('osc_nominal_hz', 40e6, 'Hz', 'frequency_hz', 'design', 10e6, 100e6,
       'nominal oscillator frequency the constellation is specified around'),
    _L('osc_healthy_ppb', 1.0, 'ppb', 'rate', 'physical', 0.1, 10.0,
       'healthy disciplined-oscillator fractional frequency spread, 1 ppb per the paper spec'),
    _L('osc_faulty_ppb', 27.5, 'ppb', 'rate', 'design', 5.0, 30.0,
       'spread of a degraded oscillator. This and the bias below are the fault '
       'model: choosing them is choosing what "degraded" means, which is what '
       'the experiment is about rather than something it fits. The magnitude is '
       'bounded by hardware: a space-grade OCXO (Rakon RK409AVNS) specifies '
       'ageing of +-30 ppb/year, so a unit left uncorrected for most of a year '
       'sits in the tens of ppb and no further. Short-term stability is far '
       'tighter, sigma_y 2.5e-13 at 1 s, about 2 ps over a 6 s cycle, so a '
       'fault of this size cannot be confused with healthy jitter'),
    _L('osc_faulty_bias_ppb', 9.0, 'ppb', 'rate', 'design', 0.0, 30.0,
       'coherent one-directional frequency offset of a degraded oscillator; the '
       'part of the fault that survives averaging and so is what separates a '
       'mean from a median. Bounded by the same +-30 ppb/year ageing figure, '
       'and the adopted 19 ppb is the drift an uncorrected unit accumulates in '
       'roughly two thirds of a year. How severe a fault to model is a design '
       'choice, so the entry is declared as one and the datasheet is what bounds '
       'it. The severity reaches ATS and not the others: across 14 to 23 ppb ATS '
       'runs 12.2 to 16.6 ns while BLT-SAND holds 8.78-8.79 and FTSP 17.76, '
       'because a median absorbs a one-directional bias and a flooding path '
       'never sees it'),
]

# ---------------------------------------------------------------------------
# Timestamping and link error
# ---------------------------------------------------------------------------
#
# These set the floor no synchronization protocol can beat, and they are where
# one-way flooding (FTSP) and two-way exchange (BLT, ATS) genuinely differ.

TIMESTAMPING = [
    _L('timestamp_resolution_s', 1e-10, 's', 'offset_s', 'design', 1e-12, 2.5e-8,
       'timestamping LSB; 2.5e-8 is a bare 40 MHz counter, 1e-12 a good TDC - '
       'reaching a 10 ns target requires the TDC end of this range'),
    _L('timestamp_jitter_s', 1e-10, 's', 'offset_s', 'physical', 1e-12, 1e-8,
       'send/receive timestamping jitter of an optical ISL terminal'),
    _L('range_uncertainty_m', 1.0, 'm', 'length_m', 'physical', 0.01, 100.0,
       'how well the inter-satellite range is known a priori; sets the residual '
       'a ONE-WAY transfer cannot remove, since it cannot separate offset from delay'),
    _L('path_asymmetry_m', 0.05, 'm', 'length_m', 'physical', 0.001, 10.0,
       'forward/return path length difference; the only propagation term a '
       'TWO-WAY exchange fails to cancel'),
    _L('relay_processing_s', 1e-4, 's', 'delay_s', 'design', 1e-6, 1e-2,
       'per-relay store-and-forward processing time, on top of propagation'),
    _L('faulty_relay_timestamp_error_s', 2.0625e-8, 's', 'offset_s', 'derived',
       1e-9, 1e-6,
       'coherent timestamping error a malfunctioning relay injects. A degraded '
       'node mis-STAMPS; modelling its fault as a larger frequency skew instead '
       'made the fault invisible, because skew only reaches the result through '
       'skew x hop_delay, which is sub-picosecond. Of every free constant in the '
       'comparison this is the only one that moves a result, it swings FTSP '
       '155x across its range while the other four are numerically inert, so '
       'it is the one value with that much leverage, so it is derived: see '
       'faulty_relay_error_s()'),
]

# ---------------------------------------------------------------------------
# Protocol cycles and topology
# ---------------------------------------------------------------------------

CYCLES = [
    _L('neighbour_cycle_ticks', 200, 'ticks', 'cycle_ticks', 'design', 20, 2000,
       'local neighbour exchange period; 1 tick = 1 ms'),
    _L('bc_local_cycle_ticks', 2700, 'ticks', 'cycle_ticks', 'design', 500, 10000,
       'BLT intra-cluster aggregation period; 2.7 s = dual-ISL TWTT collection for ~650 members'),
    _L('bc_cluster_cycle_ticks', 5500, 'ticks', 'cycle_ticks', 'design', 1000, 20000,
       'BLT global consensus period; 5.5 s = single-ISL worst case, budgeted as fault margin'),
    _L('ftsp_flood_cycle_ticks', 750, 'ticks', 'cycle_ticks', 'design', 200, 20000,
       'FTSP re-flood period, 0.75 s here and 0.45 s in the adopted '
       'configuration (blt_config.py). Either is far more often than BLT-SAND '
       'commits its global round, 8x and 13x at a 6 s cycle, and that is the '
       'end of the range which suits FTSP, since re-flooding often is what '
       'gives each relay a fresh reference. Matching the two cadences would '
       'make FTSP worse'),
    _L('isl_range_km', 2500.0, 'km', 'length_km', 'design', 1000.0, 5000.0,
       'maximum inter-satellite link range used for neighbour discovery'),
    _L('cluster_count', 12, 'count', 'count', 'design', 6, 30,
       'number of clusters / cluster heads / chain validators'),
]

# ---------------------------------------------------------------------------
# Consensus and fault injection
# ---------------------------------------------------------------------------

CONSENSUS = [
    _L('bc_quorum', 2/3, 'ratio', 'ratio', 'design', 0.5, 1.0,
       'fraction of heads that must vote for a proposal before it commits. 2/3 '
       'is the classical PBFT quorum (2f+1 of 3f+1); at that value an honest '
       'proposal carries while liars are under N/3 and a lie carries only past '
       '2N/3, so the 1/3 bound follows from the protocol instead of being asserted'),
    _L('agree_tol_sigmas', 3.0, 'sigma', 'ratio', 'design', 1.0, 6.0,
       'how many standard deviations of legitimate healthy-head spread the '
       'agreement window admits. The window itself is derived: see '
       'agree_tol_s()'),
    _L('ats_reconcile_alpha', 0.5, 'ratio', 'ratio', 'design', 0.0, 1.0,
       'ATS global correction strength'),
    _L('neighbour_alpha', 0.5, 'ratio', 'ratio', 'design', 0.0, 1.0,
       'neighbour sync correction strength; must be equal across protocols in an '
       'ablation or the consensus effect is confounded with the gain'),
]

# ---------------------------------------------------------------------------
# Comparison-algorithm constants
# ---------------------------------------------------------------------------
#
# The five values that decide how the three schemes compare. Three of them set
# how far a fault moves a baseline, so each carries the range it can credibly
# take and the reason for the value it has, and `sensitivity.py` sweeps each
# across that range rather than asserting the point. Where a physical
# derivation exists the entry gives it.

COMPARISON = [
    _L('intercluster_hop_delay_s', 8.439102e-3, 's', 'delay_s', 'derived', 1e-4, 5e-2,
       'head-to-head relay latency in the global phase. Two cluster heads are '
       'at most isl_range_km apart, so the latency is that range over c plus '
       'one relay_processing_s: see intercluster_hop_delay()'),
    _L('ftsp_fault_skew_ppb', 4.0, 'ppb', 'rate', 'design', 0.1, 30.0,
       'frequency skew attributed to a degraded FTSP relay, under the same '
       '+-30 ppb/year bound as the oscillator params. It reaches the result '
       'only as skew x hop delay, which at this size over an 8.4 ms hop is '
       '0.034 ns, so the value is not what carries the FTSP number: '
       'faulty_relay_timestamp_error_s is, and that one is derived'),
]

# ---------------------------------------------------------------------------
# Optical ISL availability (blt_isl)
# ---------------------------------------------------------------------------
#
# The paper states 2.5 W, 1,550 nm and 20 urad, and the authors used them only
# to set the 2,500 km range (isl_range_km). They reached no timing result. These
# parameters turn that range into a link that degrades toward it and breaks past it.
# Read only when main_all.ISL_LINK_MODEL is True.

ISL = [
    _L('isl_divergence_full_rad', 20e-6, 'rad', 'angle_rad', 'physical', 5e-6, 100e-6,
       'full 1/e^2 beam divergence stated in the paper; its half is the Gaussian '
       'beam width the pointing loss is measured against'),
    _L('isl_pointing_jitter_rad', 2e-6, 'rad', 'angle_rad', 'physical', 0.5e-6, 5e-6,
       'per-axis RMS pointing error of the fine-pointing loop. ASSUMED, no source: '
       'it sets how sharply outages rise near the range limit, through the exponent '
       'half_div^2 / (2 jitter^2) = 12.5 at the defaults'),
    _L('isl_grazing_altitude_km', 100.0, 'km', 'length_km', 'physical', 0.0, 300.0,
       'lowest altitude a link ray may pass; below it the atmosphere blocks the '
       'beam. ASSUMED. Inactive at 550 km shells within 2,500 km (the limb is '
       '~4,900 km away) and kept so lower shells break correctly'),
    _L('isl_route_hop_cost', 0.01, 'ratio', 'ratio', 'design', 1e-3, 0.2,
       'routing penalty per relay hop, in units of -ln(link success): 0.01 means '
       'a route takes one more hop only to avoid more than ~1% extra loss. With no '
       'penalty the most reliable route chains 7-20 short links; at 0.01 member '
       'routes average 2 hops (max 5), matching the 1-3 hop geometry'),
    _L('isl_acquisition_s', 30.0, 's', 'delay_s', 'physical', 1.0, 300.0,
       'time from a pair coming into range to a usable link (spatial acquisition). '
       'ASSUMED, no source. The engine can only apply it at position updates, so '
       'the effective value is rounded up to the update grid'),
]

REGISTRY: Dict[str, Parameter] = {
    l.name: l for group in (OSCILLATOR, TIMESTAMPING, CYCLES, CONSENSUS, COMPARISON, ISL)
    for l in group
}

GROUPS = {
    'oscillator': OSCILLATOR,
    'timestamping': TIMESTAMPING,
    'cycles': CYCLES,
    'consensus': CONSENSUS,
    'comparison': COMPARISON,
    'isl': ISL,
}


def value(name: str, overrides: dict | None = None) -> float:
    if overrides and name in overrides:
        return overrides[name]
    return REGISTRY[name].value


def ppb_to_hz(ppb: float, nominal_hz: float | None = None) -> float:
    """Convert a fractional frequency spread in ppb to the Hz stddev the engines
    draw from. The engines parameterise the oscillator in Hz at the nominal
    frequency, which is why 1 ppb reads as 0.04 and 27.5 ppb as 1.10."""
    if nominal_hz is None:
        nominal_hz = value('osc_nominal_hz')
    return ppb * 1e-9 * nominal_hz


TICK_S = 1e-3  # one simulation tick


def agree_tol_s(overrides=None) -> float:
    """Spread within which two cluster heads count as agreeing, in seconds.

    Derived rather than chosen. Between local aggregations a healthy head's
    reference drifts by its own fractional frequency error times the elapsed
    time, so the legitimate spread among healthy heads is

        osc_healthy_ppb * bc_local_cycle

    and the window is that times `agree_tol_sigmas`. At the defaults: 1 ppb over
    2.7 s is 2.7 ns, so a 3-sigma window is 8.1 ns.

    This ties the threshold to the oscillator spec instead of to a number picked
    to make a curve land, and it moves correctly if either the oscillator or the
    cadence changes.
    """
    ppb = value('osc_healthy_ppb', overrides) * 1e-9
    cycle = value('bc_local_cycle_ticks', overrides) * TICK_S
    return value('agree_tol_sigmas', overrides) * ppb * cycle


def faulty_report_error_s(overrides=None) -> float:
    """Error a degraded head's reference carries, in seconds.

    Same derivation with the faulty oscillator: a degraded oscillator accumulates
    osc_faulty_ppb * bc_local_cycle between aggregations. At the defaults, 27.5
    ppb over 2.7 s is 74 ns.

    The separation between this and agree_tol_s is therefore not a free choice:
    it is osc_faulty_ppb / (osc_healthy_ppb * agree_tol_sigmas), about 9x. A
    degraded head is detectable exactly to the extent that its oscillator is
    worse than a healthy one, which is the physical claim the experiment should
    be resting on.
    """
    ppb = value('osc_faulty_ppb', overrides) * 1e-9
    cycle = value('bc_local_cycle_ticks', overrides) * TICK_S
    return ppb * cycle


def intercluster_hop_delay(overrides=None) -> float:
    """Head-to-head relay latency in the global phase, in seconds.

    Cluster heads reconcile over a multi-hop head network rather than a
    broadcast, and a hop between two heads is bounded by the same link range
    every other ISL hop is: they cannot be further apart than isl_range_km and
    still have a link. So the latency is that range over the speed of light
    plus one store-and-forward:

        isl_range_km / c + relay_processing_s

    which is the same formula blt_links.hop_delay_s applies to a member hop.
    Nothing here is chosen; change the range or the processing time and this
    number follows.
    """
    return value('isl_range_km', overrides) / C_KM_S + value('relay_processing_s', overrides)


def faulty_relay_error_s(overrides=None, beacons=1) -> float:
    """Timestamping error a degraded FTSP relay injects, in seconds.

    The third instance of the same derivation, and the one that matters: the
    sensitivity sweep shows this constant swings FTSP 155x across its registered
    range while every other comparison constant is numerically inert, so it is
    computed from the timestamp entries rather than stated on its own.

    A relay compensates its own skew from the reference it last received. If its
    oscillator is degraded by osc_faulty_ppb, the compensation is wrong by that
    fraction, and the error it stamps into a relayed message is that fraction
    times the interval since its reference was refreshed, one flood period:

        osc_faulty_ppb * ftsp_flood_cycle_ticks

    At the defaults, 27.5 ppb over 0.75 s is 20.6 ns.

    `beacons` widens the interval to FTSP's multi-beacon rate estimate: the
    original protocol regresses over 8 beacons, so the residual can accumulate
    over up to 8 periods, giving 165 ns. The defensible range is therefore
    [20.6, 165] ns. The default of
    one period is the low end of that range, which is the value most
    favourable to FTSP.
    """
    ppb = value('osc_faulty_ppb', overrides) * 1e-9
    cycle = value('ftsp_flood_cycle_ticks', overrides) * TICK_S
    return ppb * cycle * beacons


def derived_params() -> list:
    """Entries computed from other entries. Each one must have a helper in this
    module that recomputes it, and the registry value must agree with that
    helper, verify_units.py checks exactly that, so a value cannot be quoted
    as derived while drifting from its own formula."""
    return [l for l in REGISTRY.values() if l.source == 'derived']


# The registered value of a derived entry IS its formula's output, not a literal
# transcribed from one. Recomputing it here keeps the number and the formula from
# drifting apart, rather than leaving the drift to be noticed later.
REGISTRY['intercluster_hop_delay_s'] = replace(
    REGISTRY['intercluster_hop_delay_s'], value=intercluster_hop_delay())


def table() -> str:
    out = []
    for group, group_params in GROUPS.items():
        out.append(f"\n{group.upper()}")
        out.append(f"  {'parameter':26} {'value':>12} {'unit':>7} {'source':>9} "
                   f"{'low':>10} {'high':>10}")
        out.append("  " + "-" * 78)
        for l in group_params:
            out.append(f"  {l.name:26} {l.value:>12.6g} {l.unit:>7} {l.source:>9} "
                       f"{l.low:>10.6g} {l.high:>10.6g}")
            out.append(f"      {l.why}")
    return "\n".join(out)


if __name__ == '__main__':
    print("BLT-SAND parameter registry")
    print(table())
    print("\nComputed from other parameters, and checked against their formula by "
          "verify_units.py:")
    for l in derived_params():
        print(f"  {l.name:26} {l.value:>12.6g} {l.unit:<5} derived")

    # The figures below are the measured influence of each parameter, from
    # sweeping one at a time over its whole registered range. A wide range is
    # not the same thing as a large influence, which is why both are printed.
    print("\nMeasured influence (sensitivity.py, 14 parameters x 5 values):")
    print("  - what is left to choose is the fault model: how wide a degraded "
          "oscillator")
    print("    is and how far it is biased. That is choosing what 'degraded' "
          "means, which")
    print("    is the experiment rather than a curve fit, and the size is "
          "bounded above")
    print("    by the +-30 ppb/year ageing figure on a space-grade OCXO "
          "datasheet.")
    print("  - no delay or latency is free: a delay reaches the output only as "
          "skew x")
    print("    hop_delay, 8 ps at 1 ppb over an 8.4 ms hop, and every one of "
          "them is now")
    print("    computed from the link geometry.")
    print("  - parameters classed physical swing results harder than the free ones: "
          "1 ppb of")
    print("    healthy oscillator moves BLT 6.6x. Free and influential are "
          "different axes.")
    print("  - BLT < ATS < FTSP held at all 70 measured points.")
