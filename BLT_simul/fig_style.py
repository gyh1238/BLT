"""Shared style and constants for Fig. 5 panels."""

COLORS = {
    # matplotlib default prop_cycle (the colors you get without specifying)
    # plus an amber yellow for ATS that reads as clearly distinct from C3 red.
    'bc':      'C0',       # #1f77b4 blue   — BLTi-SAND
    'cluster': '#f0a500',  # amber yellow   — ATS
    'ftsp':    'C3',       # #d62728 red    — FTSP
    'none':    'C7',       # #7f7f7f gray   — No sync
}

LABELS = {
    'bc': 'BLTi-SAND',
    'cluster': 'ATS',
    'ftsp': 'FTSP',
    'none': 'No sync',
}

MARKERS = {
    'bc': 'o',
    'cluster': 's',
    'ftsp': '^',
    'none': 'x',
}

UNIT_SCALE = 1e12 * 0.955  # seconds -> nanoseconds (matches make_figure_tmp.py)
EMA_SPAN = 1000
STEADY_STATE_WINDOW = 3000
ISL_REQUIREMENT_NS = 10.0
