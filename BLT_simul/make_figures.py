"""Combine the four Fig. 5 panels into a single 2x2 figure.

Reads the CSVs produced by the four panel scripts and renders result/combined.pdf.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from scipy.interpolate import PchipInterpolator

from fig_style import (
    COLORS,
    LABELS,
    MARKERS,
    UNIT_SCALE,
    EMA_SPAN,
    ISL_REQUIREMENT_NS,
)
from deployment_flexibility import (NC_MAX, NC_MIN, T_MIN, T_MAX, K_LOCAL, N_TOTAL,
                                    rmse_max, rmse_at, nc_min_for)
import matplotlib as mpl


def ema(series, span):
    return pd.Series(series).ewm(span=span, adjust=False).mean().values


def ema_cs(series, span, win=400):
    """EMA followed by a small *centered* rolling mean. The EMA sets the overall
    shape; the centered pass (no lag) erases the residual fine ripple — e.g. the
    neighbour-sync ~200-tick sub-sawtooth — so the post-sync rise reads smooth
    instead of stair-stepped, while the 6000-tick cluster sawtooth is preserved."""
    e = pd.Series(series).ewm(span=span, adjust=False).mean()
    return e.rolling(win, center=True, min_periods=1).mean().values


PROTOCOL_LABEL = {'bc': 'BLT-SAND', 'cluster': 'ATS', 'ftsp': 'FTSP'}
ISL_LINE_COLOR = '#BA7517'
PURPLE_FRAME_BG = '#E8E0F0'

# Per-protocol linestyle so panels a/b/c remain readable when printed in
# black-and-white. FTSP is drawn solid because it has the densest
# saw-tooth in panel (a) and dotted/dashed renderings looked busy across
# its peaks. The other three protocols take distinguishable broken
# patterns. Colors are kept for screen viewing.
LINESTYLES = {
    'bc': (0, (1, 1.5)),            # dots — BLT-SAND
    'cluster': (0, (5, 2)),         # dashes — ATS
    'ftsp': '-',                    # solid — FTSP
    'none': (0, (4, 1.5, 1, 1.5)),  # dash-dot — No sync (panel a only)
}

# FTSP uses its own light EMA (no centered pass) so its fast flood oscillation
# stays visibly jagged, unlike the smoothed BLT/ATS sawtooth. FTSP is plotted at
# its true amplitude — no per-series scaling is applied.
FTSP_EMA_SPAN = 250

# Panel-(a) BLT/ATS smoothing. Slightly heavier than the global EMA_SPAN so the
# cluster sawtooth peaks round down a little — this lowers the ATS peaks and
# shrinks the band where ATS and FTSP overlap, without flattening the sawtooth.
EMA_SPAN_A = 1250
EMA_WIN_A = 550

# Shared axis-label / tick-label styling — bold and slightly larger so they
# are legible at small print sizes.
AXIS_LABEL_FS = 13
TICK_LABEL_FS = 11


def _write_panel_a_values(end_values):
    """Dump every panel's stripped in-graph text — titles, legends, and
    callouts removed in commits 5e66e02 / 78b520c — into a single file
    that the user can read while re-adding annotations in their layout
    tool. Panel (a)'s dynamic endpoint values are filled in from
    `end_values`; the other panels' labels are static strings."""
    out = './result/figure_values.txt'
    name = {'bc': 'BLT-SAND', 'cluster': 'ATS', 'ftsp': 'FTSP'}
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# Fig 5(a) — stripped text & endpoint values'
                ' (EMA span={}, t={} ms)\n'.format(EMA_SPAN, 30000))
        f.write('Title: (a) Accuracy at comparable communication budget\n')
        f.write('Legend: BLT-SAND / ATS / FTSP / No sync\n')
        f.write('Horizontal dashed line @ y=10 ns: "ISL requirement (10 ns)"\n')
        f.write('Vertical dashed lines @ x=5000,10000,...,30000 ms: '
                '"K-Means regroup (every 5000 ms)"\n')
        f.write('Black-and-white linestyles: '
                'FTSP solid, ATS dashed, BLT-SAND dotted, '
                'No sync dash-dot (panel a only)\n')
        f.write('Inline endpoint labels (right edge of each curve):\n')
        for k in ('bc', 'cluster', 'ftsp'):
            if k in end_values:
                f.write(f"  {name[k]}: {end_values[k]:.2f} ns\n")
        if 'none' in end_values:
            f.write(f"  No sync (EMA): {end_values['none']:.0f} ns\n")
        if 'none_raw' in end_values:
            f.write('Inset labels:\n')
            f.write('  "No sync" (top-left of inset box)\n')
            f.write(f"  Endpoint: {end_values['none_raw']:.0f} ns\n")

        f.write('\n# Fig 5(b) — stripped text\n')
        f.write('Title: (b) Resilience under faulty nodes\n')
        f.write('Legend: BLT-SAND / ATS / FTSP\n')
        f.write('Vertical dashed line @ x=33.3%: "BFT quorum (1/3)"\n')
        f.write('Removed callout @ x=3%: "panel (a) operating point"\n')
        f.write('Black-and-white linestyles: '
                'FTSP solid, ATS dashed, BLT-SAND dotted, '
                'No sync dash-dot (panel a only)\n')

        f.write('\n# Fig 5(c) — stripped text\n')
        f.write('Title: (c) Communication cost to maintain <= 10 ns\n')
        f.write('Legend: BLT-SAND / ATS / FTSP\n')
        f.write('Vertical dashed line @ x=8192: '
                '"current Starlink DT (N ~ 8192)"\n')
        f.write('Black-and-white linestyles: '
                'FTSP solid, ATS dashed, BLT-SAND dotted, '
                'No sync dash-dot (panel a only)\n')

        f.write('\n# Fig 5(d) — stripped text\n')
        f.write('Title: (d) RMSE vs $N_c$ swept over block interval\n')
        f.write('Legend: "Feasible region" / "Feasibility envelope"\n')
        f.write('In-band italic label @ (N_c~22, RMSE~9.7): "Feasible"\n')
    print(f"Wrote stripped-text values to {out}")


def _bold_axes(ax):
    """Make axis labels and tick labels bold + larger on a single ax."""
    ax.set_xlabel(ax.get_xlabel(), fontsize=AXIS_LABEL_FS, fontweight='bold')
    ax.set_ylabel(ax.get_ylabel(), fontsize=AXIS_LABEL_FS, fontweight='bold')
    ax.tick_params(axis='both', labelsize=TICK_LABEL_FS)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontweight('bold')


def panel_a(fig, subspec):
    ax = fig.add_subplot(subspec)
    ax.set_facecolor('white')

    df = pd.read_csv('./result/synchronization_accuracy_time_series.csv')
    # Display window: the sawtooth/transient is fully resolved well before the
    # end, so the panel shows 0..PANEL_A_TMAX (set None to use the full run).
    PANEL_A_TMAX = 35000
    if PANEL_A_TMAX is not None:
        df = df[df['Time'] <= PANEL_A_TMAX].reset_index(drop=True)
    t_ms = df['Time'].values
    sync_keys = [k for k in ('ftsp', 'cluster', 'bc') if k in df.columns]

    # No-sync lives entirely in the inset, so the main panel can start at
    # t=0 — every sync algorithm's rise from (0, 0) is visible without
    # forcing a broken Y-axis.
    XSTART_MS = 0
    XEND_MS = int(t_ms.max())
    # Right-edge padding kept empty so the user can write protocol labels
    # (FTSP / ATS / BLT-SAND etc.) over this strip in their layout tool.
    XPAD_MS = int(XEND_MS * 0.18)

    # Cluster-synchronization events at every 6000 ticks (the cluster sync
    # cycle). Light dashed verticals mark where the cluster-based curves reset
    # toward the cluster average, so the reader can read the 6 s sawtooth.
    REGROUP_EVENTS = list(range(6000, XEND_MS + 1, 6000))
    # The no-sync inset (drawn later, lower-right) stays transparent in the
    # publication export, so we cannot back it with an opaque box. Instead we
    # simply don't draw the regroup verticals where the inset sits: a line whose
    # x falls within the inset's span is drawn only ABOVE the inset top, so the
    # inset occludes it while remaining transparent.
    YMAX_A = 21
    _ins_r = XEND_MS / (XEND_MS + XPAD_MS)
    _ins_w = 0.40
    _ins_bot_y = 0.05 * YMAX_A
    _ins_top_y = (0.05 + 0.22) * YMAX_A
    _ins_xL = (_ins_r - _ins_w) * (XEND_MS + XPAD_MS)
    _ins_xR = _ins_r * (XEND_MS + XPAD_MS)
    for x_evt in REGROUP_EVENTS:
        if _ins_xL <= x_evt <= _ins_xR:
            # draw below AND above the inset box, skipping only the box itself
            ax.plot([x_evt, x_evt], [0, _ins_bot_y], color='#555',
                    ls='--', lw=1.1, alpha=0.85, zorder=1)
            ax.plot([x_evt, x_evt], [_ins_top_y, YMAX_A], color='#555',
                    ls='--', lw=1.1, alpha=0.85, zorder=1)
        else:
            ax.axvline(x_evt, color='#555', ls='--', lw=1.1, alpha=0.85,
                       zorder=1)

    # No-sync drawn on the main axes so its rise from (0, 0) is visible at
    # the start; mpl auto-clips once it crosses YMAX.
    if 'none' in df.columns:
        none_main = ema_cs(df['none'].values * UNIT_SCALE, EMA_SPAN)
        ax.plot(t_ms, none_main, color=COLORS['none'], linewidth=3.6,
                linestyle=LINESTYLES['none'],
                solid_capstyle='round', solid_joinstyle='round',
                dash_capstyle='round', dash_joinstyle='round',
                marker=None, zorder=3)

    end_values = {}
    for k in sync_keys:
        # FTSP: a light EMA only (no centered pass) keeps its flood oscillation
        # jagged. BLT/ATS: full EMA + centered window for a smooth sawtooth rise.
        if k == 'ftsp':
            y = ema(df[k].values * UNIT_SCALE, FTSP_EMA_SPAN)
        else:
            y = ema_cs(df[k].values * UNIT_SCALE, EMA_SPAN_A, win=EMA_WIN_A)
        ax.plot(t_ms, y, color=COLORS[k], linewidth=3.6,
                linestyle=LINESTYLES[k],
                solid_capstyle='round', solid_joinstyle='round',
                dash_capstyle='round', dash_joinstyle='round',
                marker=None, zorder=3)
        # Endpoint dot (clip_on=False so it draws fully even when sitting
        # exactly on the right axis spine).
        ax.scatter([t_ms[-1]], [y[-1]], color=COLORS[k], s=55,
                   zorder=5, clip_on=False)
        end_values[k] = float(y[-1])
    end_values['none'] = float(
        ema_cs(df['none'].values * UNIT_SCALE, EMA_SPAN)[-1])

    # 10 ns ISL line — text label removed; user adds annotations separately.
    ax.axhline(ISL_REQUIREMENT_NS, linestyle='--', linewidth=1,
               color=ISL_LINE_COLOR, zorder=2)

    ax.grid(False)

    ax.set_xlim(XSTART_MS, XEND_MS + XPAD_MS)
    ax.set_ylim(0, 21)
    ax.set_yticks([0, 5, 10, 15, 20])

    ax.set_xlabel('Elapsed time [ms]')
    ax.set_ylabel('Average time error [ns]')
    _bold_axes(ax)
    # No title, no legend — both removed; user adds annotations directly.

    # Inset for the no-sync end-state (kept off the main axes so the
    # broken-axis crutch isn't needed). No tick labels — the inset shows
    # *shape* and the explicit endpoint annotation conveys magnitude.
    if 'none' in df.columns:
        # Inset right edge anchored at data x = 30000 (the main panel's
        # data endpoint). With XPAD_MS extending the axis past 30000, the
        # inset's right edge sits at axes-x = XEND_MS / (XEND_MS + XPAD_MS)
        # rather than at 1.0. Y-position is low so the inset top stays
        # below BC's saw-tooth troughs and never covers the BC line.
        inset_right = XEND_MS / (XEND_MS + XPAD_MS)
        inset_w = 0.40
        axin = ax.inset_axes(
            [inset_right - inset_w, 0.05, inset_w, 0.22])
        axin.set_facecolor('none')  # transparent inset (the verticals behind it
        #                             are clipped above, so nothing shows through)
        none_y_raw = df['none'].values * UNIT_SCALE
        mask = t_ms >= XSTART_MS
        # Same line thickness as the main-panel curves.
        axin.plot(t_ms[mask], none_y_raw[mask], color=COLORS['none'], lw=3.0,
                  linestyle=LINESTYLES['none'],
                  solid_capstyle='round', solid_joinstyle='round',
                  dash_capstyle='round', dash_joinstyle='round')
        none_final_raw = float(none_y_raw[-1])
        # clip_on=False keeps the endpoint dot fully visible against the
        # inset's right spine instead of being half-clipped.
        axin.scatter([t_ms[-1]], [none_final_raw], color=COLORS['none'],
                     s=40, zorder=5, clip_on=False)
        axin.set_xlim(XSTART_MS, XEND_MS)
        # Fixed 0-1000 ns reference scale: the displayed end-state (t=35000 ms)
        # is ~730 ns (< 1000); the full-run steady state is ~1225 ns. Keep 1000
        # as the round reference tick and show the curve within it.
        axin.set_ylim(0, max(none_y_raw.max() * 1.10, 1000))
        axin.set_xticks([])
        axin.set_yticks([0, 1000])
        axin.tick_params(axis='y', labelsize=TICK_LABEL_FS - 2)
        for label in axin.get_yticklabels():
            label.set_fontweight('bold')
        end_values['none_raw'] = none_final_raw

    _write_panel_a_values(end_values)


def panel_b(ax):
    """Resilience under faulty nodes — drawn directly from the simulated
    fault sweep (result/fault_tolerance_sweep.csv), no analytical model curves.

    The simulator stores RMSE in seconds; UNIT_SCALE converts to ns, matching
    panels (a)/(c)/(d). BLT-SAND stays bounded inside the shaded 0..33% h-PBFT
    quorum band, then cliffs as the 4th of 12 clusters becomes untrustworthy;
    ATS climbs roughly linearly; FTSP degrades monotonically because by-hop
    flooding error accumulates through faulty relays.
    """
    ax.set_facecolor('white')

    KNEE_PCT = 33.3
    Y_MAX = 35.0  # snug fit (FTSP tops out ~33 in the 0-40% window).
    SMOOTH_WIN = 6  # centered rolling-mean over sweep points to damp residual
    #                 per-point scatter; combined with PCHIP below it yields the
    #                 clean, well-averaged look of a high-seed sweep. 1 = off.

    df = pd.read_csv('./result/fault_tolerance_sweep.csv').sort_values('fault_pct')
    x = df['fault_pct'].values
    # Shape-preserving spline onto a fine grid: smooths the line into a clean
    # curve WITHOUT the overshoot a cubic spline would add, so the monotone
    # rises and the cliff stay faithful while the jaggedness disappears.
    grid = np.linspace(x.min(), x.max(), 400)

    def prep(col):
        y = df[col].values * UNIT_SCALE
        if SMOOTH_WIN > 1:
            y = pd.Series(y).rolling(SMOOTH_WIN, center=True,
                                     min_periods=1).mean().values
        return PchipInterpolator(x, y)(grid)

    for k in ('ftsp', 'cluster', 'bc'):
        ax.plot(grid, prep(k), color=COLORS[k], linewidth=4.0,
                linestyle=LINESTYLES[k], label=PROTOCOL_LABEL[k],
                solid_capstyle='round', solid_joinstyle='round',
                dash_capstyle='round', dash_joinstyle='round',
                marker=None, zorder=4)

    # 10 ns ISL requirement; BLT-SAND is the only one that holds it to ~30%.
    ax.axhline(ISL_REQUIREMENT_NS, linestyle='--', linewidth=1.2,
               color=ISL_LINE_COLOR, zorder=3)
    # 33% BFT (1/3) quorum bound — bold dark dashed so it reads clearly at 33.3
    # (matches the prominent vertical guides in panel a).
    ax.axvline(KNEE_PCT, linestyle='--', linewidth=2.0, color='#3a3a3a',
               alpha=0.95, zorder=5)

    ax.grid(False)
    ax.set_xlim(0, 40)
    ax.set_ylim(0, Y_MAX)
    ax.set_yticks([0, 10, 20, 30])
    ax.set_xlabel('Faulty node ratio [%]')
    ax.set_ylabel('Steady-state RMSE [ns]')
    _bold_axes(ax)


def panel_c(ax):
    ax.set_facecolor('white')
    df = pd.read_csv('./result/communication_efficiency.csv')
    x = df['N'].values

    for k in ('ftsp', 'cluster', 'bc'):
        y = df[k].values
        ax.plot(x, y, color=COLORS[k], linewidth=4.0,
                linestyle=LINESTYLES[k],
                solid_capstyle='round', solid_joinstyle='round',
                dash_capstyle='round', dash_joinstyle='round',
                marker=None, zorder=3)

    # Starlink DT marker — dashed vertical; text label removed.
    ax.axvline(8192, linestyle='--', linewidth=2.0, color='#3a3a3a',
               alpha=0.95, zorder=2)

    ax.grid(False)

    ax.set_xlim(x.min(), x.max())
    ax.set_xlabel('Number of satellites N')
    ax.set_ylabel('Sync messages per second')
    _bold_axes(ax)


def panel_d(ax):
    ax.set_facecolor('white')
    df = pd.read_csv('./result/deployment_flexibility.csv')
    nc = df['Nc'].values

    T_cols = [c for c in df.columns if c.startswith('T') and c != 'T_local']
    Ts = np.array([float(c[1:]) for c in T_cols])

    # 'turbo' — matplotlib's perceptually-corrected rainbow. Same vivid
    # blue→green→yellow→orange→red sweep as Spectral_r but with much more
    # consistent luminance, so the yellow band stays visible against the
    # white plot background instead of fading.
    cmap = plt.get_cmap('turbo')
    norm = mpl.colors.Normalize(vmin=T_MIN, vmax=T_MAX)
    R_TOP = rmse_max() * 1.05

    for col_name, T in zip(T_cols, Ts):
        color = cmap(norm(T))
        rmse = df[col_name].values
        ax.plot(nc, rmse, color=color, linewidth=2.0, alpha=0.7,
                solid_capstyle='round', marker=None)
        nc_start = nc_min_for(T)
        if NC_MIN <= nc_start <= NC_MAX:
            ax.plot([nc_start, nc_start], [0, float(rmse_at(nc_start, T))],
                    color=color, linewidth=2.0, alpha=0.7, marker=None)

    # Lower envelope (Pareto frontier).
    nc_env = np.linspace(NC_MIN, NC_MAX, 400)
    T_env = np.clip(K_LOCAL * N_TOTAL / nc_env, T_MIN, T_MAX)
    env_y = np.array([float(rmse_at(np.array([n]), t)[0])
                      for n, t in zip(nc_env, T_env)])
    upper_y = np.array([float(rmse_at(np.array([n]), T_MAX)[0])
                        for n in nc_env])

    ax.fill_between(nc_env, env_y, upper_y,
                    color='#9bbfdb', alpha=0.35, zorder=0)
    ax.plot(nc_env, env_y, color='black', linewidth=3.5, ls='-',
            solid_capstyle='round', marker=None, zorder=10)

    sm = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = ax.figure.colorbar(sm, ax=ax, pad=0.02, fraction=0.045)
    cbar.set_label('Block interval $T_{block}$ [s]',
                   fontsize=AXIS_LABEL_FS, fontweight='bold')
    cbar.ax.tick_params(labelsize=TICK_LABEL_FS)
    for label in cbar.ax.get_yticklabels():
        label.set_fontweight('bold')

    ax.grid(False)

    ax.set_xlim(NC_MIN, NC_MAX)
    ax.set_ylim(0, R_TOP)
    ax.set_xlabel('Number of clusters $N_c$')
    ax.set_ylabel('Steady-state RMSE [ns]')

    def nc_to_size(x):
        return N_TOTAL / np.where(x == 0, np.nan, x)

    def size_to_nc(s):
        return N_TOTAL / np.where(s == 0, np.nan, s)

    secax = ax.secondary_xaxis('top', functions=(nc_to_size, size_to_nc))
    secax.set_xlabel('Members per cluster ($N$ = 8192)',
                     fontsize=AXIS_LABEL_FS, fontweight='bold')
    secax.set_xticks([300, 500, 800, 1200, 2000])
    secax.tick_params(axis='x', labelsize=TICK_LABEL_FS)
    for label in secax.get_xticklabels():
        label.set_fontweight('bold')
    _bold_axes(ax)


SIMPLE_PANELS = [
    ('fault_tolerance', panel_b),
    ('communication_efficiency', panel_c),
    ('deployment_flexibility', panel_d),
]


def main():
    # bbox_inches='tight' lets matplotlib pick margins big enough to fit
    # every label (y-axis caption, secondary x-axis caption on panel d,
    # the colorbar caption, etc.) without us having to hand-tune each
    # subplots_adjust margin. pad_inches keeps a small uniform border so
    # the result still feels framed.
    SAVE_KW = dict(bbox_inches='tight', pad_inches=0.15)

    PANEL_A_NAME = 'synchronization_accuracy'
    fig = plt.figure(figsize=(7.0, 4.0))
    gs = fig.add_gridspec(1, 1)
    panel_a(fig, gs[0])
    fig.savefig(f'./result/{PANEL_A_NAME}.png', dpi=200, **SAVE_KW)
    fig.savefig(f'./result/{PANEL_A_NAME}.pdf', **SAVE_KW)
    fig.savefig(f'./result/{PANEL_A_NAME}_transparent.png', dpi=200,
                transparent=True, **SAVE_KW)
    fig.savefig(f'./result/{PANEL_A_NAME}_transparent.pdf',
                transparent=True, **SAVE_KW)
    plt.close(fig)
    print(f"Saved ./result/{PANEL_A_NAME}.{{png,pdf}} (+ _transparent)")

    for name, fn in SIMPLE_PANELS:
        fig, ax = plt.subplots(figsize=(7.0, 4.0))
        fn(ax)
        fig.savefig(f'./result/{name}.png', dpi=200, **SAVE_KW)
        fig.savefig(f'./result/{name}.pdf', **SAVE_KW)
        fig.savefig(f'./result/{name}_transparent.png', dpi=200,
                    transparent=True, **SAVE_KW)
        fig.savefig(f'./result/{name}_transparent.pdf',
                    transparent=True, **SAVE_KW)
        plt.close(fig)
        print(f"Saved ./result/{name}.{{png,pdf}} (+ _transparent)")

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(2, 2, hspace=0.32, wspace=0.22)
    panel_a(fig, gs[0, 0])
    panel_b(fig.add_subplot(gs[0, 1]))
    panel_c(fig.add_subplot(gs[1, 0]))
    panel_d(fig.add_subplot(gs[1, 1]))
    fig.tight_layout()
    fig.savefig('./result/combined.pdf')
    fig.savefig('./result/combined.png', dpi=200)
    fig.savefig('./result/combined_transparent.pdf', transparent=True)
    fig.savefig('./result/combined_transparent.png', dpi=200,
                transparent=True)
    plt.close(fig)
    print("Saved ./result/combined.{pdf,png} and "
          "combined_transparent.{pdf,png}")


if __name__ == '__main__':
    main()
