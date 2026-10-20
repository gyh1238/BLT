"""Shared definitions for the BLT-SAND simulation engines.

One definition of each quantity the paper quotes, imported by every arm, so
the accuracy results and the fault results measure the same thing.

1. **What is measured.** `sync_error()` returns three statistics and names
   them apart: the RMSE over the nominal satellites about the mean of those
   same clocks, which is the headline; the RMSE over all satellites; and the
   mean and maximum absolute deviation from the all-satellite mean, which are
   a different statistic from an RMSE and are labelled as such.

2. **What units the clock state carries.** See `CLOCK MODEL` below.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

import numpy as np

# ---------------------------------------------------------------------------
# CLOCK MODEL
# ---------------------------------------------------------------------------
#
# Simulation advances in ticks of TIME_TICK seconds.
#
# Each satellite has a nominal oscillator frequency f_nom and a realised
# frequency f_i. The engines store
#
#     drift_i = f_i / f_nom = 1 + eps_i
#
# where eps_i is the *fractional frequency error* (dimensionless, ~1e-9 for a
# 1 ppb oscillator). The quantity the experiment cares about is the timing
# error each clock accumulates relative to the ensemble, and over one tick that
# is
#
#     d(error_i) = eps_i * TIME_TICK          [seconds per tick]
#
# `clock_error_step()` below is that expression, and it is what every arm of
# the engine calls. It returns seconds, `fig_style.UNIT_SCALE` converts with
# 1e9, and the axis is labelled in nanoseconds, so the step, the scale and the
# label agree on one unit. `verify_units.py` checks that against the physical
# statement a reader can verify by hand: a 1 ppb oscillator accumulates 1 ns
# per second.

TIME_TICK = 0.001                  # s per simulation tick
SECONDS_TO_NS = 1.0e9              # s -> ns


def clock_error_step(drifts: np.ndarray, tick_s: float = TIME_TICK) -> np.ndarray:
    """Timing error accumulated per tick, in seconds.

    `drifts` is 1 + eps (as stored by the engines), so the common unity term is
    removed here: it is identical for every satellite and cancels in any
    deviation-from-reference metric, but carrying it wastes the float64
    mantissa on a value ~1e9 times larger than the signal.
    """
    return (np.asarray(drifts, dtype=float) - 1.0) * tick_s


# ---------------------------------------------------------------------------
# SYNCHRONIZATION ERROR METRICS
# ---------------------------------------------------------------------------


class SyncError(NamedTuple):
    """Per-tick synchronization error summary, in whatever unit `clocks` uses.

    Field order is deliberate: the first two positions reproduce the historic
    `(mean_abs_dev, max_abs_dev)` tuple exactly, so existing drivers indexing
    `d[0]` / `d[1]` keep working unchanged while new code reads the named
    fields.
    """

    mean_abs_dev: float     # mean |clock - mean(all clocks)|
    max_abs_dev: float      # max  |clock - mean(all clocks)|
    rmse_all: float         # RMS deviation from `reference`, all satellites
    rmse_normal: float      # RMS deviation from `reference`, healthy only
    reference: float        # the timescale everything above is measured against
    rmse_absolute: float    # RMS error against the ideal timescale, healthy only


def sync_error(clocks: np.ndarray,
               normal_mask: Optional[np.ndarray] = None) -> SyncError:
    """Summarize how tightly the constellation is synchronized.

    **Reference definition.** There is no external UTC in this simulation: the
    metric is internal relative synchronization, and some timescale has to be
    designated. When `normal_mask` is supplied the reference is the mean over
    *healthy* satellites, so a faulty population cannot drag the timescale it
    is being judged against; without a mask it is the mean over all. `rmse_all`
    and `rmse_normal` are both measured against that one reference, so they are
    directly comparable.

    `mean_abs_dev` and `max_abs_dev` are anchored to the all-satellite mean
    whether or not a mask is given, so they answer a different question from
    `rmse_normal` and are not interchangeable with it.
    """
    clocks = np.asarray(clocks, dtype=float)

    all_mean = float(clocks.mean())
    all_dev = np.abs(clocks - all_mean)

    if normal_mask is None:
        reference = all_mean
        normal = clocks
    else:
        normal_mask = np.asarray(normal_mask, dtype=bool)
        normal = clocks[normal_mask]
        # A run with every satellite faulty has no healthy timescale to use;
        # fall back rather than emit nan and poison the downstream average.
        reference = float(normal.mean()) if normal.size else all_mean

    dev_all = clocks - reference
    dev_normal = normal - reference

    # Absolute error against the ideal timescale. The engines store each clock
    # as its accumulated error, so a perfect clock is 0 and no external
    # reference has to be constructed.
    #
    # Why this is not redundant with rmse_normal: every other field here is a
    # deviation from an internal reference, so a common-mode shift, every
    # satellite moved by the same amount, is invisible to them. That is
    # exactly what a colluding set of cluster heads produces. A constellation
    # can be perfectly synchronized with itself and hours away from true time,
    # and only this field can tell.
    abs_err = normal if normal.size else clocks

    return SyncError(
        mean_abs_dev=float(all_dev.mean()),
        max_abs_dev=float(all_dev.max()),
        rmse_all=float(np.sqrt(np.mean(dev_all ** 2))),
        rmse_normal=float(np.sqrt(np.mean(dev_normal ** 2))) if normal.size else float('nan'),
        reference=reference,
        rmse_absolute=float(np.sqrt(np.mean(abs_err ** 2))),
    )


def fault_mask(satellites) -> np.ndarray:
    """Boolean mask, True where a satellite carries a malfunction drift bias.

    The engines each re-derived this inline, and only some of the simulate_*
    functions bothered, which is why the healthy-only metric could not be
    computed uniformly before. Faultiness is defined by a non-zero
    `drift_bias`, matching how initialize_satellites() marks a malfunctioning
    oscillator.
    """
    return np.array([s.get('drift_bias', 0.0) != 0.0 for s in satellites], dtype=bool)


def head_fault_mask(cluster_idx_list, member_faulty, explicit=None,
                    majority_frac=0.5) -> np.ndarray:
    """Which cluster heads behave Byzantinely, as a per-cluster boolean array.

    Two regimes, and conflating them is a flaw:

    - `explicit` given: the caller states which heads are faulty, independently
      of how many of their members are. This is the honest setup for a
      validator-fault experiment, because a cluster head's integrity is not a
      function of its members' oscillators.
    - `explicit` None: fall back on the historic rule, a head is faulty when
      more than `majority_frac` of its members are. Kept so existing sweeps stay
      comparable, but it *infers* validator state from member state, which is
      exactly what a Byzantine-fault claim may not do.
    """
    n_clusters = len(cluster_idx_list)
    if explicit is not None:
        mask = np.asarray(explicit, dtype=bool)
        if mask.shape != (n_clusters,):
            raise ValueError(f"explicit head mask must have {n_clusters} entries, "
                             f"got {mask.shape}")
        return mask
    member_faulty = np.asarray(member_faulty, dtype=bool)
    return np.array([member_faulty[idxs].mean() > majority_frac
                     for idxs in cluster_idx_list], dtype=bool)


def choose_faulty_heads(n_clusters, n_faulty_heads, rng) -> np.ndarray:
    """Pick `n_faulty_heads` cluster heads to be Byzantine, at random."""
    mask = np.zeros(n_clusters, dtype=bool)
    if n_faulty_heads > 0:
        mask[rng.choice(n_clusters, min(n_faulty_heads, n_clusters), replace=False)] = True
    return mask
