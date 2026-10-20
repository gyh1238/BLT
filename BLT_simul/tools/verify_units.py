"""Checks on blt_core: the clock units and the metric definitions.

The unit check anchors the whole model to something a reader can verify by
hand, that a 1 ppb oscillator accumulates 1 ns per second, and it checks that
the accumulation step, the figure scale and the axis label agree on one unit,
since changing one of the three alone would move every published magnitude.

Run:  python tools/verify_units.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
# Run from anywhere: the engine modules live in model/, figure style in figures/, and
# data/ and result/ are resolved from the repository root.
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while not _os.path.isdir(_os.path.join(_ROOT, 'model')):   # climb to the repository root
    _ROOT = _os.path.dirname(_ROOT)
_sys.path[:0] = [_os.path.join(_ROOT, 'model'), _os.path.join(_ROOT, 'figures')]
_os.chdir(_ROOT)

import numpy as np

import blt_core as core

PASS, FAIL = "OK  ", "FAIL"
_failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _failures
    if not ok:
        _failures += 1
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  {detail}" if detail else ""))


def test_clock_units() -> None:
    """The step, the figure scale and the axis label agree on nanoseconds."""
    print("\nclock units:")

    # State the physical magnitude plainly so a reader can sanity-check it:
    # a 1 ppb clock accumulates 1 ns of error per second. The tolerance is set
    # by how well 1 + 1e-9 survives storage in a float64, not by the formula.
    one_ppb_per_second = float(
        core.clock_error_step(np.array([1.0 + 1e-9]))[0]
        * (1.0 / core.TIME_TICK) * core.SECONDS_TO_NS)
    check("1 ppb oscillator accumulates 1 ns per second",
          abs(one_ppb_per_second - 1.0) < 1e-6,
          f"{one_ppb_per_second:.9f} ns/s")

    # The engines store f_i / f_nom = 1 + eps, so eps is already truncated
    # before any arithmetic happens. Worth knowing before anyone claims
    # sub-picosecond fidelity from this model.
    eps_roundtrip = (1.0 + 1e-9) - 1.0
    check("storing 1 + eps costs ~8 digits of the fractional frequency error",
          abs(eps_roundtrip - 1e-9) / 1e-9 < 1e-6,
          f"rel error {abs(eps_roundtrip - 1e-9) / 1e-9:.2e} at 1 ppb")

    # The figures must convert with the same factor the step is written in.
    import fig_style
    check("fig_style.UNIT_SCALE is the s -> ns factor the step assumes",
          fig_style.UNIT_SCALE == core.SECONDS_TO_NS,
          f"fig_style {fig_style.UNIT_SCALE:.3e} vs blt_core {core.SECONDS_TO_NS:.3e}")


def test_metric_definitions() -> None:
    print("\nmetric definitions:")
    clocks = np.array([1.0, 2.0, 3.0, 4.0])

    e = core.sync_error(clocks)
    # mean = 2.5, deviations = [-1.5, -0.5, 0.5, 1.5]
    check("mean_abs_dev matches its definition",
          abs(e.mean_abs_dev - 1.0) < 1e-12, f"{e.mean_abs_dev}")
    check("max_abs_dev matches its definition",
          abs(e.max_abs_dev - 1.5) < 1e-12, f"{e.max_abs_dev}")
    expected_rmse = float(np.sqrt(np.mean(np.array([-1.5, -0.5, 0.5, 1.5]) ** 2)))
    check("rmse_all is the RMS, not the mean absolute deviation",
          abs(e.rmse_all - expected_rmse) < 1e-12,
          f"rmse={e.rmse_all:.6f} vs mad={e.mean_abs_dev:.6f}")
    check("RMSE exceeds MAD for a non-degenerate spread",
          e.rmse_all > e.mean_abs_dev)

    # Backward compatibility: drivers index d[0] and d[1].
    check("tuple positions 0 and 1 stay the all-satellite pair",
          (e[0], e[1]) == (e.mean_abs_dev, e.max_abs_dev))


def test_reference_choice() -> None:
    print("\nreference definition:")
    # Three healthy clocks near 0 and one faulty far away.
    clocks = np.array([-1.0, 0.0, 1.0, 300.0])
    mask = np.array([True, True, True, False])

    unmasked = core.sync_error(clocks)
    masked = core.sync_error(clocks, normal_mask=mask)

    check("without a mask the faulty clock defines the timescale",
          abs(unmasked.reference - 75.0) < 1e-12, f"ref={unmasked.reference}")
    check("with a mask the reference is the healthy mean",
          abs(masked.reference - 0.0) < 1e-12, f"ref={masked.reference}")
    check("rmse_normal ignores the faulty satellite",
          abs(masked.rmse_normal - float(np.sqrt(2.0 / 3.0))) < 1e-12,
          f"{masked.rmse_normal:.6f}")
    check("rmse_all still includes it",
          masked.rmse_all > 100.0, f"{masked.rmse_all:.3f}")
    check("mean_abs_dev and max_abs_dev stay anchored to the all-satellite mean",
          abs(masked.mean_abs_dev - unmasked.mean_abs_dev) < 1e-12)

    allfaulty = core.sync_error(clocks, normal_mask=np.zeros(4, dtype=bool))
    check("an all-faulty run falls back instead of emitting nan reference",
          abs(allfaulty.reference - 75.0) < 1e-12)


def test_absolute_metric() -> None:
    """A common-mode shift is invisible to every relative field and visible only
    to rmse_absolute. This is the property the Byzantine-head experiment relies
    on, so it is worth pinning."""
    print("")
    print("absolute vs relative:")
    clocks = np.array([1.0, 2.0, 3.0]) * 1e-9
    base = core.sync_error(clocks)
    shifted = core.sync_error(clocks + 100e-9)

    # Relative comparison: these are ~1e-9 quantities, so an absolute 1e-24
    # threshold is tighter than float64 can express at that magnitude.
    rel_change = abs(base.rmse_all - shifted.rmse_all) / base.rmse_all
    check("relative RMSE is blind to a common-mode shift",
          rel_change < 1e-12,
          f"{base.rmse_all:.3e} -> {shifted.rmse_all:.3e} (rel {rel_change:.1e})")
    ratio = shifted.rmse_absolute / base.rmse_absolute
    check("absolute RMSE sees it",
          ratio > 20,
          f"{base.rmse_absolute:.3e} -> {shifted.rmse_absolute:.3e} ({ratio:.0f}x)")
    check("the earlier tuple positions still hold after adding the field",
          (base[0], base[1]) == (base.mean_abs_dev, base.max_abs_dev))


def test_derived_levers() -> None:
    """A parameter marked `derived` must equal what its own formula produces.

    Without this check the registry value and the helper could drift apart while
    the number is still described as following from its formula. Each derived
    entry is listed here with the helper that defines it, so adding one without
    a formula fails.
    """
    import blt_params as params

    formulas = {
        'faulty_relay_timestamp_error_s': params.faulty_relay_error_s,
        'intercluster_hop_delay_s': params.intercluster_hop_delay,
    }
    for parameter in params.derived_params():
        fn = formulas.get(parameter.name)
        check(f"{parameter.name} has a formula", fn is not None,
              "an entry marked derived must name the helper that computes it")
        if fn is None:
            continue
        want = fn()
        check(f"{parameter.name} matches its formula",
              abs(parameter.value - want) <= 1e-15 + 1e-9 * abs(want),
              f"registry {parameter.value:.6e} vs formula {want:.6e}")

    # The two helpers that back the consensus thresholds are derived the same
    # way but feed the engine through the profile rather than the registry, so
    # check the arithmetic they claim rather than only that they run.
    tol = params.agree_tol_s()
    want = (params.value('agree_tol_sigmas') * params.value('osc_healthy_ppb') * 1e-9
            * params.value('bc_local_cycle_ticks') * params.TICK_S)
    check("agree_tol_s is sigmas x healthy ppb x local cycle",
          abs(tol - want) <= 1e-9 * abs(want), f"{tol:.6e} vs {want:.6e}")

    rep = params.faulty_report_error_s()
    want = (params.value('osc_faulty_ppb') * 1e-9
            * params.value('bc_local_cycle_ticks') * params.TICK_S)
    check("faulty_report_error_s is faulty ppb x local cycle",
          abs(rep - want) <= 1e-9 * abs(want), f"{rep:.6e} vs {want:.6e}")

    # The FTSP flood cadence exists in two places and they must agree: the
    # the registry entry and the engine must name the same flood period.
    import main_all
    check("engine flood cadence matches the registry",
          main_all.FTSP_FLOOD_CYCLE == params.value('ftsp_flood_cycle_ticks'),
          f"engine {main_all.FTSP_FLOOD_CYCLE} vs registry "
          f"{params.value('ftsp_flood_cycle_ticks')}")


def test_isl_link_model() -> None:
    """The distance-dependent ISL model (blt_isl) against its own derivation."""
    print("\nISL link availability:")
    import blt_isl as isl
    import blt_params as params

    d_max = params.value('isl_range_km')
    k = isl.outage_exponent()
    check("outage exponent is half-divergence^2 / (2 jitter^2)",
          abs(k - (10e-6) ** 2 / (2 * (2e-6) ** 2)) < 1e-9, f"k = {k:.3f}")
    p = isl.exchange_outage_prob([0.0, d_max / 2, d_max, 1.1 * d_max])
    check("no outage at zero range, certain outage at and past the limit",
          p[0] == 0.0 and p[2] == 1.0 and p[3] == 1.0, str(p))
    check("half range gives 0.5^k", abs(p[1] - 0.5 ** k) < 1e-15, f"{p[1]:.3e}")

    # The closed form must be what a Gaussian beam with Rayleigh pointing gives.
    rng = np.random.default_rng(7)
    w, sig = 10e-6, 2e-6
    theta2 = rng.normal(0, sig, 1_000_000) ** 2 + rng.normal(0, sig, 1_000_000) ** 2
    worst = 0.0
    for dist in (1750.0, 2000.0, 2400.0):
        margin = (d_max / dist) ** 2
        mc = np.mean(np.exp(-2 * theta2 / w ** 2) < 1 / margin)
        worst = max(worst, abs(mc - float(isl.exchange_outage_prob(dist))))
    check("closed form matches Monte Carlo pointing fade", worst < 3e-3,
          f"worst |MC - closed| = {worst:.2e}")

    r = isl.EARTH_RADIUS_KM + 550.0
    a = np.array([r, 0.0, 0.0])
    ang = 2500.0 / r
    b = np.array([r * np.cos(ang), r * np.sin(ang), 0.0])
    check("2,500 km at 550 km altitude clears the atmosphere",
          bool(isl.line_of_sight(a, b)[0]))
    check("antipodal satellites are blocked by the Earth",
          not bool(isl.line_of_sight(a, -a)[0]))

    # A small synthetic shell: routes, subtree failure, expected loss.
    rng = np.random.default_rng(11)
    v = rng.normal(size=(300, 3))
    pos = r * v / np.linalg.norm(v, axis=1)[:, None]
    groups = [np.arange(0, 150), np.arange(150, 300)]
    model = isl.LinkModel(300, np.random.default_rng(5))
    model.update(pos, groups, 0.0)
    tree = model.local_trees[0]
    idx = groups[0]
    inner = idx[tree.parent[idx] >= 0]
    check("hop depth is parent depth + 1",
          bool(np.all(tree.depth[inner] == tree.depth[tree.parent[inner]] + 1)))
    subtree_ok = True
    drawn = np.zeros(len(idx))
    rounds = 4000
    for _ in range(rounds):
        reach = tree.draw(model.rng)
        subtree_ok &= bool(np.all(~reach[inner] | reach[tree.parent[inner]]))
        drawn += reach[idx]
    check("a node is never reached when its relay is not", subtree_ok)
    expect = tree.path_success()[idx]
    routed = tree.depth[idx] > 0
    err = np.abs(drawn[routed] / rounds - expect[routed]).max()
    check("drawn route success matches the product of hop successes", err < 0.03,
          f"max |drawn - expected| = {err:.3f}")

    # Acquisition: a pair that enters range is unusable for isl_acquisition_s.
    t_acq = params.value('isl_acquisition_s')
    far = np.array([[r, 0.0, 0.0], [r * np.cos(3000 / r), r * np.sin(3000 / r), 0.0]])
    near = np.array([[r, 0.0, 0.0], [r * np.cos(1000 / r), r * np.sin(1000 / r), 0.0]])
    pair = isl.LinkModel(2, np.random.default_rng(0))
    one = [np.arange(2)]
    pair.update(far, one, 0.0)
    no_link_far = len(pair.i) == 0
    pair.update(near, one, 10.0)
    still_acquiring = len(pair.i) == 0
    pair.update(near, one, 10.0 + t_acq)
    check("a link out of range does not exist", no_link_far)
    check("a link that just came into range is still acquiring", still_acquiring)
    check("it is usable once the acquisition time has passed", len(pair.i) == 1)


def main() -> int:
    print("blt_core verification")
    test_clock_units()
    test_metric_definitions()
    test_reference_choice()
    test_absolute_metric()
    test_derived_levers()
    test_isl_link_model()
    print(f"\n{'all checks passed' if not _failures else f'{_failures} check(s) FAILED'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
