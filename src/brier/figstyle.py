"""Shared figure style, so plots read as part of the paper rather than as slides.

The figures previously used matplotlib defaults: DejaVu Sans against a body set
in Computer Modern, a "Figure X --" title baked into the image duplicating the
caption underneath it, visible gridlines, and a saturated categorical palette.
Each of those is a small thing; together they are why the figures looked pasted
in from somewhere else.

Four decisions, and the reasoning matters more than the values:

1. **Computer Modern, from the repository's own font files.** The paper body is
   set in CM (see `scripts/89_fetch_fonts.py`), so a figure in DejaVu Sans is
   visibly a different document. The .woff files are converted to .ttf on first
   use because matplotlib cannot read woff. If conversion fails the style falls
   back to any available serif rather than failing the build -- a figure in the
   wrong font is worse than one in the right font, but far better than no
   figure.

2. **No title inside the figure.** The caption already names it. A title inside
   the image means the reader sees "Figure 4" twice, at two sizes, in two
   typefaces. Panel headings stay, because those label panels rather than the
   figure.

3. **Colour is redundant, never load-bearing.** Anything colour distinguishes is
   also distinguished by marker, line style or position, so the figures survive
   greyscale printing and the ~8% of male readers with colour-vision deficiency.
   The palette is muted for the same reason a paper is not a dashboard:
   saturated primaries signal "slide deck".

4. **Hairline rules, no grid.** Gridlines compete with data at print sizes. Where
   a reference value matters it gets an explicit annotated line instead.
"""
from __future__ import annotations

import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FONT_WOFF = _ROOT / "artifacts" / "fonts"
_FONT_TTF = _FONT_WOFF / "ttf"

# Muted, print-safe, and distinguishable in greyscale by lightness alone.
INK = "#1c1c1c"        # body text and axes
MUTED = "#6e6e6e"      # secondary annotation
RULE = "#bfbfbf"       # hairlines
BEFORE = "#9a9a9a"     # "uncalibrated" / baseline series
AFTER = "#2b5f8e"      # "calibrated" / treatment series
ACCENT = "#a4341f"     # reference lines and the quantity being integrated
SUPPORT = "#3f7a5c"    # third series where one is needed


def _ensure_ttf() -> bool:
    """Convert the bundled CM .woff faces to .ttf once. True if CM is usable."""
    if _FONT_TTF.exists() and any(_FONT_TTF.glob("*.ttf")):
        return True
    if not _FONT_WOFF.exists():
        return False
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return False
    try:
        _FONT_TTF.mkdir(parents=True, exist_ok=True)
        for w in _FONT_WOFF.glob("*.woff"):
            f = TTFont(str(w))
            f.flavor = None
            f.save(str(_FONT_TTF / (w.stem + ".ttf")))
        return any(_FONT_TTF.glob("*.ttf"))
    except Exception:
        return False


def use(scale: float = 1.0) -> str:
    """Apply the paper's figure style. Returns the font family actually used.

    `scale` multiplies every font size together, for figures that are placed at
    less than full text width.
    """
    import matplotlib
    from matplotlib import font_manager

    family = "serif"
    if _ensure_ttf():
        for ttf in _FONT_TTF.glob("*.ttf"):
            try:
                font_manager.fontManager.addfont(str(ttf))
            except Exception:
                pass
        names = {f.name for f in font_manager.fontManager.ttflist}
        if "CMU Serif" in names:
            family = "CMU Serif"

    if family == "serif":
        warnings.warn(
            "Computer Modern unavailable; figures will not match the paper body. "
            "Run scripts/89_fetch_fonts.py, or install fonttools.",
            stacklevel=2,
        )

    matplotlib.rcParams.update({
        "font.family": family,
        # Math set in the same face, so an axis label reading "$T$" does not
        # switch typeface mid-word.
        "mathtext.fontset": "cm",
        "font.size": 10.0 * scale,
        "axes.titlesize": 10.0 * scale,
        "axes.labelsize": 10.0 * scale,
        "xtick.labelsize": 9.0 * scale,
        "ytick.labelsize": 9.0 * scale,
        "legend.fontsize": 8.5 * scale,

        "text.color": INK,
        "axes.labelcolor": INK,
        "axes.edgecolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,

        # No grid, no top/right spines: the data is the ink.
        "axes.grid": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.direction": "out",
        "ytick.direction": "out",

        "legend.frameon": False,
        "legend.handlelength": 1.6,
        "legend.borderpad": 0.3,

        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 400,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "figure.dpi": 140,

        "lines.linewidth": 1.2,
        "lines.markersize": 4.5,
        "patch.linewidth": 0.6,
    })
    return family


def panel_label(ax, text: str, dx: float = -0.085, dy: float = 1.06):
    """(a), (b), (c) in the top-left, the way a journal numbers panels.

    Placed in axes coordinates outside the data area so it never collides with
    a data point, which is the usual failure of in-axes labels.
    """
    ax.text(dx, dy, text, transform=ax.transAxes, fontsize=10.5,
            fontweight="bold", va="bottom", ha="left", color=INK)


def note(ax, text: str, loc: str = "upper left", **kw):
    """A small annotation block, hairline-boxed rather than filled.

    A filled box hides the data underneath it; a hairline says "this is
    annotation" without occluding anything.
    """
    xy = {"upper left": (0.035, 0.965, "left", "top"),
          "upper right": (0.965, 0.965, "right", "top"),
          "lower left": (0.035, 0.035, "left", "bottom"),
          "lower right": (0.965, 0.035, "right", "bottom")}[loc]
    ax.text(xy[0], xy[1], text, transform=ax.transAxes, ha=xy[2], va=xy[3],
            fontsize=8.5, color=INK, linespacing=1.35,
            bbox=dict(boxstyle="square,pad=0.42", facecolor="white",
                      edgecolor=RULE, linewidth=0.5), **kw)
