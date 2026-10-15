"""Shared publication style for every figure in the manuscript.

Import and call `apply()` before building any figure, and use `FIGSIZE` for
every `plt.subplots(...)` call so all PDFs share identical canvas dimensions,
font, and theme. `save()` standardizes the export settings.
"""
from __future__ import annotations

from pathlib import Path
import matplotlib.pyplot as plt

# Times New Roman is not installed on this Linux toolchain; Liberation Serif is
# metric-compatible with Times New Roman and is the standard free substitute for
# exactly this situation. matplotlib falls through the family list in order, so
# a machine that does have Times New Roman will use it automatically.
FONT_FAMILY = ["Times New Roman", "Liberation Serif", "DejaVu Serif", "serif"]
FONT_SIZE = 12

# Every figure in the manuscript shares this canvas size for visual consistency.
FIGSIZE = (7.2, 4.6)

# Colorblind-safe (Okabe-Ito derived) palette used across all figures.
COLORS = {
    "gray": "#6B7280",
    "blue": "#1877B8",
    "orange": "#D55E00",
    "green": "#009E73",
    "navy": "#1F4E79",
    "light_blue": "#D9EAF7",
}


def apply() -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": FONT_FAMILY,
        "font.size": FONT_SIZE,
        "axes.titlesize": FONT_SIZE,
        "axes.labelsize": FONT_SIZE,
        "xtick.labelsize": FONT_SIZE,
        "ytick.labelsize": FONT_SIZE,
        "legend.fontsize": FONT_SIZE,
        "figure.titlesize": FONT_SIZE,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.6,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        "pdf.fonttype": 42,
    })


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print("saved", path)
