"""Phase 3b: mechanised guard against claim inflation.

docs/PHASE3B_TRUST_MODEL.md fixes the vocabulary for describing dispute
resolution BEFORE the code was written. This test enforces that list, so a
later doc edit cannot quietly upgrade "bounded trust" to "decentralized".

It is deliberately dumb (a grep). A smarter check would be easier to talk
past; the point is that the forbidden words simply cannot appear.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

DOCS = [
    ROOT / "README.md",
    ROOT / "PAPER.md",
    ROOT / "RESULTS.md",
    ROOT / "docs" / "PHASE3B_TRUST_MODEL.md",
]

# Words that would overstate what an N-of-M committee provides.
FORBIDDEN = [
    r"decentrali[sz]ed dispute",
    r"trustless",
    r"permissionless",
    r"DAO-governed",
    r"community-governed",
    r"eliminates trust",
]

# Lines that legitimately contain a forbidden word because they are DENYING it
# ("this is not decentralized"), quoting the forbidden list itself, or naming
# other protocols' properties.
NEGATION = re.compile(
    r"\b(not|never|no|neither|nor|without|isn't|is not|rather than|instead of|"
    r"forbidden|avoid|must not|cannot|would be false|does not)\b",
    re.I,
)


# A cited work's TITLE is not a claim about this system. ERC-8004 is literally
# named "Trustless Agents" and arXiv:2606.26028 is "Can Trustless Agents Be
# Trusted?"; refusing to cite them by name would be a worse outcome than the
# one this guard protects against.
#
# The exemption is deliberately narrow, because a broad one would be a hole:
# it applies only inside the reference list -- a line beginning "[n]", or a
# continuation line of such an entry -- and only where the forbidden word sits
# inside *italics*, which is how this document marks a title. Body prose can
# never reach it, so the guard is unchanged everywhere a claim could be made.
REFERENCE_ENTRY = re.compile(r"^\[\d+\]")


def _title_spans(line: str, open_before: bool):
    """Character ranges inside *italics*, tracking runs that wrap across lines.

    Reference titles are wrapped by the formatter, so an entry's italic run
    routinely spans several lines. Returns (spans, still_open_after).
    """
    spans = []
    pos = 0
    open_at = 0 if open_before else None
    while True:
        i = line.find("*", pos)
        if i == -1:
            break
        if open_at is None:
            open_at = i + 1
        else:
            spans.append((open_at, i))
            open_at = None
        pos = i + 1
    if open_at is not None:
        spans.append((open_at, len(line)))
    return spans, open_at is not None


def _in_cited_title(match: re.Match, spans) -> bool:
    return any(a <= match.start() < b for a, b in spans)


def _offending_lines(path: Path):
    if not path.exists():
        return []
    out = []
    in_references = False
    in_entry = False
    italic_open = False
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.match(r"^#{1,3} References\s*$", line):
            in_references = True
        elif re.match(r"^#{1,3} ", line):
            in_references = False

        if REFERENCE_ENTRY.match(line):
            in_entry = True
            italic_open = False
        elif not line.strip():
            in_entry = False
            italic_open = False

        exempt = in_references and in_entry
        spans, italic_open = _title_spans(line, italic_open) if exempt else ([], False)

        for pat in FORBIDDEN:
            m = re.search(pat, line, re.I)
            if not m or NEGATION.search(line):
                continue
            if exempt and _in_cited_title(m, spans):
                continue
            out.append((i, pat, line.strip()[:110]))
    return out


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_inflated_trust_vocabulary(doc):
    bad = _offending_lines(doc)
    assert not bad, (
        f"{doc.name} uses vocabulary reserved for properties this system does "
        f"not have (see docs/PHASE3B_TRUST_MODEL.md):\n"
        + "\n".join(f"  L{n}: [{pat}] {txt}" for n, pat, txt in bad)
    )


def test_bounded_trust_doc_exists_and_states_the_limit():
    doc = ROOT / "docs" / "PHASE3B_TRUST_MODEL.md"
    assert doc.exists(), "the trust-model contract doc must not be deleted"
    text = doc.read_text(encoding="utf-8").lower()
    for required in ("it is not decentralized", "it is not trustless",
                     "bounded trust", "n-of-m"):
        assert required in text, f"missing required statement: {required!r}"


# ---------------------------------------------------------------------------
# The exemption above is a hole by construction, so these tests bound it.
# Without them, "cited title" would be an unfalsifiable excuse that any future
# edit could hide a claim behind.
# ---------------------------------------------------------------------------


def _check(tmp_path, text):
    f = tmp_path / "doc.md"
    f.write_text(text, encoding="utf-8")
    return _offending_lines(f)


def test_exemption_allows_a_real_cited_title(tmp_path):
    doc = "## References\n\n[23] *ERC-8004: Trustless Agents*, EIPs.\n"
    assert _check(tmp_path, doc) == []


def test_exemption_allows_a_title_wrapped_across_lines(tmp_path):
    doc = (
        "## References\n\n"
        "[24] X. Xiong et al., *Can Trustless Agents Be Trusted? An Empirical\n"
        "Study of the ERC-8004 Ecosystem*, arXiv:2606.26028.\n"
    )
    assert _check(tmp_path, doc) == []


def test_exemption_does_not_cover_body_prose(tmp_path):
    """The case that matters: a claim in the body must still be caught."""
    doc = "## 3. The mechanism\n\nDispute resolution is trustless and permissionless.\n"
    bad = _check(tmp_path, doc)
    assert len(bad) == 2, bad


def test_exemption_does_not_cover_commentary_inside_a_reference(tmp_path):
    """A reference entry's own prose is not a title.

    This is the abuse path worth closing: appending a claim to a citation,
    outside the italics, where it would read as part of the reference.
    """
    doc = (
        "## References\n\n"
        "[23] *ERC-8004: Trustless Agents*, EIPs -- our dispute layer is\n"
        "trustless in the same sense.\n"
    )
    bad = _check(tmp_path, doc)
    assert len(bad) == 1, bad
    assert bad[0][0] == 4, "the commentary line, not the title line"


def test_exemption_does_not_apply_outside_the_reference_section(tmp_path):
    """Italics alone are not a licence -- the line must be in the reference list."""
    doc = "## 2. Related work\n\n[23] *Our trustless dispute layer*, ibid.\n"
    assert len(_check(tmp_path, doc)) == 1


def test_italic_state_resets_between_entries(tmp_path):
    """An unclosed italic must not leak its exemption into the next entry."""
    doc = (
        "## References\n\n"
        "[23] *An unclosed title\n"
        "\n"
        "[24] Smith, our system is trustless.\n"
    )
    bad = _check(tmp_path, doc)
    assert len(bad) == 1 and bad[0][0] == 5, bad
