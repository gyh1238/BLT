"""Render every result that can be a chart or a table.

Reads the CSVs and logs the experiments wrote and writes one PNG + PDF per panel to
result/evaluation/.
Where an input is missing the figure is skipped with a note.

The style is the manuscript's (fig_style: bold labels, no grid, per-protocol
linestyles and bar hatches for black-and-white print, one 7.0 x 4.0 in panel per
file, no titles). Each panel's reading belongs in the caption where it is used.
A figure that holds more than one panel is saved as <figure>_a, _b, ...

Run:  python figures/evaluation_panels.py             # no titles (caption supplied where used)
      python figures/evaluation_panels.py --titles    # titles on, for a quick look
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

import argparse
import os
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fig_style import (COLORS, MARKERS, LINESTYLES, ISL_LINE_COLOR, ISL_REQUIREMENT_NS,
                       TICK_LABEL_FS, SAVE_KW, PNG_DPI, PANEL_SIZE, bold_axes)

# Bold by default. These panels are reduced to a quarter or a half of the text width
# in the letter, where thin type closes up; rather than add fontweight to every call,
# the default weight is bold and the explicit sizes below are raised to match.
plt.rcParams.update({
    'font.weight': 'bold',
    'axes.labelweight': 'bold',
    'axes.titleweight': 'bold',
    'mathtext.default': 'bf',   # N$^2$ and the like, so exponents match their line
})

OUT = 'result/evaluation'
C = {'bc': COLORS['bc'], 'cluster': COLORS['cluster'], 'ftsp': COLORS['ftsp'], 'none': COLORS['none']}
L = {'bc': 'BLT-SAND', 'cluster': 'ATS', 'ftsp': 'FTSP', 'none': 'No sync'}
# the ablation arm name in the result CSVs -> the name the reader sees (17, 23)
SHOW = {'BLT-SAND (published)': 'BLT-SAND (proposed)'}
M = MARKERS
GREY = '#9aa0a6'
LEGEND_FS = 13
ANNOT_FS = 12
TITLE_FS = 13
LW = 2.4
TITLES = False
made, skipped = [], []


def title(ax, text, **kw):
    """Panel titles are off by default; the reading belongs in the caption."""
    if TITLES:
        ax.set_title(text, **kw)


def panel(size=PANEL_SIZE):
    return plt.subplots(figsize=size)


# Panels that print much smaller than the rest where they are used, and the factor
# each one's type is multiplied by. KEEP_XTICKS names those whose x ticks are a
# dense numeric run: they hold their size while the rest grows, because they are
# the one thing a reader does not have to read closely, the curve carries the
# shape, and they are what collides first.
TEXT_SCALE = {'02_timestamp_jitter': 1.45, '15_who_votes': 1.55, '16_block_content': 1.20,
              '17_isl_outage': 1.45, '18_collection_time': 1.45}
KEEP_XTICKS = {'02_timestamp_jitter', '17_isl_outage'}


def _scale_text(fig, k, keep_xticks=False):
    """Multiply every piece of type in `fig` by k.

    Done here rather than at each call site because a panel's sizes come from four
    places, bold_axes, the legend, the annotations and the title, and scaling
    them at the end is one change instead of four per panel.
    """
    for ax in fig.axes:
        items = [ax.title, ax.xaxis.label, ax.yaxis.label]
        if not keep_xticks:
            items += list(ax.get_xticklabels())
        items += list(ax.get_yticklabels()) + list(ax.texts)
        if ax.get_legend() is not None:
            items += list(ax.get_legend().get_texts())
            if ax.get_legend().get_title() is not None:
                items.append(ax.get_legend().get_title())
        for t in items:
            t.set_fontsize(t.get_fontsize() * k)
    for t in fig.texts:
        t.set_fontsize(t.get_fontsize() * k)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    for ax in fig.axes:
        if ax.axison:
            bold_axes(ax)
    if name in TEXT_SCALE:
        _scale_text(fig, TEXT_SCALE[name], keep_xticks=name in KEEP_XTICKS)
    fig.savefig(os.path.join(OUT, name + '.png'), dpi=PNG_DPI, **SAVE_KW)
    fig.savefig(os.path.join(OUT, name + '.pdf'), **SAVE_KW)
    plt.close(fig)
    made.append(name)


def need(path):
    if os.path.exists(path):
        return True
    skipped.append(path)
    return False


def proto(a, **kw):
    """Line style of one protocol: its color, black-and-white linestyle and marker."""
    return dict(dict(color=C[a], ls=LINESTYLES[a], marker=M[a], lw=LW, ms=7, label=L[a],
                     dash_capstyle='round'), **kw)


def isl_line(ax, label=True):
    ax.axhline(ISL_REQUIREMENT_NS, color=ISL_LINE_COLOR, ls='--', lw=1.2)
    if label:
        ax.text(ax.get_xlim()[0], ISL_REQUIREMENT_NS, ' 10 ns ISL', va='bottom', ha='left',
                fontsize=ANNOT_FS, color=ISL_LINE_COLOR)


def legend(ax, **kw):
    ax.legend(**dict(dict(fontsize=LEGEND_FS, frameon=False), **kw))


# --------------------------------------------------------------------- 01 time series
def f01():
    p = 'result/runs/timeseries.csv'
    if not need(p):
        return
    df = pd.read_csv(p)
    t = df['t_ms'] / 1000
    # The same run under the manuscript's Fig. 4(a) smoothing, so the panel the
    # paper carries can be read against the one here. The manuscript's copy is
    # assembled separately and without a legend; this is the evaluation copy, so
    # it keeps the legend and is saved as PNG and PDF like the rest.
    w = df[df.t_ms <= 35000]
    tm = w.t_ms.values
    sm = lambda x, span: pd.Series(x).ewm(span=span, adjust=False).mean().values
    sm_cs = lambda x, span, win: (pd.Series(sm(x, span))
                                  .rolling(win, center=True, min_periods=1).mean().values)
    fig, ax = panel((7.0, 4.0))
    for a in ('ftsp', 'cluster', 'bc'):
        y = sm(w[a].values, 140) if a == 'ftsp' else sm_cs(w[a].values, 650, 250)
        ax.plot(tm, y, **proto(a, marker=None))
        ax.scatter([tm[-1]], [y[-1]], color=C[a], s=40, zorder=6)
    for x_evt in range(6000, int(tm.max()) + 1, 6000):
        ax.axvline(x_evt, color='#555', ls='--', lw=1.1, alpha=0.8, zorder=1)
    isl_line(ax, label=False)
    ax.set_xlim(0, tm.max())
    ax.set_ylim(0, 21)
    ax.set_xlabel('Elapsed time [ms]')
    ax.set_ylabel('Average time error [ns]')
    title(ax, 'Fig. 4(a) under the manuscript smoothing')
    legend(ax, loc='upper right', ncol=3)
    ins = ax.inset_axes([0.52, 0.06, 0.38, 0.24])
    ins.plot(tm, sm_cs(w.none_all.values, 650, 250), color=C['none'], lw=LW,
             ls=LINESTYLES['none'])
    ins.scatter([tm[-1]], [w.none_all.values[-1]], color=C['none'], s=30, clip_on=False)
    ins.set_xlim(0, tm.max())
    ins.set_ylim(0, 300)
    ins.set_xticks([])
    ins.set_yticks([0, 262])
    ins.tick_params(labelsize=TICK_LABEL_FS - 3)
    for lab in ins.get_yticklabels():
        lab.set_fontweight('bold')
    ins.text(0.02, 1.03, 'No sync (all satellites)', transform=ins.transAxes,
             fontsize=ANNOT_FS - 1, fontweight='bold', va='bottom')
    save(fig, '01_accuracy_over_time')


# --------------------------------------------------------------------- 03 parameters
def f03():
    # The sweep documented in FIGURES.md: sensitivity_sweep.py writes one row
    # per jitter value with a column per scheme.
    sweep = 'result/fit/jitter_sweep.csv'
    if not need(sweep):
        return
    d = pd.read_csv(sweep)
    if 'jitter_ns' in d.columns and 'alg' in d.columns:
        w = d.pivot_table(index='jitter_ns', columns='alg', values='rmse_ns')
        pts = np.column_stack([w.index.values,
                               w['bc'].values, w['cluster'].values, w['ftsp'].values])
    else:
        d = d.sort_values('jitter_s')
        pts = np.column_stack([d['jitter_s'].values * 1e9,
                               d['bc'].values, d['cluster'].values, d['ftsp'].values])
    fig, ax = panel()
    for k, a in enumerate(('bc', 'cluster', 'ftsp')):
        ax.plot(pts[:, 0], pts[:, k + 1], **proto(a))
    for y, a in zip((8.8, 14.4, 17.2), ('bc', 'cluster', 'ftsp')):
        ax.axhline(y, color=C[a], ls=':', lw=1.2)
    ax.set_xlabel('Timestamp jitter [ns] (100 MHz counter, 1 ppb)')
    ax.set_ylabel('RMSE [ns] (N=8,192)')
    title(ax, 'The timestamp tier sets BLT-SAND (N=8,192)')
    legend(ax, ncol=3, loc='upper left')
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    save(fig, '02_timestamp_jitter')



# --------------------------------------------------------------------- 04 fault axes
def f04():
    pm, ph = 'result/runs/fault_axes_member.csv', 'result/runs/fault_axes_head.csv'
    if not (need(pm) and need(ph)):
        return
    m, h = pd.read_csv(pm), pd.read_csv(ph)
    fig, ax = panel()
    for a in ('bc', 'cluster', 'ftsp'):
        ax.plot(100 * m.faulty_frac, m[a], **proto(a))
    isl_line(ax, label=False)
    ax.set_xlabel('Faulty satellites, scattered [% of all]')
    ax.set_ylabel('RMSE [ns]')
    title(ax, 'Member faults (heads honest)')
    ax.set_ylim(0, 30)
    legend(ax, ncol=3, loc='upper left')
    save(fig, '03_member_faults')


# --------------------------------------------------------------------- 07 ledger + intermittent
def f07():
    p1, p2 = 'result/runs/ledger_history.csv', 'result/runs/intermittent_faults.csv'
    if not (need(p1) and need(p2)):
        return
    lh = pd.read_csv(p1)
    lh = lh[lh.arm != 'ATS']
    style = {'BLT + ledger': dict(color=C['bc'], ls=LINESTYLES['bc'], marker='o'),
             'BLT, no ledger': dict(color='#9467bd', ls=LINESTYLES['cluster'], marker='s')}
    for name, col, scale, ylabel, heading in (
            ('06_head_selection', 'liars', 1, 'Faulty heads per round',
             'Heads chosen from the ledger record'),
            ('07_commit_rate', 'commit', 100, 'BLT commit rate [%]',
             '...keeps consensus available')):
        fig, ax = panel()
        if col == 'liars':
            # Without a ledger the head is the satellite nearest the cluster centroid,
            # chosen without regard to the faults, so the count is Binomial(12, frac):
            # the expectation is the straight line 12 x frac, and one run scatters
            # around it with sd ~1.5 heads. The line is drawn so the points can be read
            # against it instead of looking like a curve of their own.
            xs = np.linspace(0, 100 * lh.faulty_frac.max(), 50)
            ax.plot(xs, 12 * xs / 100, color=GREY, ls=(0, (2, 2)), lw=1.6,
                    label='12 x faulty fraction (no selection)')
        for arm, g in lh.groupby('arm'):
            ax.plot(100 * g.faulty_frac, scale * g[col], lw=LW, ms=7, label=arm, dash_capstyle='round',
                    **style[arm])
        ax.set_xlabel('Faulty satellites, scattered [%]')
        ax.set_ylabel(ylabel)
        title(ax, heading)
        if col == 'commit':
            ax.set_ylim(0, 105)
            legend(ax, loc='lower left')
        else:
            legend(ax, loc='upper left')
        save(fig, name)

    im = pd.read_csv(p2)
    im = im[im.arm != 'ATS']
    arms = ['BLT, full history', 'BLT, latest only', 'BLT, no ledger']
    # 64 seeds; the latest-only and no-ledger bars match the analytic 12 q f(1-q)/(1-fq)
    # and 12 f q, within the seed spread.
    colors = {'BLT, full history': C['bc'], 'BLT, latest only': '#ff7f0e', 'BLT, no ledger': '#9467bd'}
    hatches = {'BLT, full history': '', 'BLT, latest only': '//', 'BLT, no ledger': '..'}
    fr = sorted(im.intermittent_frac.unique())
    fig, ax = panel()
    w = 0.8 / len(arms)
    for j, a in enumerate(arms):
        g = [im[(im.intermittent_frac == f) & (im.arm == a)].iloc[0] for f in fr]
        xs = np.arange(len(fr)) + (j - 1) * w
        v = np.array([r.liars for r in g])
        ax.bar(xs, v, w, color=colors[a], label=a, hatch=hatches[a], edgecolor='black', linewidth=0.6)
        for x, val in zip(xs, v):
            ax.text(x, val + 0.03, f'{val:.2f}', ha='center', va='bottom', fontsize=ANNOT_FS - 1)
    ax.set_xticks(np.arange(len(fr)))
    ax.set_xticklabels([f'{100 * f:.0f}% intermittent' for f in fr])
    for k, f in enumerate(fr):
        for j, a in enumerate(arms):
            c = im[(im.intermittent_frac == f) & (im.arm == a)].commit.iloc[0]
            ax.text(k + (j - 1) * w, -0.35, f'{100 * c:.0f}%', ha='center', fontsize=ANNOT_FS,
                    fontweight='bold', color=colors[a])
    # the row of percentages is the commit rate; say so where it cannot be taken for a bar's value
    ax.text(0.98, 0.96, '% below the bars: commit rate', transform=ax.transAxes, ha='right', va='top',
            fontsize=ANNOT_FS, style='italic')
    ax.set_ylabel('Faulty heads per round')
    title(ax, 'Intermittent faults (commit % below)')
    legend(ax, loc='upper left')
    top = max(3, ax.get_ylim()[1]) * 1.15
    ax.set_ylim(-0.6, top)
    ax.set_yticks(np.arange(0, top, 0.5))
    save(fig, '08_intermittent_faults')


# --------------------------------------------------------------------- 08 chain
def parse_chain():
    rows = []
    for n in (4, 8, 12, 16):
        p = f'result/chain/chain_n{n}.log' if n != 12 else 'result/chain/chain_n12_full.log'
        if not os.path.exists(p):
            continue
        txt = open(p, encoding='utf-8', errors='replace').read()
        m = re.search(r'SUMMARY n=(\d+) lat_med=([\d.]+) interval=([\d.]+) cpu_per_block_node=([\d.]+) rss=(\d+) '
                      r'p2p_kib_per_block_node=([\d.]+)', txt)
        blocks = [int(x) for x in re.findall(r'^\s+\d+\s+[\d.]+\s+\d+\s+(\d+)\s+\d+\s*$', txt, re.M)]
        txs = [int(x) for x in re.findall(r'^\s+\d+\s+[\d.]+\s+(\d+)\s+\d+\s+\d+\s*$', txt, re.M)]
        lats = [float(x) for x in re.findall(r'^\s+\d+\s+([\d.]+)\s+\d+\s+\d+\s+\d+\s*$', txt, re.M)]
        if m:
            rows.append(dict(n=int(m[1]), lat=float(m[2]), interval=float(m[3]), cpu=float(m[4]), rss=int(m[5]),
                             p2p=float(m[6]), block=np.median(blocks), tx=np.median(txs),
                             lat_lo=min(lats) if lats else float(m[2]),
                             lat_hi=max(lats) if lats else float(m[2]),
                             lat_mean=(sum(lats) / len(lats)) if lats else float(m[2]),
                             lat_n=len(lats)))
    return pd.DataFrame(rows)


def f08():
    p = 'result/chain/chain_n12_full.log'
    if not need(p):
        return
    txt = open(p, encoding='utf-8', errors='replace').read()
    tam = re.findall(r'^(rollback|replay|forged time|duplicate head|outsider)\s+(\d+)\s+(\S+)\s+(\d+/\d+)\s*$', txt, re.M)
    if tam:
        names = {'rollback': 'Roll reference time back', 'replay': 'Reuse a committed epoch id',
                 'forged time': 'Forge reference time (+60 s)', 'duplicate head': 'Report one head twice',
                 'outsider': 'Proposer outside the delegate set'}
        # The error the chain returned, by name and code (x/blt/types/errors.go), and no
        # constant columns: every attempt left the history untouched and all twelve nodes
        # agreed, which the caption states once instead of repeating it on every row.
        err = {'1101': 'ErrProposerNotDelegate', '1112': 'ErrRefTimeSkew',
               '1113': 'ErrDuplicateClusterHead', '1114': 'ErrEpochIdNotAdvancing'}
        cells = [[names[a], 'committed' if c == '0' else f'{err.get(c, "code")} ({c})']
                 for a, c, h, n in tam]
        _table(cells, ['Tamper attempt', 'Rejected with'], [0.52, 0.48],
               '12_tamper_attempts', 'Tamper attempts on a 12-validator chain',
               width=12.5, fontsize=TICK_LABEL_FS)


def f09():
    d = parse_chain()
    if d.empty:
        skipped.append('result/chain/*.log')
        return
    nfit = np.linspace(2, 18, 50)
    A = np.vstack([d.n, d.n ** 2]).T
    c, *_ = np.linalg.lstsq(A, d.p2p, rcond=None)
    k = np.polyfit(d.n, d.block - d.tx, 1)
    fig, ax = panel()
    ax.plot(d.n, d.block, color=C['bc'], ls='-', marker='o', lw=LW, ms=7, label='block')
    ax.plot(d.n, d.tx, color=GREY, ls=(0, (5, 2)), marker='s', lw=LW, ms=7, label='sync tx')
    ax.set_ylim(0, None)   # from zero: the point is how little the block grows
    ax.axhline(6700, color='k', ls=':', lw=1.2)
    ax.text(d.n.min(), 6700, ' 6.7 kB (manuscript)', fontsize=ANNOT_FS, fontweight='bold', va='bottom')
    ax.set_xlabel('Validators N')
    ax.set_ylabel('Bytes')
    ax.set_ylim(0, max(d.block.max(), 6700) * 1.45)   # headroom: the legend was sitting on the curves
    title(ax, f'Signatures add {k[0]:.0f} B per validator')
    legend(ax, loc='upper left')
    save(fig, '13_block_size')

    # One claim per panel: CPU grows with the number of validators, the commit
    # latency does not. The latency markers are the mean over each run's epochs and
    # the dashed line is the mean over all of them, no whiskers, because the
    # block-to-block jitter is not what the panel is about. A line through the
    # per-run medians would suggest a trend the runs do not support.
    fig, ax = panel()
    ax.plot(d.n, d.cpu, color=C['bc'], ls='-', marker='o', lw=LW, ms=7, label='CPU s / block / node')
    lat = d.lat_mean if 'lat_mean' in d else d.lat
    ax.axhline(lat.mean(), color='#ff7f0e', ls=(0, (5, 2)), lw=LW)
    ax.plot(d.n, lat, 's', ms=8, color='#ff7f0e', label='commit latency [s], mean per run')
    ax.annotate(f'mean {lat.mean():.1f} s, no trend with N', (float(d.n.mean()), lat.mean()),
                xytext=(0, -6), textcoords='offset points', fontsize=ANNOT_FS,
                fontweight='bold', color='#ff7f0e', va='top', ha='center')
    ax.set_xlabel('Validators N')
    ax.set_ylabel('Seconds')
    title(ax, 'CPU grows, latency flat within its spread')
    ax.set_ylim(0, max(lat.max(), d.cpu.max()) * 1.55)   # room for the legend above the points
    legend(ax, loc='upper left')
    save(fig, '14_cpu_and_latency')

    blocks5 = 5 * 365.25 * 86400 / 6
    n = 8192
    # SI throughout. The chain's Prometheus counters report p2p in KiB and the
    # storage figures are byte counts read against the 128 GB onboard budget, which is
    # an SI number; carrying both unit families made one cost set read in two scales,
    # so the KiB measurements are converted once, here, and never shown as KiB.
    def human(b):
        units = (('TB', 1e12), ('GB', 1e9), ('MB', 1e6), ('kB', 1e3))
        for unit, f in units:
            if b >= f:
                return f'{b / f:.3g} {unit}'
        return f'{b:.0f} B'
    # all in bytes
    # Per-block cost only: a cumulative quantity does not belong under the same
    # heading as a per-block one. The five-year archive is a bar in 09c instead,
    # where the onboard budget line and the raw-record alternative give it context.
    rows = [('Traffic per validator\nper block', d[d.n == 12].p2p.iloc[0] * 1024, (c[0] * n + c[1] * n * n) * 1024),
            ('Signature data\nper block', k[0] * 12 + k[1], k[0] * n + k[1])]
    # Bytes on a linear axis, one panel per cost: the three costs are orders of
    # magnitude apart, so sharing one axis would either need a log scale (which
    # makes a 300,000x gap look moderate) or a normalisation that hides the unit.
    # Each panel keeps its own byte scale, and the head-only bar is the sliver it is.
    # Wide enough that the two panels' tight crops do not reach into each other:
    # each is cut out on its own for the letter, labels and title included.
    fig, axes = plt.subplots(1, len(rows), figsize=(11.0, 4.2))
    for ax, r in zip(axes, rows):
        b = ax.bar([0, 1], [r[1], r[2]], 0.6, color=[C['bc'], C['ftsp']],
                   edgecolor='black', linewidth=0.6)
        b[1].set_hatch('//')
        for bar, v in zip(b, (r[1], r[2])):
            ax.text(bar.get_x() + bar.get_width() / 2, v, human(v), ha='center', va='bottom',
                    fontsize=ANNOT_FS, fontweight='bold')
        ratio = r[2] / r[1]
        ax.text(0, r[2] * 0.22, f'{ratio:,.0f}x less' if ratio < 1e4 else f'{ratio / 1000:,.0f},000x less',
                ha='center', va='bottom', fontsize=ANNOT_FS, color=C['bc'], fontweight='bold')
        ax.set_xticks([0, 1])
        ax.set_xticklabels(['Cluster heads\n(BLT-SAND)', 'Every satellite\n(extrapolated)'])
        ax.set_ylim(0, r[2] * 1.2)
        ax.set_ylabel('Bytes')
    # A gap wide enough that each panel's cut-out keeps its own margin: the titles are
    # wider than their axes, so with the default spacing one panel's title ends where
    # the next panel's y label begins and there is nothing to cut between them.
    fig.tight_layout(w_pad=5.0)
    save(fig, '15_who_votes')

    # Linear and in units of the onboard budget: the summary block is the only
    # one of the three that a mission-length history fits in at all, and 1.0 is
    # where the hard fork becomes necessary. The extrapolated all-satellite
    # signature row is dropped, it is an extrapolation on an extrapolation.
    fig, ax = panel()
    budget = 128.0
    # Three arms, so the archive question is answered in one place: what BLT-SAND
    # stores, what storing every member's raw record would cost, and what it would
    # cost if every satellite were a validator (the signature row grows with N).
    # The last one was a panel of 09b and is here instead, same quantity, and here
    # it sits against the budget line and the other alternative.
    # The three arms are one thing said three ways: what ONE BLOCK holds. Each label is
    # the content and its size, so the bars read as a consequence of that size rather
    # than as three unrelated scenarios.
    kinds = [('Summary block\n(BLT-SAND)', 6700),
             ('All satellite\nrecords', 137078),
             ('All satellite\nsignatures', 6700 + k[0] * n)]
    vals = [b * blocks5 for _, b in kinds]          # bytes, as in 09b
    bars = ax.bar(range(len(kinds)), vals, 0.55,
                  color=[C['bc'], '#ff7f0e', C['ftsp']], edgecolor='black', linewidth=0.6)
    for bar, h in zip(bars, ('', '//', '//')):
        bar.set_hatch(h)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v,
                human(v), ha='center',
                va='bottom', fontsize=ANNOT_FS, fontweight='bold')
    ax.axhline(budget * 1e9, color='k', ls=':', lw=1.2)
    # The budget line sits near the floor on a linear byte axis, where the first bar's own
    # label already is, so it is named above and pointed at.
    ax.annotate('128 GB onboard\nbudget', xy=(0.04, budget * 1e9), xycoords=('axes fraction', 'data'),
                xytext=(0.04, 0.14), textcoords='axes fraction', fontsize=ANNOT_FS,
                fontweight='bold', va='bottom', ha='left',
                arrowprops=dict(arrowstyle='-', color='#555555', lw=0.9))
    ax.set_xticks(range(len(kinds)))
    ax.set_xticklabels([f'{k_[0]}\n{human(k_[1])}' for k_ in kinds])
    ax.set_ylabel('Bytes')
    # Linear and in bytes, like 09b: a bar's length is its value, and the two figures of
    # the cost set are read on the same kind of axis.
    ax.set_ylim(0, max(vals) * 1.15)
    ax.set_title('Storage per node over 5 years', fontsize=TITLE_FS, fontweight='bold')
    save(fig, '16_block_content')


# --------------------------------------------------------------------- 10 ISL
def f10():
    import blt_isl
    fig, ax = panel()
    d = np.linspace(0, 2500, 400)
    for j, ls in ((2e-6, '-'), (4e-6, (0, (5, 2)))):
        ax.plot(d, 100 * blt_isl.exchange_outage_prob(d, {'isl_pointing_jitter_rad': j}), ls=ls, lw=LW,
                color=C['bc'], label=f'pointing jitter {j * 1e6:.0f} µrad')
    ax.set_xlabel('Link length [km]')
    ax.set_ylabel('Outage [%]')
    title(ax, 'Distance-dependent ISL outage (limit 2,500 km)')
    legend(ax, loc='upper left')
    save(fig, '17_isl_outage')


# --------------------------------------------------------------------- 11 geometry and scale
def f11():
    fig, ax = panel()
    isl = [1, 2, 4]
    t = [11.38, 5.69, 2.85]
    b = ax.bar([str(i) for i in isl], t, color=[GREY, C['bc'], GREY], edgecolor='black', linewidth=0.6)
    for bar, v in zip(b, t):
        ax.text(bar.get_x() + bar.get_width() / 2, v - 0.25, f'{v:.2f} s', ha='center', va='top',
                fontsize=ANNOT_FS + 1, fontweight='bold', color='white')
    ax.axhline(6, color='k', ls='--', lw=1.2)
    ax.text(2.45, 6, '6 s cycle ', fontsize=ANNOT_FS, fontweight='bold', va='bottom', ha='right')
    ax.set_xlabel('ISL terminals at the head')
    ax.set_ylabel('Time to poll\n683 members [s]')
    title(ax, 'Round trip 16.7 ms over 1.97 hops (2,471 km)')
    save(fig, '18_collection_time')

# --------------------------------------------------------------------- 12 correlated faults
NOVOTE = '#9467bd'


def _log_smooth(values):
    """Symmetric three-point weighted mean (1/4, 1/2, 1/4) taken in log space.

    For a positive series read on a log axis. It has no phase lag, so a slope stays
    where it is, and the two ends keep three quarters of their own value.
    """
    v = np.log(np.asarray(values, dtype=float))
    out = v.copy()
    out[1:-1] = 0.25 * v[:-2] + 0.5 * v[1:-1] + 0.25 * v[2:]
    out[0] = 0.75 * v[0] + 0.25 * v[1]
    out[-1] = 0.75 * v[-1] + 0.25 * v[-2]
    return np.exp(out)


def f12():
    p = 'result/runs/correlated_faults_runs.csv'
    if not need(p):
        return
    r = pd.read_csv(p)
    pl = r[r.part == 'placement']
    order = ['scattered', 'clustered', 'regional']
    names = {'scattered': 'Scattered', 'clustered': 'Whole\nclusters', 'regional': 'Regional'}
    groups, keys = [], []
    for f in sorted(pl.level.unique()):
        for c in order:
            groups.append(f'{names[c]}\n{100 * f:.0f}%')
            keys.append((f, c))
    m = pl.groupby(['level', 'case', 'arm']).mean(numeric_only=True)
    arms = {'bc': 'BLT-SAND', 'novote': 'no vote', 'cluster': 'ATS', 'ftsp': 'FTSP'}
    cols = {'bc': C['bc'], 'novote': NOVOTE, 'cluster': C['cluster'], 'ftsp': C['ftsp']}
    hatches = {'bc': '', 'novote': 'oo', 'cluster': '//', 'ftsp': '..'}
    labels = {'bc': 'BLT-SAND', 'novote': 'Same hierarchy, no vote', 'cluster': 'ATS', 'ftsp': 'FTSP'}

    # 12b isolates the consensus from the rest of the design, and the scope of
    # "resilient", against the same hierarchy with the vote removed, no other protocol,
    # since the question is what consensus adds to this design. Both panels run on the
    # manuscript's axis: regionally correlated degradation takes whole clusters and so
    # their heads, and the count of heads misreporting together is the severity.
    # Left, what the vote prevents: the value the network agrees on, measured against what
    # its healthy clusters themselves report (result/runs/correlated_faults_runs_sweep.csv
    # joined to fault_concentration.csv, the two correlated placements pooled). Right, how
    # far it holds: the commit rate, 62% at a third of the heads, and
    # nothing committed past the quorum.
    ps = 'result/runs/correlated_faults_runs_sweep.csv'
    if need(ps):
        sw = pd.read_csv(ps)
        sw = sw[sw.part == 'placement'].copy()
        # Rounds, not runs, are the sample. A wrong proposal is rare and discrete, so a
        # per-run average lands on multiples of (lie / rounds per run), 0.6, 7.4, 14.3 ns
        # for a 25-round run, and a median over runs then steps from one branch to the
        # next as soon as half the runs contain one. Pooling every round of every seed
        # (350-375 per point) gives the quantity the panel is about: how far the value the
        # network adopts sits from its healthy clusters, per round. The first round of each
        # run is dropped, as everywhere else: no satellite has a ledger record yet, so the
        # heads are chosen without one.
        # And only the rounds that COMMITTED. The axis is the time the network agreed on,
        # and a refused round agreed on nothing: BLT-SAND then falls back on the median of
        # what it heard (FAILED_ROUND_FALLBACK) so the satellites still get a global step, but that value was
        # never voted for and is not what this panel is about. Counting it read as the vote
        # failing past a third of the heads, when what happens there is the vote refusing --
        # the wrong-commit rate is 0 at every point of this sweep. What it costs is
        # availability, which is written next to the curves and is 18's subject. The no-vote
        # arm commits every round, so the filter does not touch it.
        # The scattered placement is measured with 40 seeds against the other two placements' 15, and the extra run
        # replaces those rows. Where a whole cluster or a region degrades, the number of
        # misreporting heads is all but fixed within a run (sd 0.0 to 0.14) and fifteen seeds
        # settle the curve; scattered faults instead make a wrong proposal a rare event whose
        # rate IS the quantity plotted, and at 1-2 expected events per 360 rounds the low end
        # of the curve was reading a coin toss. 40 seeds put 960 rounds behind each point.
        pr = 'result/runs/correlated_faults_rounds_sweep.csv'
        rounds_ref = commit_of = None
        if os.path.exists(pr):
            rd = pd.read_csv(pr)
            more = 'result/runs/correlated_faults_rounds_scattered40.csv'
            if os.path.exists(more):
                extra = pd.read_csv(more)
                rd = pd.concat([rd[~rd.case.isin(extra.case.unique())], extra],
                               ignore_index=True)
            if 'ref_err_ns' in rd:
                rd = rd[(rd.part == 'placement') & (rd['round'] > 0)]
                commit_of = rd.groupby(['case', 'level', 'arm']).committed.mean()
                rounds_ref = (rd[rd.committed == 1]
                              .groupby(['case', 'level', 'arm']).ref_err_ns.mean())
                # Why the two scattered curves part at all, in one number: how often the
                # cluster whose turn it is to propose is headed by a degraded satellite.
                # That is the whole gap, the vote rejects every one of those proposals
                # (no wrong commit anywhere in the sweep), and without it each becomes the
                # constellation's reference for that round.
                # Not the ledger failing, the ledger has already taken this from 12 x f
                # heads (0.6 / 2.0 / 3.3 / 3.9 at 5 / 15 / 25 / 35%) down to
                # 0.03 / 0.07 / 0.13 / 0.20. What is left is the share of degraded oscillators
                # whose realized drift landed near zero, which a record OF PRECISION cannot
                # see by construction. The vote checks the value, not the proposer's record,
                # so it is the layer that catches exactly this.
                sc = rd[(rd.case == 'scattered') & (rd.arm == 'BLT-SAND') & (rd.level >= 0.2)]
                bad_prop = 100 * sc.proposer_wrong.mean() if len(sc) else float('nan')
        # Fallback for a rounds file that carries no ref_err_ns column: the
        # median over per-run averages.
        gsw = sw.groupby(['case', 'level', 'arm']).median(numeric_only=True)
        lv = sorted(sw.level.unique())
        xs = [100 * v for v in lv]
        # Left, the fault model: where the degradation sits decides how full one cluster
        # gets. Right, what that does to the value the network agrees on, with and without
        # the vote, the same three placements in the same colours. No line is drawn at the
        # share where a head starts to misreport: that threshold is the simulator's rule
        # (blt_core.head_fault_mask, majority_frac = 0.5), not something the manuscript
        # states, and a head's state is not to be inferred from its members'.
        # The commit rate is not drawn here either, availability is 07b's and 18's subject.
        cc = pd.read_csv('result/runs/fault_concentration.csv')
        gp = cc.groupby(['case', 'level']).mean(numeric_only=True)
        place = (('scattered', 'Scattered', GREY, 'o'),
                 ('clustered', 'Whole clusters', '#9467bd', 's'),
                 ('regional', 'Regional', C['ftsp'], '^'))
        fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.8), constrained_layout=True)
        for c, lab, col, mk in place:
            axes[0].plot(xs, [100 * gp.loc[(c, v), 'worst_cluster_frac'] for v in lv],
                         color=col, marker=mk, lw=LW + 1.6, ms=8.5, label=lab)
            ref_of = (lambda c_, v, arm: (rounds_ref.get((c_, v, arm), float('nan'))
                                          if rounds_ref is not None
                                          else gsw.loc[(c_, v, arm), 'ref_err_ns']))
            # Every line the same colour, weight, marker and style: the placement is the
            # colour and the arms are told apart by where they run. Each colour forks where
            # the vote starts to matter, and the two branches are named on the plot.
            # The scattered points are a RATE of a rare event, a degraded head that is
            # also the round's proposer, a few dozen rounds out of 960, so neighbouring
            # points scatter by a third around the line they follow. They are drawn through
            # a symmetric three-point weighted mean (1/4, 1/2, 1/4) in log space, which has
            # no lag and leaves the ends where they are. The concentrated placements are NOT
            # smoothed: their wrong-head count hardly moves inside a run, their curve is
            # already the shape of the measurement, and smoothing would halve the 22 ns that
            # whole-cluster degradation reaches at 10%, a real step, not scatter.
            sm = (lambda v: _log_smooth(v)) if c == 'scattered' else (lambda v: v)
            axes[1].plot(xs, sm([ref_of(c, v, 'BLT-SAND') for v in lv]),
                         color=col, marker=mk, lw=LW + 1.6, ms=8.5, zorder=5, label='_')
            axes[1].plot(xs, sm([ref_of(c, v, 'no vote') for v in lv]), ls='--',
                         color=col, marker=mk, lw=LW + 1.6, ms=8.5, zorder=4, label='_')
        axes[0].set_ylabel('Worst-hit cluster faulty [%]')
        axes[0].set_ylim(0, 108)
        axes[1].set_yscale('log')
        axes[1].set_ylim(0.17, 300)
        axes[1].set_yticks([0.3, 1, 10, 100])
        axes[1].set_yticklabels(['0.3', '1', '10', '100'])
        # Not the synchronization RMSE the manuscript reports (8.8 ns): the error of the
        # reference value the round adopted, against what the clusters that are not lying
        # reported for themselves. A healthy round leaves 0.4 ns of it.
        axes[1].set_ylabel('Adopted reference error [ns]')
        for ax_ in axes:
            ax_.set_xlabel('Faulty satellites [%]')
            ax_.set_xlim(0, 100 * max(lv) + 2)
        # Two words in the panel and nothing else, each tied to its own curves by a leader
        # line: solid is the arm with the vote, dashed the arm without, and the no-vote
        # family splits too far apart for one label sitting on a curve to serve.
        def tie(text, xy_text, anchors, ha='center'):
            for a in anchors:
                axes[1].annotate('', xy=a, xytext=xy_text, textcoords='data',
                                 arrowprops=dict(arrowstyle='-', lw=0.9, color='#666666',
                                                 shrinkA=9, shrinkB=5))
            axes[1].text(*xy_text, text, fontsize=ANNOT_FS, fontweight='bold',
                         color='#333333', ha=ha, va='center',
                         bbox=dict(boxstyle='round,pad=0.18', fc='white', ec='none'))

        tie('no vote', (xs[5], 10.5),
            [(xs[4], ref_of('clustered', lv[4], 'no vote')),
             (xs[-2], ref_of('scattered', lv[-2], 'no vote'))])
        tie('vote (BLT-SAND)', (xs[2], 0.25),
            [(xs[4], ref_of('regional', lv[4], 'BLT-SAND'))])
        for c, lab, col, mk in place:
            axes[1].plot([], [], color=col, marker=mk, lw=LW + 1.6, ms=8.5, label=lab)
        legend(axes[0], loc='center right', fontsize=LEGEND_FS - 2)
        legend(axes[1], loc='upper left', fontsize=LEGEND_FS - 2)
        title(axes[0], 'Where the degradation sits decides how full a cluster gets')
        title(axes[1], 'And what the network then agrees on, with and without the vote')
        save(fig, '10_correlated_faults')


# --------------------------------------------------------------------- 13 cross-cluster checks
def _table(cells, header, widths, name, heading, width=9.0, fontsize=10):
    """A grid and nothing else: the figure is exactly as tall as its rows.

    loc='center' placed the table in the middle of a fixed-height axes and let it
    keep its own idea of row height, so the saved panel carried as much blank as
    table. The table now fills the axes and the axes fills the figure, and the
    height follows the row count, so adding a row grows the panel instead of
    shrinking the margin.
    """
    row_h = fontsize / 72 * 2.4
    fig, ax = plt.subplots(figsize=(width, (len(cells) + 1) * row_h))
    ax.axis('off')
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    t = ax.table(cellText=cells, colLabels=header, cellLoc='left', colWidths=widths,
                 bbox=[0, 0, 1, 1])
    t.auto_set_font_size(False)
    t.set_fontsize(fontsize)
    for (row, _), cell in t.get_celld().items():
        if row == 0:
            cell.set_text_props(fontweight='bold')
    title(ax, heading, fontsize=fontsize)
    save(fig, name)


def f13():
    p = 'result/chain/chain_n12_cross.log'
    if need(p):
        txt = open(p, encoding='utf-8', errors='replace').read()
        got = re.findall(r'^(control: consistent summary|\d+ of \d+ heads 20 ms off|head not in delegate set|'
                         r'cluster count != table|member count != table)\s+(\S+)\s+(committed|rejected)\s+(\d+/\d+)\s*$',
                         txt, re.M)
        if got:
            # Only what the ledger checks across clusters. The "k of 12 heads off" rows are the
            # vote threshold, which the simulation tables evaluate. The result is the error the
            # chain returned by name and code; 18 is the SDK's ErrInvalidRequest from the
            # message's own validation, raised before the module's count checks.
            # The majority case is kept as one row, phrased as the check it is (a global time
            # that contradicts most cluster summaries), not as a threshold sweep; the two
            # count mismatches are one refusal of the same kind and share a row.
            label = {'control: consistent summary': 'All 12 cluster summaries consistent',
                     '7 of 12 heads 20 ms off': 'Global time contradicting most cluster summaries',
                     'head not in delegate set': 'Summary from a non-elected head',
                     'cluster count != table': "Declared counts differ from the block's tables"}
            err = {'1109': 'ErrPlausibility', '1102': 'ErrUnknownClusterHead',
                   '18': 'ErrInvalidRequest'}
            cells = [[label[a], 'committed' if c == '0' else f'{err.get(c, "code")} ({c})']
                     for a, c, res, n in got if a in label]
            # 0.62 of 10.5 in leaves the longest proposal clear of the column rule.
            _table(cells, ['Proposal', 'Result'], [0.62, 0.38],
                   '11_cross_cluster_checks', 'Cross-cluster consistency on a 12-validator chain',
                   width=10.5, fontsize=TICK_LABEL_FS)


# --------------------------------------------------------------------- chain verdict graphics
# Experimental graphical versions of the chain tables (the tables stay as they are).
REFUSED, COMMITTED = '#d62728', '#2ca02c'


# --------------------------------------------------------------------- 15 design guidance and Fig. 4(c) periods
def f16():
    """Deployment flexibility drawn like the manuscript's Fig. 4(d), from measurements.

    Grid: result/runs/deployment_grid_block.csv (local = global = T_block, link
    model on, Nc 6/12/18/24/30 x T 2..10 s, 3 seeds). Curves are the measured grid
    interpolated (PCHIP in Nc, linear in T); a curve starts where the block covers the
    member collection time of result/runs/collection_time.csv (Nc 6..30)."""
    from scipy.interpolate import PchipInterpolator
    pg, pc = 'result/runs/deployment_grid_block.csv', 'result/runs/collection_time.csv'
    if not (need(pg) and need(pc)):
        return
    g = pd.read_csv(pg)
    ct = pd.read_csv(pc).sort_values('Nc')
    grid = g.pivot_table(index='Nc', columns='T_s', values='rmse_ns')
    ncs, ts = grid.index.values.astype(float), grid.columns.values.astype(float)
    nc_fine = np.linspace(6, 30, 241)
    # collection time decreases with Nc: invert to the smallest Nc a block interval allows
    t_collect = PchipInterpolator(ct.Nc.values, ct.T_local_s.values)
    nc_min = lambda T: nc_fine[np.argmax(t_collect(nc_fine) <= T)] if (t_collect(nc_fine) <= T).any() else np.nan
    curves = {c: PchipInterpolator(ncs, grid[c].values) for c in ts}

    def rmse(nc, T):
        k = np.searchsorted(ts, T)
        if k == 0:
            return curves[ts[0]](nc)
        if k >= len(ts):
            # past the longest measured interval (10 s): the 8-10 s slope, carried on
            w = (T - ts[-2]) / (ts[-1] - ts[-2])
            return (1 - w) * curves[ts[-2]](nc) + w * curves[ts[-1]](nc)
        t0, t1 = ts[k - 1], ts[k]
        w = (T - t0) / (t1 - t0)
        return (1 - w) * curves[t0](nc) + w * curves[t1](nc)

    # Drawn the way the manuscript draws Fig. 4(d) (the paper layout,
    # panel_d): one curve per block interval starting where the block covers the member
    # collection time, with a drop line at that start; the black envelope through the
    # starts; the deployable region (envelope up to the longest interval, capped at the
    # longest interval shaded; x from the first to the last measured Nc.
    #
    # The extent is the measured grid's own rather than a cap written here. Every
    # interval in the grid runs; 6 s is where 10 ns and 12 clusters land for this
    # cluster size, not a bound on the design, which is also why no 10 ns line is
    # drawn across the region.
    T_MIN, T_MAX = float(ts.min()), float(ts.max())
    t_fine = np.arange(T_MIN, T_MAX + 0.01, 1.0)
    nc_lo, nc_hi = float(ncs.min()), float(ncs.max())
    nc_fine = np.linspace(nc_lo, nc_hi, 400)
    fig, ax = panel((7.0, 4.6))
    cmap = plt.get_cmap('turbo')
    norm = matplotlib.colors.Normalize(vmin=T_MIN, vmax=T_MAX)
    for T in t_fine:
        n0 = nc_min(T)
        if np.isnan(n0):
            continue
        sel = nc_fine >= n0
        y = rmse(nc_fine[sel], T)
        ax.plot(nc_fine[sel], y, color=cmap(norm(T)), lw=2.0, alpha=0.7, solid_capstyle='round')
        ax.plot([n0, n0], [0, float(y[0])], color=cmap(norm(T)), lw=2.0, alpha=0.7)
    # lower envelope: at each Nc the shortest block interval its collection allows. It is
    # drawn on to the left edge of the plot by its trend (the collection there needs a
    # little over 10 s; the 8-10 s slope is carried on) instead of dropping to zero.
    x0 = np.floor(nc_min(T_MAX)) if not np.isnan(nc_min(T_MAX)) else nc_lo
    t_env = np.clip(t_collect(nc_fine), T_MIN, None)
    ok = t_env <= T_MAX
    shown = nc_fine >= x0
    env_y = np.array([float(rmse(np.array([n]), t)[0]) if o else np.nan
                      for n, t, o in zip(nc_fine, t_env, shown)])
    upper_y = np.array([float(rmse(np.array([n]), T_MAX)[0]) for n in nc_fine])
    # Feasible = the block covers the collection time: on or above the envelope, up to the
    # longest interval drawn. One shade, one label; no accuracy line, since the region is
    # about what can run, and the RMSE axis already says how accurate each point is.
    ax.fill_between(nc_fine, env_y, upper_y, where=ok, color='#9bbfdb', alpha=0.35, zorder=0,
                    interpolate=True)
    ax.plot(nc_fine, env_y, color='black', lw=3.5, solid_capstyle='round', zorder=10)
    xm = nc_fine[len(nc_fine) * 2 // 3]
    ym = float(np.interp(xm, nc_fine, (np.nan_to_num(env_y) + upper_y) / 2))
    ax.text(xm, ym, 'feasible', fontsize=13, fontweight='bold', ha='center', va='center', zorder=12,
            bbox=dict(facecolor='white', edgecolor='none', alpha=0.85, pad=2))
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, pad=0.02, fraction=0.045)
    cb.set_label('Block interval $T_{block}$ [s]', fontweight='bold')
    # Start where the first curve starts (the longest block interval covers the
    # collection time only from here on), so there is no empty band on the left.
    ax.set_xlim(x0, nc_hi)
    ax.set_xticks([t for t in (10, 15, 20, 25, 30) if x0 <= t <= nc_hi])
    ax.set_ylim(0, float(np.nanmax(upper_y)) * 1.05)
    ax.set_xlabel('Number of clusters $N_c$')
    ax.set_ylabel('Steady-state RMSE [ns]')
    sec = ax.secondary_xaxis('top', functions=(lambda x: 8192 / np.where(x == 0, np.nan, x),
                                               lambda m: 8192 / np.where(m == 0, np.nan, m)))
    sec.set_xlabel('Members per cluster ($N$ = 8192)', fontweight='bold')
    sec.set_xticks([300, 400, 500, 700, 1000])
    for lab in sec.get_xticklabels():
        lab.set_fontweight('bold')
    save(fig, '20_deployment_flexibility')


def f17():
    """Ablation, as one table (result/runs/ablation_ladder.csv).

    Rows are the published design and one removal each, with the three flags saying what a
    row still has. Columns are grouped by fault condition and carry only the metrics that
    fault moves, because a component can only show its worth against the fault it answers.
    (A second table, the fault trend scheme by scheme, re-read the same runs; dropped.)

    RMSE is the relative metric the paper reports; it stays flat across the top rows by
    construction, since a commit shifts every cluster alike and leaves the satellites
    aligned with each other whatever was committed. The reference error is that same
    commit measured against the cluster references that did not lie, the deviation the
    relative metric cancels, and the thing the vote prevents. Below a nanosecond it prints
    as "< 1": one exchange carries about 3 ns of timestamp noise."""
    p_ = 'result/runs/ablation_ladder.csv'
    if not need(p_):
        return
    d = pd.read_csv(p_)
    if 'condition' not in d or 'ref_err' not in d:
        skipped.append(p_ + ' (old format, rerun experiments/ledger/ablation_ladder.py)')
        return
    runs = 'result/runs/ablation_ladder_runs.csv'
    rr = pd.read_csv(runs) if os.path.exists(runs) else None
    med = rr.groupby(['arm', 'condition']).rmse.median() if rr is not None else None
    # The RMSE of the same nominal satellites against true time. It is a genuine RMSE
    # (every satellite's error, squared and averaged) and it does not cancel a shift the
    # whole constellation took together, which is exactly what a wrong commit is.
    # Healthy oscillators drift about zero, so true time is the timescale the honest
    # clusters keep; the relative RMSE stays next to it as the metric the paper uses.
    # MEAN over the seeds, not the median: a wrong commit happens in one seed out of four
    # and moves that whole run by hundreds of ns (554 ns at two faulty clusters), so the
    # median reports the three seeds where nothing went wrong and hides the damage this
    # column exists to show. The relative RMSE keeps the median, as on the fault axes.
    med_true = (rr.groupby(['arm', 'condition']).rmse_true.mean()
                if rr is not None and 'rmse_true' in rr else None)
    conds, arms = list(dict.fromkeys(d.condition)), list(dict.fromkeys(d.arm))
    # How fast the constellation's shared time walks off true time, over ten minutes
    # (experiments/ledger/timescale_drift.py). The relative RMSE cannot show it: a wrong commit
    # moves every cluster alike. ppb is the unit an oscillator is specified in, so it
    # reads directly against a single healthy clock (1 ppb).
    dp = 'result/runs/timescale_drift.csv'
    drift = (pd.read_csv(dp).set_index(['arm', 'condition']).abs_drift_ppb
             if os.path.exists(dp) else None)
    drift_of = lambda arm, c: (drift.get((arm, c), float('nan')) if drift is not None else float('nan'))
    ppb = lambda v: '-' if pd.isna(v) else f'{v:.2f}'
    mark = lambda b: 'yes' if b else '-'
    pct = lambda v: '-' if pd.isna(v) else f'{100 * v:.0f}%'
    num = lambda v: '-' if pd.isna(v) else f'{v:.2f}'
    ref = lambda v: '-' if pd.isna(v) else ('< 1' if v < 1.0 else f'{v:.1f}')
    rmse_of = lambda arm, c, row: (med.get((arm, c), row.rmse) if med is not None else row.rmse)
    true_of = lambda arm, c, row: (med_true.get((arm, c), float('nan')) if med_true is not None
                                   else float('nan'))
    tru = lambda v: '-' if pd.isna(v) else f'{v:.1f}'

    # ---------------------------------------------------------------- 17: components
    # One table. Rows are the published design and one removal each; the three flags say
    # what a row still has. Columns are grouped by fault condition, and each condition
    # shows only the metrics that fault can move, a component can only show its worth
    # against the fault it answers. The relative RMSE is shown once, under the headline
    # draw (the manuscript's numbers); in the other two conditions it is 8.8 ns for every
    # BLT row by construction (a commit moves all clusters alike), so the table says that
    # in a note instead of repeating it.
    def cond(prefix):
        return next(c for c in conds if c.startswith(prefix))
    hd, rg, sc = cond('headline'), cond('a degraded region'), cond('degraded individuals')
    # The same metrics in the same order in every condition, so a column means one thing
    # across the table: what the network's common time did, then how many heads made it
    # happen. RMSE appears once, under the headline draw, it is the manuscript's number
    # and reads 8.8 ns for every BLT row elsewhere by construction. Wrong commits are shown
    # where one happens at all, the regional patch.
    cols = [(hd, 'rmse', 'RMSE\n[ns]'), (hd, 'liars', 'faulty\nheads'),
            (sc, 'drift', 'timescale\ndrift [ppb]'), (sc, 'liars', 'faulty\nheads'),
            (rg, 'drift', 'timescale\ndrift [ppb]'), (rg, 'liars', 'faulty\nheads'),
            (rg, 'bad', 'wrong\ncommits')]
    # Named as 12b names its placements, since the two figures are read together:
    # scattered / whole clusters / regional. The middle condition fills two whole
    # clusters (cluster_aligned), so it is 'whole clusters', not 12b's 'regional',
    # which is a spatial patch that ignores cluster borders. The headline draw is
    # 5% of 8,192 = 410 satellites, less than one cluster of 683, so it fills none
    # and lands as a minority spread, the manuscript's own draw, named as such.
    groups = [('5% faulty\n(manuscript draw)', 4, 6), ('25% faulty\nscattered', 6, 8),
              ('25% faulty\nregional', 8, 11)]

    def value(arm, c, key):
        r = d[(d.arm == arm) & (d.condition == c)].iloc[0]
        if key == 'rmse':
            return rmse_of(arm, c, r)
        if key == 'drift':
            return drift_of(arm, c)
        return r[key] if r.vote or r.ledger else float('nan')
    fmt = {'rmse': lambda v: f'{v:.2f}', 'liars': num, 'drift': ppb, 'bad': pct}
    cells, vals = [], []
    for arm in arms:
        r = d[(d.arm == arm) & (d.condition == hd)].iloc[0]
        v = [value(arm, c, k) for c, k, _ in cols]
        vals.append(v)
        cells.append([SHOW.get(arm, arm), mark(r.hierarchy), mark(r.vote), mark(r.ledger)]
                     + [fmt[k](x) for (_, k, _), x in zip(cols, v)])
    heads = ['Configuration', 'Hier.', 'Vote', 'Ledger'] + [h for *_, h in cols]
    w = np.array([0.25, 0.06, 0.055, 0.065] + [0.095] * len(cols))
    w = w / w.sum()
    fig, ax = plt.subplots(figsize=(11.8, 3.3))
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    top = 0.80
    t = ax.table(cellText=cells, colLabels=heads, cellLoc='center',
                 bbox=[0, 0.08, 1, top - 0.08], colWidths=list(w))
    t.auto_set_font_size(False)
    t.set_fontsize(9)
    pub = vals[arms.index('BLT-SAND (published)')]
    for (row, col), cell in t.get_celld().items():
        if row == 0:
            cell.set_text_props(fontweight='bold')
        elif col == 0:
            cell.set_text_props(ha='left', fontweight='bold' if row == 1 else 'normal')
        elif col >= 5:
            # a removal that at least doubles a fault metric of the published design
            x, ref0 = vals[row - 1][col - 4], pub[col - 4]
            if not pd.isna(x) and x > 2 * ref0 + 1e-9 and x > 0.005:
                cell.set_facecolor('#fdece7')
    edges = np.concatenate([[0], np.cumsum(w)])
    for label, a, b in groups:
        x0, x1 = edges[a], edges[b]
        ax.plot([x0 + 0.004, x1 - 0.004], [top + 0.015] * 2, color='k', lw=1.0)
        ax.text((x0 + x1) / 2, top + 0.03, label, ha='center', va='bottom',
                fontsize=ANNOT_FS, fontweight='bold')
    ax.text(0, 0.0, 'The three BLT-SAND rows read 8.8 ns RMSE in every condition: '
            'a commit moves all clusters alike.',
            fontsize=ANNOT_FS - 2, va='bottom', ha='left', style='italic')
    save(fig, '05_component_ablation')


def f18():
    """Head axis with the failed-round fallback.

    result/runs/fault_axes_head_fallback.csv: a round that misses the quorum falls
    back to the unverified head median, which is what the same hierarchy does without
    any consensus. The x axis is the share of the twelve heads, as asked on the member
    axis, and the commit rate is drawn on the right so the availability cost of the
    quorum is visible next to the accuracy."""
    p_ = 'result/runs/fault_axes_head_fallback.csv'
    if not need(p_):
        return
    d = pd.read_csv(p_).sort_values('faulty_heads')
    x = 100 * d.faulty_heads / 12
    fig, ax = panel()
    runs = 'result/runs/fault_axes_head_runs_fallback.csv'
    if os.path.exists(runs):
        # Median with the quartile band over the 8 seeds x 4 cluster combinations:
        # which clusters degrade matters (their size and where they sit on the flood
        # paths), so the point estimate alone hides most of what the runs show.
        g = pd.read_csv(runs).groupby('faulty_heads')
        for a in ('ftsp', 'cluster', 'bc'):
            q = g[a].quantile([0.25, 0.5, 0.75]).unstack()
            xr = 100 * q.index / 12
            ax.plot(xr, q[0.5], **proto(a))
            ax.fill_between(xr, q[0.25], q[0.75], color=C[a], alpha=0.15, lw=0)
    else:
        for a in ('ftsp', 'cluster', 'bc'):
            ax.plot(x, d[a], **proto(a))
    isl_line(ax)
    ax.axvline(100 / 3, color='k', ls=':', lw=1.2)
    ax.text(100 / 3, ax.get_ylim()[1], ' 4 of 12 heads', fontsize=ANNOT_FS, fontweight='bold',
            va='top')
    ax.set_xlabel('Cluster heads misreporting [% of 12]')
    ax.set_ylabel('RMSE, nominal\nsatellites [ns]')
    ax2 = ax.twinx()
    ax2.plot(x, 100 * d.commit, color=GREY, ls=(0, (1, 1)), lw=LW, marker='x', ms=6,
             label='BLT commit rate')
    ax2.set_ylabel('Commit rate [%]', color=GREY)
    ax2.set_ylim(0, 105)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=LEGEND_FS, frameon=False, loc='upper left', ncol=2)
    title(ax, 'Head axis with the failed-round fallback')
    save(fig, '04_head_faults')


def f19():
    """How fast cluster membership turns over.

    result/runs/cluster_migration_turnover.csv: positions propagated and re-clustered,
    no synchronization. The cumulative curve is what a record kept per cluster loses:
    within ten minutes about half the constellation has been re-assigned at least once."""
    p_ = 'result/runs/cluster_migration_turnover.csv'
    if not need(p_):
        return
    d = pd.read_csv(p_)
    m = d.seconds / 60
    # Only the cumulative share is drawn. The per-update series (0.5% of the
    # constellation) is invisible next to it and made the panel look flat; the
    # number that matters is how long a cluster-local record stays complete.
    fig, ax = panel()
    ax.plot(m, 100 * d.ever_moved_frac, color=C['bc'], ls='-', lw=LW + 0.6)
    for frac in (0.5, 0.8):
        hit = d[d.ever_moved_frac >= frac]
        if not len(hit):
            continue
        t = hit.seconds.iloc[0] / 60
        ax.plot([0, t], [100 * frac] * 2, color=GREY, ls=(0, (2, 2)), lw=1.2, zorder=1)
        ax.plot([t, t], [0, 100 * frac], color=GREY, ls=(0, (2, 2)), lw=1.2, zorder=1)
        ax.plot([t], [100 * frac], marker='o', ms=10, color=C['bc'], zorder=5)
        ax.annotate(f'{100 * frac:.0f}% after {t:.0f} min', (t, 100 * frac), fontsize=ANNOT_FS + 1,
                    fontweight='bold', xytext=(10, -6), textcoords='offset points')
    ax.set_xlabel('Elapsed time [min]')
    # Rewrapped: at the larger label size the first line was taller than the axes.
    ax.set_ylabel('Satellites that changed\ncluster at least once [%]')
    ax.set_ylim(0, 100)
    ax.set_xlim(0, m.max())
    title(ax, 'Cluster membership does not stay put')
    save(fig, '09_cluster_turnover')


FTSP_CYCLE_S = 1.0


def f22():
    """Fig. 4(c) in the manuscript's own shape: messages per second against constellation
    size, one curve per scheme, with the 8,192-satellite line (figures/manuscript,
    panel_c). Only the operating periods change, and they are now measured rather than
    assumed: result/runs/comm_periods.csv gives the longest period each scheme holds
    10 ns at, 9 s for BLT-SAND, 2 s for ATS. FTSP has no such period (about 18 ns at
    every flooding rate from 0.1 to 1 s, because its error is the timestamp budget along
    the flood path), so it is drawn at the evaluated 0.45 s and labelled as not meeting
    the target. The message model is the manuscript's own:

        BLT   N/T + 3k^2/T      ATS   N/T      FTSP   N/T

    Panel 22b keeps the cost-accuracy view of the same measurements, which is the
    evidence that those periods are the right ones; this panel is the one that has to
    sit in the paper, where the reader already knows the axes."""
    p_ = 'result/runs/comm_periods.csv'
    if not need(p_):
        return
    d = pd.read_csv(p_)
    if 'lsb_ns' in d:
        d = d[(d.lsb_ns == 10) & (d.jitter_ns == 3)]
    k, target = 12, ISL_REQUIREMENT_NS
    period, label = {}, {}
    for a in ('bc', 'cluster', 'ftsp'):
        g = d[d.alg == a].sort_values('period_s')
        ok = g[g.rmse_ns <= target]
        if len(ok):
            period[a] = float(ok.period_s.max())
            label[a] = f'{period[a]:g} s for {target:.0f} ns'
        else:
            # No qualifying period. FTSP's error falls with the cycle only onto a
            # floor set by the one-way timestamp budget along the flood path, which
            # the cycle does not touch, so the point cannot be read off the accuracy
            # column. FTSP_CYCLE_S is already cheaper than the 0.45 s this work runs
            # FTSP at elsewhere, and is the longest measured cycle that still
            # refreshes more often than either scheme it is compared with.
            period[a] = FTSP_CYCLE_S
            at = float(g.loc[(g.period_s - FTSP_CYCLE_S).abs().idxmin(), 'rmse_ns'])
            label[a] = f'{period[a]:g} s, {at:.0f} ns (never reaches {target:.0f})'

    n = np.linspace(500, 10000, 200)
    fig, ax = panel()
    for a in ('ftsp', 'cluster', 'bc'):
        msgs = n / period[a] + (3 * k * k / period[a] if a == 'bc' else 0.0)
        ax.plot(n, msgs, color=C[a], ls=LINESTYLES[a], lw=LW + 1.2, dash_capstyle='round',
                label=f'{L[a]}, {label[a]}')
    # Linear, as in the manuscript's panel: every curve is a straight line in N, which a
    # log axis would bend into a curve that seems to saturate. The values at 8,192 are
    # written on the line so the lowest curve can still be read exactly.
    top = max(n.max() / period[a] + (3 * k * k / period[a] if a == 'bc' else 0.0)
              for a in period) * 1.12
    ax.set_ylim(0, top)
    ax.set_xlim(n.min(), n.max())
    ax.axvline(8192, ls='--', lw=1.8, color='#3a3a3a', alpha=0.95)
    ax.text(8192, top * 0.45, ' N = 8,192', fontsize=ANNOT_FS, fontweight='bold',
            va='center', ha='left')
    for a in ('ftsp', 'cluster', 'bc'):
        v = 8192 / period[a] + (3 * k * k / period[a] if a == 'bc' else 0.0)
        ax.plot([8192], [v], 'o', color=C[a], ms=7, zorder=6)
        # Two significant figures, which is how the paper reads these. The exact
        # values are N/T plus the head-consensus term, so printing them in full
        # gives 8192 and 4096, the constellation size and half of it, which
        # read as placeholders rather than as a measurement.
        ax.annotate(f'{float(f"{v:.2g}"):,.0f}', (8192, v), xytext=(-6, 5), textcoords='offset points',
                    ha='right', va='bottom', fontsize=ANNOT_FS, fontweight='bold', color=C[a])
    ax.set_xlabel('Number of satellites N')
    ax.set_ylabel('Sync messages per second')
    title(ax, 'Communication at each scheme\'s measured operating period')
    legend(ax, loc='upper left', fontsize=LEGEND_FS - 1)
    save(fig, '19_communication_cost')



def main() -> int:
    global TITLES
    ap = argparse.ArgumentParser()
    ap.add_argument('--titles', action='store_true', help='draw panel titles (off: caption supplied where used)')
    TITLES = ap.parse_args().titles
    for fn in (f01, f03, f04, f07, f08, f09, f10, f11, f12, f13,
               f16, f17, f18, f19, f22):
        try:
            fn()
        except Exception as exc:  # keep going; report at the end
            skipped.append(f'{fn.__name__}: {exc!r}')
    print('made:', ', '.join(made))
    if skipped:
        print('skipped:', *skipped, sep='\n  ')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
