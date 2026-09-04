"""Render the SVG figures to PNG for PDF export, via headless Chromium.

A bare .svg document makes Chromium's full-page screenshot hang, so each SVG is
embedded in a minimal HTML shell with an explicit viewport instead.

The shell also embeds Computer Modern as base64 @font-face rules. Chromium has
no CM installed, so without this the SVGs silently fall back to Georgia and the
diagrams stop matching the paper body -- which is exactly the mismatch these
figures were redrawn to fix. A silent font fallback is worse than a loud
failure, so the absence of the font files is reported rather than ignored.
"""
import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIGS = ROOT / "figures"
FONTS = ROOT / "artifacts" / "fonts"

TARGETS = [
    ("figure-a-architecture.svg", 1060, 604),
    ("figure-b-sequence.svg", 1060, 600),
    ("figure-c-threat-model.svg", 1060, 640),
]

# woff files fetched by scripts/89_fetch_fonts.py, keyed by the weight/style
# they provide. Same faces the PDF builder embeds.
FACES = [
    ("cmunrm.woff", "normal", "normal"),
    ("cmunbx.woff", "bold", "normal"),
    ("cmunti.woff", "normal", "italic"),
    ("cmunbi.woff", "bold", "italic"),
]


def font_css() -> str:
    rules = []
    missing = []
    for fname, weight, style in FACES:
        f = FONTS / fname
        if not f.exists():
            missing.append(fname)
            continue
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        rules.append(
            "@font-face{font-family:'CMU Serif';font-weight:%s;font-style:%s;"
            "src:url(data:font/woff;base64,%s) format('woff');}"
            % (weight, style, b64)
        )
    if missing:
        print(f"  WARNING: missing font faces {missing} -- diagrams will not "
              f"match the paper body. Run scripts/89_fetch_fonts.py.")
    return "".join(rules)


SHELL = """<!doctype html><meta charset="utf-8">
<style>%s
html,body{margin:0;padding:0;background:#fff}svg{display:block}</style>
%s"""

css = font_css()

with sync_playwright() as p:
    b = p.chromium.launch()
    for name, w, h in TARGETS:
        src = FIGS / name
        if not src.exists():
            print(f"skip (absent): {name}")
            continue
        tmp = FIGS / (src.stem + ".render.html")
        tmp.write_text(SHELL % (css, src.read_text(encoding="utf-8")), encoding="utf-8")
        page = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=3)
        page.goto(tmp.as_uri())
        # Wait for the embedded faces to be applied; screenshotting before they
        # load silently captures the fallback font.
        page.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)
        page.wait_for_timeout(250)
        out = src.with_suffix(".png")
        page.screenshot(path=str(out))
        page.close()
        tmp.unlink()
        print(f"wrote {out}")
    b.close()
