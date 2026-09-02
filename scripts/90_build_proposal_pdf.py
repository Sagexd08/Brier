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
    r"\leq": "\u2264",
    r"\geq": "\u2265",
    r"\pm": "\u00b1",
    r"\cdot": "\u00b7",
    r"\times": "\u00d7",
    r"\to": "\u2192",
    r"\in": "\u2208",
    r"\approx": "\u2248",
    r"\ll": "\u226a",
    r"\gg": "\u226b",
    r"\sigma": "\u03c3",
    r"\alpha": "\u03b1",
    r"\lambda": "\u03bb",
    r"\delta": "\u03b4",
    r"\rho": "\u03c1",
    r"\tau": "\u03c4",
    r"\kappa": "\u03ba",
    r"\eta": "\u03b7",
    r"\zeta": "\u03b6",
    r"\Lambda": "\u039b",
    r"\Omega": "\u03a9",
    r"\hat": "",
    r"\mathbb": "",
    r"\log": "log",
    r"\min": "min",
    r"\max": "max",
    r"\sum": "\u2211",
    r"\frac": "",
    r"\beta": "\u03b2",
    r"\gamma": "\u03b3",
    r"\epsilon": "\u03b5",
    r"\theta": "\u03b8",
    r"\phi": "\u03c6",
    r"\omega": "\u03c9",
    r"\Sigma": "\u03a3",
    r"\Delta": "\u0394",
    r"\mu": "\u03bc",
    r"\nu": "\u03bd",
    r"\Theta": "\u0398",
    r"\infty": "\u221e",
    r"\ldots": "\u2026",
    r"\dots": "\u2026",
    r"\left": "",
    r"\right": "",
    r"\!": "",
    r"\,": "\u2009",
    r"\;": "\u2002",
    r"\quad": "\u2003",
    r"\text": "",
}

_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b\u207c\u207d\u207e\u207f")


def _render_math(expr: str) -> str:
    """Convert a small subset of inline TeX to styled HTML."""
    s = expr.strip()

    # \text{...} -> plain run
    s = re.sub(r"\\text\{([^}]*)\}", r"\1", s)

    # \frac{a}{b} -> a/b. A real fraction needs stacked layout this renderer
    # does not have, and an inline solidus is the conventional fallback.
    s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)

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

    # A hyphen-minus set in an italic serif reads as a hyphen, which is wrong
    # in mathematics. Promote it to U+2212 wherever it is a binary or unary
    # operator rather than part of an identifier.
    s = re.sub(r"(?<=[0-9A-Za-z\)\]])\s*-\s*(?=[0-9A-Za-z\(\[])", "\u2009\u2212\u2009", s)
    s = re.sub(r"(?<=[\(\[])-", "\u2212", s)

    # Thin space around the remaining binary operators for LaTeX-like colour.
    # The sub/sup tags emitted above contain < and >, so they are stashed
    # first -- without this the pass rewrites them into literal "< sub >".
    tags: list[str] = []

    def _stash_tag(m: "re.Match[str]") -> str:
        tags.append(m.group(0))
        return "\x01%d\x01" % (len(tags) - 1)

    s = re.sub(r"</?su[bp]>", _stash_tag, s)
    s = re.sub(r"\s*([+=<>])\s*", "\u2009\\1\u2009", s)
    for idx, tag in enumerate(tags):
        s = s.replace("\x01%d\x01" % idx, tag)

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


# ----------------------------------------------------------------------
# Numbered environments.
#
# The proposal states results as theorems, propositions and definitions, so
# the renderer provides amshtm-style environments rather than leaving them as
# bold-run-in paragraphs. Numbering is sequential per environment class, which
# is what a reader of a paper expects.
# ----------------------------------------------------------------------
ENVIRONMENTS = {
    "definition": ("Definition", "defn"),
    "assumption": ("Assumption", "defn"),
    "proposition": ("Proposition", "plain"),
    "theorem": ("Theorem", "plain"),
    "lemma": ("Lemma", "plain"),
    "corollary": ("Corollary", "plain"),
    "remark": ("Remark", "rem"),
}


class Counters:
    """Per-class counters for environments, tables and figures."""

    def __init__(self) -> None:
        self.env: dict[str, int] = {}
        self.table = 0
        self.figure = 0

    def next_env(self, kind: str) -> int:
        self.env[kind] = self.env.get(kind, 0) + 1
        return self.env[kind]

    def next_table(self) -> int:
        self.table += 1
        return self.table

    def next_figure(self) -> int:
        self.figure += 1
        return self.figure


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def md_to_html(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Convert the proposal's Markdown subset to HTML. Returns (body, toc)."""
    ctr = Counters()
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

        # ---- numbered environment:  :::proposition Optional title
        m = re.match(r"^:::(\w+)\s*(.*)$", line)
        if m and m.group(1).lower() in ENVIRONMENTS:
            kind = m.group(1).lower()
            title = m.group(2).strip()
            label, style = ENVIRONMENTS[kind]
            num = ctr.next_env(label)
            i += 1
            buf = []
            while i < n and not lines[i].startswith(":::"):
                buf.append(lines[i])
                i += 1
            i += 1  # closing :::
            head = "%s %d" % (label, num)
            if title:
                head += " (%s)" % title
            body = _inline(" ".join(x for x in buf if x.strip()))
            out.append(
                '<div class="thm thm--%s"><span class="head">%s.</span> '
                '<span class="body">%s</span></div>' % (style, head, body)
            )
            continue

        # ---- proof environment
        if re.match(r"^:::proof\s*$", line, re.I):
            i += 1
            buf = []
            while i < n and not lines[i].startswith(":::"):
                buf.append(lines[i])
                i += 1
            i += 1
            body = _inline(" ".join(x for x in buf if x.strip()))
            out.append(
                '<div class="proof"><span class="head">Proof.</span> %s'
                '<span class="qed">&#9633;</span></div>' % body
            )
            continue

        # ---- table caption:  Table: text   (must precede the table)
        #
        # A caption is normally wrapped across several source lines, so keep
        # consuming until a blank line or the table itself. Taking only the
        # first line left the remainder to be re-parsed as a paragraph, which
        # is how it escaped the caption and landed under it.
        m = re.match(r"^Table:\s*(.+)$", line)
        if m:
            parts = [m.group(1).strip()]
            i += 1
            while (i < n and lines[i].strip()
                   and not lines[i].lstrip().startswith("|")
                   and not lines[i].startswith(":::")
                   and not re.match(r"^(#{1,6}\s|```|Table:)", lines[i])):
                parts.append(lines[i].strip())
                i += 1
            num = ctr.next_table()
            out.append('<p class="tabcaption"><span class="lab">Table %d:</span> %s</p>'
                       % (num, _inline(" ".join(parts))))
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

        # standalone image -> numbered figure
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if m:
            num = ctr.next_figure()
            caption = m.group(1)
            # Strip any hand-written "Figure N —" prefix; numbering is automatic.
            caption = re.sub(r"^Figure\s+\d+\s*[-\u2013\u2014:]\s*", "", caption)
            out.append(
                '<figure><img alt="%s" src="%s" />'
                '<figcaption><span class="lab">Figure %d:</span> %s</figcaption></figure>'
                % (caption[:60], _embed_image(m.group(2)), num, _inline(caption))
            )
            i += 1
            continue

        if not line.strip():
            i += 1
            continue

        # paragraph
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|>|---+\s*$|\s*([-*+]|\d+\.)\s)", lines[i]) \
                and not re.match(r"^\s*\$\$.+\$\$\s*$", lines[i]) \
                and not lines[i].startswith(":::") \
                and not re.match(r"^Table:\s", lines[i]) \
                and not lines[i].lstrip().startswith("|"):
            buf.append(lines[i])
            i += 1
        if buf:
            out.append("<p>%s</p>" % _inline(" ".join(buf)))

    return "\n".join(out), toc


FONT_DIR = ROOT / "artifacts" / "fonts"

# Computer Modern, embedded as data URIs so the PDF is self-contained and the
# build is reproducible offline. Falls back to a system serif if the cache is
# missing (run scripts/89_fetch_fonts.py to populate it).
_FACES = [
    ("CMU Serif", "cmunrm.woff", "normal", "400"),
    ("CMU Serif", "cmunbx.woff", "normal", "700"),
    ("CMU Serif", "cmunti.woff", "italic", "400"),
    ("CMU Serif", "cmunbi.woff", "italic", "700"),
    ("CMU Sans", "cmunss.woff", "normal", "400"),
    ("CMU Sans", "cmunsx.woff", "normal", "700"),
    ("CMU Typewriter", "cmuntt.woff", "normal", "400"),
]


def font_face_css() -> str:
    out = []
    for family, filename, style, weight in _FACES:
        f = FONT_DIR / filename
        if not f.is_file():
            continue
        uri = "data:font/woff;base64," + base64.b64encode(f.read_bytes()).decode("ascii")
        out.append(
            "@font-face{font-family:'%s';src:url(%s) format('woff');"
            "font-style:%s;font-weight:%s;font-display:block;}"
            % (family, uri, style, weight)
        )
    return "\n".join(out)


SERIF = "'CMU Serif', 'Latin Modern Roman', 'CMU Serif Roman', Cambria, Georgia, 'Times New Roman', serif"
SANS = "'CMU Sans', 'Latin Modern Sans', 'Helvetica Neue', Arial, sans-serif"
MONO = "'CMU Typewriter', 'Latin Modern Mono', Consolas, 'Courier New', monospace"

CSS = """
@page {
  size: A4;
  margin: 26mm 24mm 24mm;
}
@page :first { margin-top: 0; }

* { box-sizing: border-box; }

html { -webkit-font-smoothing: antialiased; }

body {
  font-family: %(serif)s;
  font-size: 10.6pt;
  line-height: 1.34;
  color: #000000;
  margin: 0;
  text-align: justify;
  hyphens: auto;
  -webkit-hyphens: auto;
}

/* ---------------- headings ---------------- */
h1, h2, h3, h4 {
  font-family: %(serif)s;
  color: #000;
  line-height: 1.2;
  text-align: left;
  hyphens: none;
}
h2 {
  font-size: 12.4pt;
  font-weight: 700;
  margin: 17pt 0 7pt;
  break-after: avoid; page-break-after: avoid;
}
h3 {
  font-size: 11pt;
  font-weight: 700;
  margin: 13pt 0 5pt;
  color: #1a3d6d;
  break-after: avoid; page-break-after: avoid;
}
h4 {
  font-size: 10.6pt;
  font-weight: 700;
  margin: 10pt 0 3pt;
  break-after: avoid; page-break-after: avoid;
}

p { margin: 0 0 5.5pt; orphans: 3; widows: 3; }
p + p { text-indent: 1.4em; }

a { color: #1a3d6d; text-decoration: none; }
strong { font-weight: 700; }
em { font-style: italic; }

hr { border: 0; border-top: 0.5pt solid #bbb; margin: 12pt 0; }

/* ---------------- abstract ---------------- */
.abstract {
  margin: 0 0 14pt;
  padding: 10pt 0 0;
  border-top: 0.9pt solid #000;
}
.abstract-end { border-bottom: 0.9pt solid #000; margin-bottom: 15pt; padding-bottom: 11pt; }
.abstract h2 {
  font-size: 11pt;
  text-align: center;
  margin: 0 0 6pt;
}
.abstract p { font-size: 9.9pt; line-height: 1.32; margin-bottom: 4pt; }
.abstract p + p { text-indent: 1.4em; }

/* ---------------- code ---------------- */
code, pre { font-family: %(mono)s; }
code {
  font-size: 9.1pt;
  overflow-wrap: anywhere;
}
pre {
  background: #f7f7f7;
  border: 0.4pt solid #ddd;
  padding: 6pt 8pt;
  font-size: 8.5pt;
  line-height: 1.35;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  text-align: left;
  hyphens: none;
  break-inside: avoid; page-break-inside: avoid;
  margin: 7pt 0 9pt;
}
pre code { font-size: inherit; }

/* ---------------- math ---------------- */
.math {
  font-family: %(serif)s;
  font-style: italic;
  white-space: nowrap;
}
.math sub, .math sup { font-style: normal; font-size: 0.72em; }
.mathblock {
  font-family: %(serif)s;
  font-style: italic;
  text-align: center;
  font-size: 11.4pt;
  margin: 9pt 0 10pt;
  break-inside: avoid;
}
.mathblock .math { font-size: inherit; white-space: normal; }

/* ---------------- tables: booktabs ---------------- */
table {
  border-collapse: collapse;
  width: 100%%;
  margin: 3pt 0 11pt;
  font-size: 9pt;
  break-inside: avoid; page-break-inside: avoid;
  text-align: left;
  hyphens: none;
}
thead tr { border-top: 1.1pt solid #000; border-bottom: 0.5pt solid #000; }
tbody tr:last-child { border-bottom: 1.1pt solid #000; }
th, td {
  border: 0;
  padding: 2.9pt 7pt 2.9pt 0;
  vertical-align: top;
}
th { font-weight: 700; }
/* numeric-looking columns read better flush right */
td.num, th.num { text-align: right; padding-right: 0; }

.tabcaption {
  font-family: %(sans)s;
  font-size: 8.6pt;
  line-height: 1.34;
  margin: 11pt 0 0;
  text-align: left;
  hyphens: none;
  break-after: avoid; page-break-after: avoid;
}
.tabcaption .lab { font-weight: 700; color: #a03020; }

/* ---------------- figures ---------------- */
figure {
  margin: 12pt 0 13pt;
  text-align: center;
  break-inside: avoid; page-break-inside: avoid;
}
figure img { max-width: 100%%; height: auto; }
figcaption {
  font-family: %(sans)s;
  font-size: 8.6pt;
  line-height: 1.34;
  margin-top: 6pt;
  text-align: left;
  hyphens: none;
}
figcaption .lab { font-weight: 700; color: #a03020; }

/* ---------------- theorem environments ---------------- */
.thm {
  margin: 8pt 0 8pt;
  break-inside: avoid; page-break-inside: avoid;
}
.thm .head { font-weight: 700; }
.thm .name { font-weight: 700; }
/* Statement environments are italic, as in amsthm's plain style. */
.thm--plain .body { font-style: italic; }
/* Definitions and remarks stay upright, as in amsthm's definition style. */
.thm--defn .body, .thm--rem .body { font-style: normal; }
.thm .body { display: inline; }
.thm p { display: inline; margin: 0; text-indent: 0; }

.proof {
  margin: 7pt 0 9pt;
  break-inside: avoid; page-break-inside: avoid;
}
.proof .head { font-style: italic; }
.proof .qed { float: right; }
.proof p { display: inline; margin: 0; text-indent: 0; }
.proof::after { content: ""; display: block; clear: both; }

/* ---------------- lists ---------------- */
ul, ol { margin: 0 0 6pt; padding-left: 15pt; }
li { margin-bottom: 1.8pt; }

blockquote {
  margin: 7pt 0 8pt 14pt;
  font-size: 9.7pt;
  break-inside: avoid;
}
blockquote p { margin: 0; text-indent: 0; }

/* ---------------- title block ---------------- */
.titleblock {
  padding: 34mm 0 0;
  text-align: center;
  margin-bottom: 16pt;
}
.titleblock .t1 {
  font-size: 17.5pt;
  font-weight: 700;
  line-height: 1.24;
  margin-bottom: 3pt;
}
.titleblock .t2 {
  font-size: 13.4pt;
  font-weight: 700;
  line-height: 1.28;
  margin-bottom: 16pt;
}
.titleblock .author { font-size: 11.4pt; font-weight: 700; margin-bottom: 2pt; }
.titleblock .affil { font-size: 10.4pt; margin-bottom: 12pt; }
.titleblock .meta { font-size: 9pt; }
.titleblock .meta span { margin: 0 7pt; }

/* ---------------- contents ---------------- */
.toc { break-after: page; page-break-after: always; }
.toc h2 { font-size: 12.4pt; margin: 0 0 8pt; }
.toc ol {
  list-style: none; padding: 0; margin: 0; font-size: 9pt;
  column-count: 2; column-gap: 20pt;
}
.toc li { margin: 0; padding: 1.15pt 0; break-inside: avoid; }
.toc li.l2 { font-weight: 700; margin-top: 3pt; }
.toc li.l3 { padding-left: 13pt; font-size: 8.7pt; font-weight: 400; }
.toc a { color: #000; }

.caveat {
  border: 0.6pt solid #c0a49f;
  background: #fdf6f4;
  border-left: 2.2pt solid #a03020;
  padding: 8pt 11pt;
  font-size: 9.4pt;
  line-height: 1.36;
  margin: 14pt 0 0;
  text-align: left;
}
.caveat b { color: #a03020; }
""" % {"serif": SERIF, "sans": SANS, "mono": MONO}


def build() -> None:
    if not SRC.is_file():
        raise SystemExit("missing %s" % SRC)

    md = SRC.read_text(encoding="utf-8")

    # The title block reproduces the heading, so drop it from the flow.
    body_md = md
    m = re.search(r"^---\s*$", md, re.M)
    if m and md.lstrip().startswith("# "):
        body_md = md[m.end():]

    # The abstract is set apart from the body, LaTeX-style, so it is lifted
    # out of the normal flow and rendered between rules.
    abstract_html = ""
    am = re.search(r"^## Abstract\s*$(.*?)^---\s*$", body_md, re.M | re.S)
    if am:
        abstract_body, _ = md_to_html(am.group(1).strip())
        abstract_html = (
            '<div class="abstract"><h2>Abstract</h2>'
            '<div class="abstract-end">%s</div></div>' % abstract_body
        )
        body_md = body_md[am.end():]

    body, toc = md_to_html(body_md)

    toc_html = ['<div class="toc"><h2>Contents</h2><ol>']
    for lvl, txt, sid in toc:
        if lvl > 3:
            continue
        clean = re.sub(r"[*`$\\]", "", txt)
        toc_html.append('<li class="l%d"><a href="#%s">%s</a></li>'
                        % (lvl, sid, html_mod.escape(clean)))
    toc_html.append("</ol></div>")

    page = """<!doctype html><html lang="en"><head><meta charset="utf-8" />
<title>What Does the Proof Actually Buy? Confidence-Calibrated Slashing</title>
<style>%s</style><style>%s</style></head><body>
<div class="titleblock">
  <div class="t1">What Does the Proof Actually Buy?</div>
  <div class="t2">Confidence-Calibrated Slashing for<br />On-Chain AI Decision Accountability</div>
  <div class="author">Sohom Chatterjee</div>
  <div class="affil">Sister Nivedita University</div>
  <div class="meta">
    <span>Version v0 (prototype)</span>&middot;<span>August 2026</span>&middot;<span>Artifact: circuits, contracts, benchmark, analysis</span>
  </div>
  <div class="caveat">
    <b>This is a mechanism and a measured prototype, not a deployable protocol.</b>
    Only the calibration head is zero-knowledge proved &mdash; its input logit is
    unverified, dispute resolution rests on an admin-appointed N-of-M committee
    whose collusion carries the authority a single key would, and an unvalidated
    collusion detector can withhold a claimant's payout. Section&nbsp;7 states
    each limitation in full; Section&nbsp;8 separates what has shipped from what
    remains.
  </div>
</div>
%s
%s
%s
</body></html>""" % (font_face_css(), CSS, abstract_html, "".join(toc_html), body)

    tmp = OUT.parent / "_proposal_render.html"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(page, encoding="utf-8")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright not installed:  pip install playwright && playwright install chromium")

    running_title = "What Does the Proof Actually Buy? Confidence-Calibrated Slashing for On-Chain AI Decision Accountability"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.goto(tmp.as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(500)
        pg.pdf(
            path=str(OUT),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template=(
                '<div style="font:8pt \'CMU Serif\', Cambria, Georgia, serif;color:#000;'
                'width:100%;padding:0 24mm;border-bottom:0.4pt solid #999;'
                'padding-bottom:3pt;margin-bottom:4pt;">' + running_title + "</div>"
            ),
            footer_template=(
                '<div style="font:9pt \'CMU Serif\', Cambria, Georgia, serif;color:#000;'
                'width:100%;text-align:center;"><span class="pageNumber"></span></div>'
            ),
            margin={"top": "20mm", "bottom": "16mm", "left": "24mm", "right": "24mm"},
        )
        browser.close()

    tmp.unlink(missing_ok=True)

    kb = OUT.stat().st_size / 1024
    print("wrote %s (%.0f KB)" % (OUT.relative_to(ROOT), kb))
    print("sections in contents: %d" % len([t for t in toc if t[0] <= 3]))


if __name__ == "__main__":
    sys.exit(build())
