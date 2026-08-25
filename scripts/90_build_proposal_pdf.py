"""
Render PROPOSAL.md to a print-quality PDF.

The PDF is a build artifact of the Markdown source, not a separately
maintained document -- so the numbers in it cannot drift away from the
numbers in the repo. Re-run this after any edit to PROPOSAL.md.

Chromium (via Playwright) does the typesetting because it is the only
engine available here that renders the figures, tables and page breaks
faithfully. No pandoc/LaTeX dependency.

    python scripts/90_build_proposal_pdf.py

Writes landing/brier-proposal.pdf so the landing page can serve it as a
static asset.
"""

from __future__ import annotations

import base64
import html as html_mod
import mimetypes
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "PROPOSAL.md"
OUT = ROOT / "landing" / "brier-proposal.pdf"

# ----------------------------------------------------------------------
# Inline math. The proposal uses only simple inline expressions -- no
# display math, no environments -- so a targeted substitution renders
# them correctly without a 300 KB KaTeX dependency in the page.
# Anything not matched here is passed through as literal text rather
# than silently mangled.
# ----------------------------------------------------------------------
_MATH_LITERAL = {
    r"\neq": "\u2260",
    r"\pm": "\u00b1",
    r"\cdot": "\u00b7",
    r"\times": "\u00d7",
    r"\to": "\u2192",
    r"\in": "\u2208",
    r"\sigma": "\u03c3",
    r"\text": "",
}

_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b\u207c\u207d\u207e\u207f")


def _render_math(expr: str) -> str:
    """Convert a small subset of inline TeX to styled HTML."""
    s = expr.strip()

    # \text{...} -> plain run
    s = re.sub(r"\\text\{([^}]*)\}", r"\1", s)

    # ^{...} and ^x -> real superscript where the characters allow it
    def sup(m: str) -> str:
        body = m.strip("{}")
        if all(ch in "0123456789+-=()n" for ch in body):
            return body.translate(_SUPERSCRIPT)
        return "<sup>%s</sup>" % html_mod.escape(body)

    s = re.sub(r"\^(\{[^}]*\}|\S)", lambda m: sup(m.group(1)), s)
    s = re.sub(r"_(\{[^}]*\}|\w)", lambda m: "<sub>%s</sub>" % html_mod.escape(m.group(1).strip("{}")), s)

    for tex, ch in _MATH_LITERAL.items():
        s = s.replace(tex, ch)

    # \{ \} escapes survive to literal braces
    s = s.replace(r"\{", "{").replace(r"\}", "}")
    s = re.sub(r"\\[a-zA-Z]+", lambda m: m.group(0)[1:], s)  # unknown macro -> its name
    return '<span class="math">%s</span>' % s


def _embed_image(src: str) -> str:
    """Inline a figure as a data URI so the PDF is self-contained."""
    p = (ROOT / src).resolve()
    if not p.is_file():
        raise SystemExit("figure not found: %s (referenced as %s)" % (p, src))
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return "data:%s;base64,%s" % (mime, base64.b64encode(p.read_bytes()).decode("ascii"))


def _inline(text: str) -> str:
    """Inline markdown -> HTML, with math protected from escaping."""
    slots: list[str] = []

    def stash(rendered: str) -> str:
        slots.append(rendered)
        return "\x00%d\x00" % (len(slots) - 1)

    # math and code first: their contents must not be treated as markdown
    text = re.sub(r"(?<!\$)\$([^$\n]+)\$(?!\$)", lambda m: stash(_render_math(m.group(1))), text)
    text = re.sub(r"`([^`]+)`", lambda m: stash("<code>%s</code>" % html_mod.escape(m.group(1))), text)

    text = html_mod.escape(text)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                  lambda m: '<img alt="%s" src="%s" />' % (m.group(1), _embed_image(m.group(2))), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"&lt;(https?://[^&\s]+)&gt;", r'<a href="\1">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)

    for i, rendered in enumerate(slots):
        text = text.replace("\x00%d\x00" % i, rendered)
    return text


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def md_to_html(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Convert the proposal's Markdown subset to HTML. Returns (body, toc)."""
    out: list[str] = []
    toc: list[tuple[int, str, str]] = []
    lines = md.split("\n")
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # fenced code
        if line.startswith("```"):
            lang = line[3:].strip().lower()
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            # Mermaid sources exist so PROPOSAL.md renders diagrams natively on
            # GitHub. In print the rendered PNG sits immediately above them, so
            # emitting the source too duplicates a page of content.
            if lang != "mermaid":
                out.append("<pre><code>%s</code></pre>" % html_mod.escape("\n".join(buf)))
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            txt = m.group(2).strip()
            sid = _slug(re.sub(r"[*`$\\]", "", txt))
            if lvl <= 3:
                toc.append((lvl, txt, sid))
            out.append('<h%d id="%s">%s</h%d>' % (lvl, sid, _inline(txt), lvl))
            i += 1
            continue

        # display math: $$ ... $$ alone on a line
        m = re.match(r"^\s*\$\$(.+?)\$\$\s*$", line)
        if m:
            out.append('<div class="mathblock">%s</div>' % _render_math(m.group(1)))
            i += 1
            continue

        # horizontal rule
        if re.match(r"^---+\s*$", line):
            out.append("<hr />")
            i += 1
            continue

        # table
        if line.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            def cells(row: str) -> list[str]:
                return [c.strip() for c in row.strip().strip("|").split("|")]

            head = cells(line)
            i += 2
            body = []
            while i < n and lines[i].lstrip().startswith("|"):
                body.append(cells(lines[i]))
                i += 1
            t = ["<table><thead><tr>"]
            t += ["<th>%s</th>" % _inline(c) for c in head]
            t.append("</tr></thead><tbody>")
            for row in body:
                t.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in row) + "</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue

        # blockquote
        if line.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % _inline(" ".join(buf)))
            continue

        # lists
        m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if m:
            ordered = bool(re.match(r"\d+\.", m.group(2)))
            tag = "ol" if ordered else "ul"
            items = []
            while i < n:
                mm = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[i])
                if not mm:
                    # continuation line belonging to the current item
                    if items and lines[i].strip() and lines[i].startswith(("  ", "\t")):
                        items[-1] += " " + lines[i].strip()
                        i += 1
                        continue
                    break
                items.append(mm.group(3))
                i += 1
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % _inline(it) for it in items), tag))
            continue

        # standalone image -> figure
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if m:
            out.append('<figure><img alt="%s" src="%s" /><figcaption>%s</figcaption></figure>'
                       % (m.group(1), _embed_image(m.group(2)), _inline(m.group(1))))
            i += 1
            continue

        if not line.strip():
            i += 1
            continue

        # paragraph
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|>|---+\s*$|\s*([-*+]|\d+\.)\s)", lines[i]) \
                and not re.match(r"^\s*\$\$.+\$\$\s*$", lines[i]) \
                and not lines[i].lstrip().startswith("|"):
            buf.append(lines[i])
            i += 1
        if buf:
            out.append("<p>%s</p>" % _inline(" ".join(buf)))

    return "\n".join(out), toc


CSS = """
@page { size: A4; margin: 20mm 18mm 18mm; }
@page :first { margin-top: 0; }

* { box-sizing: border-box; }
body {
  font-family: "Charter", "Georgia", "Times New Roman", serif;
  font-size: 10.2pt; line-height: 1.52; color: #16191d; margin: 0;
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4 { font-family: "Helvetica Neue", Arial, sans-serif; color: #0d1013; line-height: 1.22; }
h1 { font-size: 20pt; letter-spacing: -0.02em; margin: 0 0 6pt; }
h2 { font-size: 13pt; margin: 20pt 0 7pt; padding-bottom: 3pt; border-bottom: 0.6pt solid #c8ced6;
     break-after: avoid; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 14pt 0 5pt; break-after: avoid; page-break-after: avoid; }
h4 { font-size: 10pt; margin: 11pt 0 4pt; }
p { margin: 0 0 7pt; text-align: justify; hyphens: auto; orphans: 3; widows: 3; }
a { color: #1c4f8a; text-decoration: none; }
hr { border: 0; border-top: 0.6pt solid #d5dae1; margin: 13pt 0; }
strong { font-weight: 700; }

code, pre { font-family: "SF Mono", "Consolas", "Menlo", monospace; }
code { font-size: 8.8pt; background: #eef1f4; padding: 0.5pt 3pt; border-radius: 2pt; }
pre { background: #f5f7f9; border: 0.5pt solid #dde2e8; border-radius: 3pt; padding: 7pt 9pt;
      font-size: 8.4pt; line-height: 1.42; overflow-wrap: break-word; white-space: pre-wrap;
      break-inside: avoid; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }

.math { font-family: "Cambria Math", "Latin Modern Math", Georgia, serif; font-style: italic;
        white-space: nowrap; }
.math sub, .math sup { font-style: normal; }
.mathblock { font-family: "Cambria Math", "Latin Modern Math", Georgia, serif;
             font-style: italic; text-align: center; font-size: 11.4pt;
             margin: 11pt 0 12pt; break-inside: avoid; page-break-inside: avoid; }
.mathblock .math { font-size: inherit; white-space: normal; }

table { border-collapse: collapse; width: 100%; margin: 8pt 0 10pt; font-size: 8.9pt;
        break-inside: avoid; page-break-inside: avoid; }
th, td { border: 0.5pt solid #ccd2da; padding: 3.6pt 6pt; text-align: left; vertical-align: top; }
th { background: #eef1f5; font-family: "Helvetica Neue", Arial, sans-serif; font-weight: 600;
     font-size: 8.4pt; }
tbody tr:nth-child(even) { background: #fafbfc; }

blockquote { margin: 8pt 0; padding: 6pt 11pt; border-left: 2.2pt solid #9aa5b1;
             background: #f6f8fa; font-size: 9.6pt; break-inside: avoid; }
blockquote p { margin: 0; }

ul, ol { margin: 0 0 8pt; padding-left: 17pt; }
li { margin-bottom: 2.6pt; text-align: justify; }

figure { margin: 11pt 0 13pt; text-align: center; break-inside: avoid; page-break-inside: avoid; }
figure img { max-width: 100%; height: auto; border: 0.5pt solid #dde2e8; border-radius: 2pt; }
figcaption { font-size: 8.4pt; color: #58616b; margin-top: 4pt;
             font-family: "Helvetica Neue", Arial, sans-serif; text-align: center; }

/* ---- cover ---- */
.cover { height: 297mm; padding: 34mm 20mm 20mm; display: flex; flex-direction: column;
         break-after: page; page-break-after: always; }
.cover-mark { width: 34pt; height: 34pt; margin-bottom: 20pt; }
.cover h1 { font-size: 25pt; line-height: 1.16; letter-spacing: -0.025em; margin-bottom: 11pt;
            max-width: 15cm; }
.cover .sub { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 11.5pt; color: #4a545f;
              margin-bottom: 26pt; }
.cover .meta { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 9pt; color: #58616b;
               line-height: 1.85; }
.cover .meta b { color: #16191d; font-weight: 600; }
.cover .spacer { flex: 1; }
.cover .caveat { border: 0.6pt solid #d8b4ae; background: #fdf4f2; border-left: 2.4pt solid #C44536;
                 border-radius: 3pt; padding: 10pt 13pt; font-size: 9.2pt; line-height: 1.55;
                 color: #3d2320; max-width: 15cm; }
.cover .caveat b { color: #C44536; }

/* ---- contents ---- */
.toc { break-after: page; page-break-after: always; }
.toc h2 { margin-top: 0; }
.toc ol { list-style: none; padding: 0; margin: 0;
          font-family: "Helvetica Neue", Arial, sans-serif; font-size: 9.6pt; }
.toc li { margin: 0; padding: 3.4pt 0; border-bottom: 0.4pt dotted #d5dae1; }
.toc li.l3 { padding-left: 15pt; font-size: 9pt; color: #4a545f; }
.toc a { color: #16191d; }
"""

MARK = """<svg class="cover-mark" viewBox="0 0 24 24" fill="#16191d">
<g transform="rotate(-30 12 12)">
<circle cx="7.3" cy="3.2" r="1.45"/><rect x="5.5" y="4.7" width="3.6" height="14.6" rx="1.8"/>
<rect x="14.9" y="4.7" width="3.6" height="14.6" rx="1.8"/><circle cx="16.7" cy="20.8" r="1.45"/>
</g></svg>"""


def build() -> None:
    if not SRC.is_file():
        raise SystemExit("missing %s" % SRC)

    md = SRC.read_text(encoding="utf-8")

    # The cover reproduces the title block, so drop it from the flow.
    body_md = md
    m = re.search(r"^---\s*$", md, re.M)
    if m and md.lstrip().startswith("# "):
        body_md = md[m.end():]

    body, toc = md_to_html(body_md)

    toc_html = ['<div class="toc"><h2>Contents</h2><ol>']
    for lvl, txt, sid in toc:
        if lvl > 3:
            continue
        clean = re.sub(r"[*`$\\]", "", txt)
        toc_html.append('<li class="l%d"><a href="#%s">%s</a></li>' % (lvl, sid, html_mod.escape(clean)))
    toc_html.append("</ol></div>")

    page = """<!doctype html><html lang="en"><head><meta charset="utf-8" />
<title>Brier — Confidence-Calibrated Slashing</title><style>%s</style></head><body>
<div class="cover">
  %s
  <h1>Brier: Confidence-Calibrated Slashing for On-Chain AI Decision Accountability</h1>
  <div class="sub">A research proposal with a measured v0 prototype</div>
  <div class="meta">
    <div><b>Version</b> &nbsp; v0 (prototype)</div>
    <div><b>Date</b> &nbsp; August 2026</div>
    <div><b>Repository</b> &nbsp; <a href="https://github.com/Sagexd08/Brier">github.com/Sagexd08/Brier</a></div>
  </div>
  <div class="spacer"></div>
  <div class="caveat">
    <b>This is a mechanism and a measured prototype, not a deployable protocol.</b>
    Only the calibration head is zero-knowledge proved &mdash; its input logit is
    unverified, dispute resolution rests on a single administrative key, there is
    no unbonding period, and the figures reported here come from a local chain.
    Section&nbsp;7 states each limitation in full; Section&nbsp;8 sets out what
    closing them would take.
  </div>
</div>
%s
%s
</body></html>""" % (CSS, MARK, "".join(toc_html), body)

    tmp = OUT.parent / "_proposal_render.html"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(page, encoding="utf-8")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright not installed:  pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.goto(tmp.as_uri(), wait_until="networkidle")
        pg.pdf(
            path=str(OUT),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template='<div style="font:7.5pt Helvetica,Arial;color:#98a1ab;width:100%;'
                            'padding:0 18mm;text-align:right;">Brier &mdash; v0 proposal</div>',
            footer_template='<div style="font:7.5pt Helvetica,Arial;color:#98a1ab;width:100%;'
                            'padding:0 18mm;display:flex;justify-content:space-between;">'
                            '<span>github.com/Sagexd08/Brier</span>'
                            '<span class="pageNumber"></span></div>',
            margin={"top": "16mm", "bottom": "15mm", "left": "18mm", "right": "18mm"},
        )
        browser.close()

    tmp.unlink(missing_ok=True)

    kb = OUT.stat().st_size / 1024
    print("wrote %s (%.0f KB)" % (OUT.relative_to(ROOT), kb))
    print("sections in contents: %d" % len([t for t in toc if t[0] <= 3]))


if __name__ == "__main__":
    sys.exit(build())
