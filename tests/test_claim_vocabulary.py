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
    ROOT / "PROPOSAL.md",
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


def _offending_lines(path: Path):
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for pat in FORBIDDEN:
            if re.search(pat, line, re.I) and not NEGATION.search(line):
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
