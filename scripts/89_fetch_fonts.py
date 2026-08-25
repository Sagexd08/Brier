"""Fetch and cache the Computer Modern web fonts used by the PDF build.

The proposal is typeset to look like the LaTeX papers it will sit alongside,
which means Computer Modern rather than a system serif. The faces are cached
under artifacts/fonts/ and embedded as data URIs at build time, so a rebuild
works offline and produces a byte-identical result on any machine.

    python scripts/89_fetch_fonts.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "artifacts" / "fonts"

BASE = "https://cdn.jsdelivr.net/gh/dreampulse/computer-modern-web-font@master/font"

FACES = {
    "cmunrm.woff": f"{BASE}/Serif/cmunrm.woff",   # roman
    "cmunbx.woff": f"{BASE}/Serif/cmunbx.woff",   # bold
    "cmunti.woff": f"{BASE}/Serif/cmunti.woff",   # italic
    "cmunbi.woff": f"{BASE}/Serif/cmunbi.woff",   # bold italic
    "cmunss.woff": f"{BASE}/Sans/cmunss.woff",    # sans (captions/headers)
    "cmunsx.woff": f"{BASE}/Sans/cmunsx.woff",    # sans bold
    "cmuntt.woff": f"{BASE}/Typewriter/cmuntt.woff",  # typewriter
}


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    got = 0
    for name, url in FACES.items():
        target = DEST / name
        if target.exists() and target.stat().st_size > 1000:
            print(f"  cached  {name}")
            got += 1
            continue
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                blob = r.read()
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED  {name}: {exc}")
            continue
        target.write_bytes(blob)
        print(f"  fetched {name}  ({len(blob) / 1024:.0f} KB)")
        got += 1

    if got < len(FACES):
        print(f"\n  {len(FACES) - got} face(s) missing; the build falls back to a "
              f"system serif stack.")
        return 1
    print(f"\n  {got}/{len(FACES)} faces available in "
          f"{DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
