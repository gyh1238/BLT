"""Shared style and constants for the evaluation panels."""

COLORS = {
    # matplotlib default prop_cycle (the colors you get without specifying)
    # plus an amber yellow for ATS that reads as clearly distinct from C3 red.
    'bc':      'C0',       # #1f77b4 blue   BLT-SAND
    'cluster': '#f0a500',  # amber yellow   ATS
    'ftsp':    'C3',       # #d62728 red    FTSP
    'none':    'C7',       # #7f7f7f gray   No sync
}

MARKERS = {
    'bc': 'o',
    'cluster': 's',
    'ftsp': '^',
    'none': 'x',
}

# seconds -> nanoseconds. The engines accumulate clock error in seconds
# (blt_core.clock_error_step), so this is the plain unit conversion, and
# tools/verify_units.py checks the two against each other.
UNIT_SCALE = 1e9
EMA_SPAN = 1000
ISL_REQUIREMENT_NS = 10.0
ISL_LINE_COLOR = '#BA7517'

# Per-protocol linestyle so panels remain readable when printed in
# black-and-white. FTSP is drawn solid because it has the densest
# saw-tooth in panel (a) and dotted/dashed renderings looked busy across
# its peaks. The other three protocols take distinguishable broken
# patterns. Colors are kept for screen viewing.
LINESTYLES = {
    'bc': (0, (1, 1.5)),            # dots, BLT-SAND
    'cluster': (0, (5, 2)),         # dashes, ATS
    'ftsp': '-',                    # solid, FTSP
    'none': (0, (4, 1.5, 1, 1.5)),  # dash-dot, No sync (panel a only)
}

# Bar fill patterns, the black-and-white counterpart of LINESTYLES for bar charts.
# Shared axis-label / tick-label styling, bold and larger so they stay legible at
# small print sizes. A two-column page places these panels at a quarter to half of the text
# width, so a 7 in panel is reproduced at under 2 in and every point of type counts;
# the sizes below are set for that reduction, not for reading the PNG at full size.
AXIS_LABEL_FS = 15
TICK_LABEL_FS = 13

# bbox_inches='tight' lets matplotlib pick margins big enough to fit
# every label (y-axis caption, secondary x-axis caption on panel d,
# the colorbar caption, etc.) without hand-tuning each
# subplots_adjust margin. pad_inches keeps a small uniform border so
# the result still feels framed.
SAVE_KW = dict(bbox_inches='tight', pad_inches=0.15)
PNG_DPI = 200
PANEL_SIZE = (7.0, 4.0)


def bold_axes(ax):
    """Make axis labels and tick labels bold + larger on a single ax."""
    ax.set_xlabel(ax.get_xlabel(), fontsize=AXIS_LABEL_FS, fontweight='bold')
    ax.set_ylabel(ax.get_ylabel(), fontsize=AXIS_LABEL_FS, fontweight='bold')
    ax.tick_params(axis='both', labelsize=TICK_LABEL_FS)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontweight('bold')
