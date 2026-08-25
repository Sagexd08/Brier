"""Render the SVG figures to PNG for PDF export, via headless Chromium.

A bare .svg document makes Chromium's full-page screenshot hang, so each SVG is
embedded in a minimal HTML shell with an explicit viewport instead.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIGS = ROOT / "figures"

TARGETS = [
    ("figure-a-architecture.svg", 1180, 700),
    ("figure-c-threat-model.svg", 1180, 1060),
]

SHELL = """<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#fff}svg{display:block}</style>
{svg}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    for name, w, h in TARGETS:
        src = FIGS / name
        if not src.exists():
            print(f"skip (absent): {name}")
            continue
        tmp = FIGS / (src.stem + ".render.html")
        tmp.write_text(SHELL.replace("{svg}", src.read_text(encoding="utf-8")),
                       encoding="utf-8")
        page = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
        page.goto(tmp.as_uri())
        page.wait_for_timeout(350)
        out = src.with_suffix(".png")
        page.screenshot(path=str(out))
        page.close()
        tmp.unlink()
        print(f"wrote {out}")
    b.close()
