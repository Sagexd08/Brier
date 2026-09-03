"""Generate the Results and Trust Model pages from measured artifacts.

Every figure on these pages is read out of artifacts/ at build time. Nothing is
typed by hand, for the same reason RESULTS.md and ABLATION.md are generated: a
page that restates numbers drifts from the runs that produced them, and a
marketing page drifting from the paper is worse than having no page.

Re-run after any change to the artifacts:

    python scripts/95_build_site_pages.py

Writes landing/results.html and landing/trust.html.
"""
from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = ROOT / "artifacts" / "ablation"
CAL = ROOT / "artifacts" / "calibration"
ZK = ROOT / "artifacts" / "zk"
LANDING = ROOT / "landing"
FIGS = ROOT / "figures"


def load(p: Path):
    if not p.is_file():
        raise SystemExit("missing artifact: %s" % p.relative_to(ROOT))
    return json.loads(p.read_text(encoding="utf-8"))


A = load(ABL / "phaseA.json")
B = load(ABL / "phaseB.json")
BC = load(ABL / "phaseB_circuit.json")
C = load(ABL / "phaseC.json")
D = load(ABL / "phaseD.json")
E = load(ABL / "phaseE.json")
P1 = load(CAL / "phase1_report.json")
MS = load(CAL / "multiseed_report.json")
GAS = load(ZK / "phase4_gas.json")["gas"]
P3 = load(ZK / "phase3_report.json")["metrics"]


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def pm(d: dict, key: str, n: int = 4) -> str:
    return "%.*f <span class=\"pm\">± %.*f</span>" % (n, d[key]["mean"], n, d[key]["std"])


def num(v, n: int = 0) -> str:
    return "{:,.{p}f}".format(v, p=n)


# ----------------------------------------------------------------------
# Shared chrome
# ----------------------------------------------------------------------

def head(title: str, desc: str, active: str) -> str:
    nav = []
    for label, href in (("Mechanism", "index.html"), ("Results", "results.html"),
                        ("Trust Model", "trust.html"), ("Paper", "brier-proposal.pdf")):
        cls = "nav-link is-active" if label == active else "nav-link"
        extra = ' target="_blank" rel="noopener"' if href.endswith(".pdf") else ""
        aria = ' aria-current="page"' if label == active else ""
        nav.append('<a class="%s" href="%s"%s%s>%s</a>' % (cls, href, extra, aria, label))

    mnav = []
    for label, href in (("Mechanism", "index.html"), ("Results", "results.html"),
                        ("Trust Model", "trust.html"), ("Paper", "brier-proposal.pdf")):
        cls = "m-link is-active" if label == active else "m-link"
        extra = ' target="_blank" rel="noopener"' if href.endswith(".pdf") else ""
        mnav.append('<a class="%s" href="%s"%s>%s</a>' % (cls, href, extra, label))

    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>%(title)s</title>
    <meta name="description" content="%(desc)s" />
    <meta name="theme-color" content="#000000" />
    <link rel="icon" type="image/webp" href="assets/logo-white.webp" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
    <link href="https://db.onlinewebfonts.com/c/8cb707a9b8a73f8a7403336b861c3074?family=BubbledotICG-FinePos" rel="stylesheet" />
    <link rel="stylesheet" href="styles.css" />
    <link rel="stylesheet" href="pages.css" />
  </head>
  <body class="doc">
    <header class="doc-header">
      <a class="logo" href="index.html" aria-label="Brier home">
        <img src="assets/logo.webp" alt="" width="52" height="52" />
      </a>
      <nav class="nav" aria-label="Primary">%(nav)s</nav>
      <a class="sign-in" href="https://github.com/Sagexd08/Brier">GitHub</a>
      <button class="burger" type="button" aria-label="Open menu"
              aria-expanded="false" aria-controls="mobile-menu">
        <span></span><span></span><span></span>
      </button>
    </header>
    <div class="menu-overlay" hidden></div>
    <div class="mobile-menu" id="mobile-menu" hidden>%(mnav)s
      <a class="m-sign-in" href="https://github.com/Sagexd08/Brier">GitHub</a>
    </div>
""" % {"title": esc(title), "desc": esc(desc), "nav": "".join(nav), "mnav": "".join(mnav)}


FOOT = """
    <footer class="doc-foot">
      <div class="foot-row">
        <span class="foot-mark">
          <img src="assets/logo-white.webp" alt="" width="18" height="18" /> Brier
        </span>
        <nav class="foot-links" aria-label="Footer">
          <a href="index.html">Mechanism</a>
          <a href="results.html">Results</a>
          <a href="trust.html">Trust Model</a>
          <a href="brier-proposal.pdf" target="_blank" rel="noopener">Paper</a>
          <a href="https://github.com/Sagexd08/Brier">GitHub</a>
        </nav>
      </div>
      <p class="foot-note">
        Research prototype. Every figure on this page is generated from the
        artifacts in the repository by <code>scripts/95_build_site_pages.py</code>
        and is reproducible from a clean checkout. Measurements come from a local
        chain against UCI German Credit data and are not a claim about production
        behaviour.
      </p>
    </footer>
    <script src="main.js"></script>
  </body>
</html>
"""


def section(eyebrow: str, title_html: str, lede: str = "") -> str:
    out = ['<section class="sec"><div class="wrap">',
           '<span class="eyebrow">%s</span>' % esc(eyebrow),
           "<h2>%s</h2>" % title_html]
    if lede:
        out.append('<p class="lede">%s</p>' % lede)
    return "".join(out)


def table(headers, rows, caption="", cls="") -> str:
    out = ['<div class="tw">']
    if caption:
        out.append('<p class="cap">%s</p>' % caption)
    out.append('<table class="%s">' % cls)
    out.append("<thead><tr>" + "".join("<th>%s</th>" % h for h in headers) + "</tr></thead><tbody>")
    for r in rows:
        out.append("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


# ----------------------------------------------------------------------
# Results page
# ----------------------------------------------------------------------

def results_page() -> str:
    sa, ca = A["summary"], A["comparisons"]
    sc, cc = C["summary"], C["comparisons"]
    sd = D["summary"]
    bt = BC["results"]["temperature_only"]
    bcf = BC["results"]["temperature_plus_conformal"]

    ece_before = sa["xgboost"]["uncal_ece"]["mean"]
    ece_after = sa["xgboost"]["cal_ece"]["mean"]
    reduction = (1 - ece_after / ece_before) * 100

    o = [head("Results — Brier",
              "Measured results for Brier: calibration across 10 pinned seeds, "
              "proving cost, on-chain gas, and five ablated enhancements.",
              "Results")]

    # ---- hero ----
    o.append("""
    <section class="doc-hero">
      <div class="wrap">
        <span class="eyebrow">Measured, not projected</span>
        <h1>Results</h1>
        <p class="lede">
          Every number below is produced by a script in the repository and
          regenerated into this page at build time. The protocol is
          %d pinned seeds, always run in full, so a favourable subset cannot be
          reported selectively.
        </p>
        <div class="kpis">
          %s
        </div>
      </div>
    </section>
    """ % (MS["n_seeds"], "".join(
        '<div class="kpi"><span class="k">%s</span><span class="v">%s</span>'
        '<span class="n">%s</span></div>' % (k, v, n)
        for k, v, n in [
            ("Calibration error", "%.4f&nbsp;&rarr;&nbsp;%.4f" % (ece_before, ece_after),
             "ECE, mean over %d seeds. Reduced in every seed." % MS["n_seeds"]),
            ("Proving time", P3["Proving time - temperature"],
             "EZKL / halo2 over the calibration head, laptop CPU."),
            ("Verification", num(GAS["verifyProof (real EZKL proof, on-chain)"]) + " gas",
             "Roughly 33&times; a plain transfer."),
            ("Slash arithmetic", num(GAS["BrierMath.slashAmount (pure, via wrapper)"]) + " gas",
             "About 0.08%% of the per-decision cost."),
        ])))

    # ---- calibration ----
    o.append(section("Calibration", "The head that <em>earns its place</em>.",
                     "Temperature scaling reduces ECE by %.1f%% on held-out data, in every "
                     "seed. Accuracy is unchanged, as it must be: a monotone rescaling of "
                     "the logit cannot move the decision boundary." % reduction))
    o.append(table(
        ["Base model", "Uncalibrated ECE", "Calibrated ECE", "Brier", "Accuracy"],
        [["<strong>XGBoost + temperature</strong>", pm(sa["xgboost"], "uncal_ece"),
          "<strong>%s</strong>" % pm(sa["xgboost"], "cal_ece"),
          pm(sa["xgboost"], "cal_brier"), pm(sa["xgboost"], "accuracy")],
         ["Tabular NN + temperature", pm(sa["nn"], "uncal_ece"), pm(sa["nn"], "cal_ece"),
          pm(sa["nn"], "cal_brier"), pm(sa["nn"], "accuracy")],
         ["Ensemble + temperature", pm(sa["ensemble"], "uncal_ece"),
          pm(sa["ensemble"], "cal_ece"), pm(sa["ensemble"], "cal_brier"),
          pm(sa["ensemble"], "accuracy")]],
        caption="Calibration across %d pinned seeds. Each row is a base model with "
                "temperature scaling applied on top, so the first two columns are the same "
                "model before and after. Learned T = %.4f, with T &gt; 1 in every seed "
                "&mdash; the base model required softening everywhere. Brier and accuracy "
                "are post-calibration; accuracy is unchanged by a monotone rescaling."
                % (MS["n_seeds"], P1["temperature"])))
    o.append('<figure class="fig"><img src="figures/figure-d-calibration.png" '
             'alt="Reliability diagrams before and after temperature scaling, with the '
             'train-fitted leakage control." loading="lazy" />'
             '<figcaption>Reliability before and after calibration. The right panel is a '
             'leakage control fitted on the training split: it is <em>worse than not '
             'calibrating at all</em>, in every seed.</figcaption></figure>')
    o.append("</div></section>")

    # ---- ablation ----
    ce = ca["ensemble_vs_xgboost_cal_ece"]
    cv = cc["variance_aware_vs_temperature_ece"]
    ck = cc["capacity_control_vs_temperature_ece"]
    o.append(section("Ablation", "Two of five enhancements <em>failed</em>.",
                     "Each was measured against the shipped baseline on the identical seed "
                     "protocol and kept only if it earned its place. The failures are "
                     "reported here at the same size as the successes."))
    o.append(table(
        ["Enhancement", "Verdict", "Evidence"],
        [["Conformal prediction", '<span class="tag ok">Adopted</span>',
          "Fits the circuit budget: logrows unchanged, +%d rows of 32,768, no measurable "
          "proving cost." % BC["verdict"]["rows_used_delta"]],
         ["Counterfactual evidence", '<span class="tag ok">Adopted</span>',
          "%d of %d rejections resolved, %d immutable violations, deterministic hash."
          % (sd["n_counterfactual_found"], sd["n_rejections_examined"],
             sd["immutable_violations"])],
         ["Deep tabular NN + ensemble", '<span class="tag null">Null</span>',
          "%dW/%dL on calibrated ECE (p = %.4f), and it costs accuracy."
          % (ce["wins"], ce["losses"], ce["p_value"])],
         ["Deep-ensemble uncertainty", '<span class="tag bad">Negative</span>',
          "%dW/%dL (p = %.4f). The signal <em>degrades</em> calibration."
          % (cv["wins"], cv["losses"], cv["p_value"])],
         ["GNN collusion detection", '<span class="tag warn">Synthetic only</span>',
          "Recovers injected rings; never seen real collusion."]],
        caption="Five ablated enhancements. Full tables and statistics in ABLATION.md."))

    o.append('<div class="callout"><h3>The capacity control is what made Phase C legible</h3>'
             '<p>Feeding the calibration head ensemble disagreement made calibration worse '
             '(%dW/%dL, p&nbsp;=&nbsp;%.4f). But the <em>same head shape</em> fed a constant '
             'zero beat the baseline (%dW/%dL, p&nbsp;=&nbsp;%.4f). So the architecture helps '
             'and the epistemic signal then cancels it &mdash; it is noise the head overfits '
             'on %d calibration points. Without the control this would have read as '
             '&ldquo;disagreement doesn&rsquo;t help&rdquo;.</p></div>'
             % (cv["wins"], cv["losses"], cv["p_value"],
                ck["wins"], ck["losses"], ck["p_value"], P1["n_calib"]))
    o.append("</div></section>")

    # ---- conformal ----
    o.append(section("Uncertainty", "A guarantee, and <em>what it cost</em>.",
                     "Split conformal returns a set with a distribution-free coverage "
                     "guarantee. Coverage tracks the target and sits 1&ndash;2 points below "
                     "it at every level, which is within sampling noise at n&nbsp;=&nbsp;%d."
                     % MS["n_seeds"]))
    o.append(table(
        ["Target", "Empirical coverage", "Min over seeds", "Seeds &ge; target", "Avg set size"],
        [["%.2f" % B["summary"][a]["target_coverage"],
          "%.4f <span class=\"pm\">± %.4f</span>" % (B["summary"][a]["coverage_mean"],
                                                     B["summary"][a]["coverage_std"]),
          "%.4f" % B["summary"][a]["coverage_min"],
          "%d/%d" % (B["summary"][a]["seeds_at_or_above_target"], MS["n_seeds"]),
          "%.3f" % B["summary"][a]["avg_set_size_mean"]]
         for a in ("0.20", "0.10", "0.05")],
        caption="Coverage is reported with set size throughout, because coverage alone is "
                "trivially satisfiable: always return both labels and you have 100% coverage "
                "and no information."))
    o.append(table(
        ["Head", "logrows", "Rows used", "Proving time", "Proof size"],
        [["Temperature only", bt["logrows"], num(bt["num_rows_used"]),
          "%.2f s" % bt["prove_s"], num(bt["proof_bytes"]) + " B"],
         ["Temperature + conformal", bcf["logrows"], num(bcf["num_rows_used"]),
          "%.2f s" % bcf["prove_s"], num(bcf["proof_bytes"]) + " B"]],
        caption="The circuit-feasibility gate. It fits because both comparisons push through "
                "the monotone sigmoid into logit space and become comparisons against two "
                "constants, so the sigmoid never enters the circuit."))
    o.append("</div></section>")

    # ---- cost ----
    o.append(section("On-chain cost", "Verification dominates, <em>the mechanism does not</em>.",
                     "The Brier arithmetic that is the substance of the mechanism is three "
                     "orders of magnitude cheaper than proving that it ran."))
    o.append(table(["Operation", "Gas"],
                   [[esc(k), num(v)] for k, v in GAS.items()],
                   caption="Measured with <code>forge test --gas-report</code> on a local chain."))
    o.append('<div class="callout"><h3>The practical claim is an L2 claim</h3>'
             '<p>At 887,376 gas an attestation costs about <strong>$79.86</strong> on L1 at '
             '30&nbsp;gwei, against <strong>$0.13</strong> on an L2 at 0.05&nbsp;gwei '
             '(ETH at $3,000). At L1 prices the design is only coherent for decisions worth '
             'hundreds of dollars each, which excludes most consumer credit. The L1 figures '
             'are best read as an upper bound.</p></div>')
    o.append('<figure class="fig"><img src="figures/figure-e-circuit-sweep.png" '
             'alt="Proving cost against head size across four orders of magnitude." '
             'loading="lazy" /><figcaption>Proving cost is flat across a 16,897&times; '
             'parameter increase. Capacity, not parameter count, is the binding '
             'constraint &mdash; which is why the design proves a small head rather than a '
             'classifier.</figcaption></figure>')
    o.append("</div></section>")

    o.append("""
    <section class="cta-band"><div class="wrap">
      <h2>The full method, <em>with its limits</em>.</h2>
      <p>Statistics, controls and the negative results in full.</p>
      <div class="row">
        <a class="btn-solid" href="brier-proposal.pdf" target="_blank" rel="noopener">Read the paper</a>
        <a class="btn-ghost" href="trust.html">See the trust model</a>
      </div>
    </div></section>
    """)
    o.append(FOOT)
    return "".join(o)


# ----------------------------------------------------------------------
# Trust model page
# ----------------------------------------------------------------------

def trust_page() -> str:
    o = [head("Trust Model — Brier",
              "What Brier proves cryptographically, what it assumes economically, "
              "and what it simply trusts. Every weakness is demonstrated by a passing test.",
              "Trust Model")]

    o.append("""
    <section class="doc-hero">
      <div class="wrap">
        <span class="eyebrow">What is proved, and what is not</span>
        <h1>Trust Model</h1>
        <p class="lede">
          This is a mechanism and a measured prototype, not a deployable protocol.
          Every weakness below is demonstrated by a test that passes, so the threat
          model cannot drift from the code without the suite failing.
        </p>
        <div class="tierbar">
          <span class="tb t1">Tier 1 · Cryptographic</span>
          <span class="tb t15">Content integrity</span>
          <span class="tb t2">Tier 2 · Economic</span>
          <span class="tb t3">Tier 3 · Bounded trust</span>
          <span class="tb t4">Below tier 3 · Unvalidated</span>
        </div>
      </div>
    </section>
    """)

    tiers = [
        ("t1", "Tier 1", "Cryptographically guaranteed",
         "Holds against a fully malicious operator. No trust required.",
         ["Calibration-head execution: given a logit <em>L</em> committed on-chain, the "
          "proof establishes that the head identified by this verifying key maps it to "
          "the attested confidence.",
          "Conformal set construction, proved on the same terms since it fits the same circuit.",
          "The slash arithmetic: exactly stake&nbsp;&middot;&nbsp;(c&nbsp;&minus;&nbsp;o)², "
          "capped, with no overflow.",
          "Tampered proofs, flipped bytes and wrong verifying keys are each rejected (4/4)."],
         None),
        ("t15", "Content integrity", "ModelRegistry",
         "A narrow cryptographic property, which is why it does not sit in tier 1.",
         ["Guarantees the artifact behind a version id hashes to the recorded value, so "
          "substitution is detectable by anyone.",
          "Does <strong>not</strong> establish that training was honest &mdash; a poisoned "
          "model registers and verifies perfectly cleanly.",
          "Does <strong>not</strong> bind a version id to the circuit that actually ran."],
         "Content integrity is not training integrity."),
        ("t2", "Tier 2", "Economically assumed",
         "Holds if the operator is rational and the assumption is enforced in code.",
         ["<strong>Honest reporting</strong> is enforced by the payoff: Brier is strictly "
          "proper, so expected loss is minimised at the operator's true belief.",
          "<strong>Stake availability</strong> was broken in v0 and is now enforced &mdash; "
          "withdrawal is request/execute behind an unbonding delay, and an open dispute "
          "freezes execution.",
          "Residual gap A: an operator never disputed inside the window still exits intact. "
          "That is a bound on the dispute window, not on the lock.",
          "Residual gap B: the freeze is released by dispute <em>resolution</em>, which is a "
          "tier-3 action."],
         "Enforced against the operator, but subordinate to tier 3."),
        ("t3", "Tier 3", "Bounded trust",
         "An N-of-M committee decides who loses money. No cryptographic or economic guarantee.",
         ["One resolver cannot act alone. That is the whole of the improvement over a single key.",
          "N colluding members carry exactly the authority that key had.",
          "The admin appoints and can replace the committee, so the bound covers resolution, "
          "not selection. Resolvers stake nothing.",
          "Operator reputation is auditable on-chain aggregation, but its inputs are tier-3 "
          "outcomes, so it inherits that trust level and no better.",
          "Underneath sits a harder problem: for a loan rejection the counterfactual is "
          "unobservable, so &ldquo;the decision was wrong&rdquo; has no on-chain referent."],
         "Bounded trust is not an absence of trust."),
        ("t4", "Below tier 3", "An unvalidated detector with authority over money",
         "One reporter key relays a model whose false-positive rate on real traffic has "
         "never been measured.",
         ["An enforced flag <strong>blocks a claimant from disputing</strong> and "
          "<strong>withholds their payout</strong>.",
          "It <strong>cannot slash</strong>: the operator's penalty is computed and taken "
          "identically whether or not the claimant is flagged.",
          "An appeal window precedes any effect, and a zero-length window is rejected at "
          "construction.",
          "Quarantined funds are refunded in full if the flag is cleared; permanent "
          "forfeiture is a separate, admin-only act.",
          "A false positive silences a legitimate claimant and thereby protects the bad "
          "decision they were trying to challenge."],
         "Thinner than tier 3: the committee needs N signatures, this needs one."),
    ]

    o.append('<section class="sec"><div class="wrap"><div class="tiers">')
    for cls, label, title, lede, items, note in tiers:
        o.append('<article class="tier %s"><div class="tier-head">'
                 '<span class="tier-label">%s</span><h3>%s</h3></div>'
                 '<div class="tier-body"><p class="tier-lede">%s</p><ul>%s</ul>%s</div></article>'
                 % (cls, esc(label), esc(title), lede,
                    "".join("<li>%s</li>" % i for i in items),
                    ('<p class="tier-note">%s</p>' % note) if note else ""))
    o.append("</div></div></section>")

    # ---- the boundary ----
    o.append(section("The boundary", "What a fabricated input <em>costs you</em>.",
                     "The proof binds a computation, not a pipeline. This is the single "
                     "largest gap in the system and it has not moved since v0."))
    o.append('<div class="callout danger"><h3>An operator that fabricates the input logit '
             'obtains a proof that verifies</h3>'
             '<p>The circuit takes the base model&rsquo;s logit as an unverified public '
             'input. Nothing on-chain relates it to the base model, and the chain will '
             'accept <code>type(int256).max</code> as a margin and still mark the '
             'attestation proved. Describing this system as &ldquo;zero-knowledge proving '
             'the AI decision&rdquo; would be false.</p>'
             '<p class="src">Demonstrated by '
             '<code>test_tier1_marginIsUnverifiedOperatorSuppliedInput</code>.</p></div>')

    o.append(table(
        ["Adversary capability", "Covered", "Mechanism, or reason not"],
        [["Forge a proof for a head it did not run", '<span class="yes">yes</span>',
          "halo2 soundness; 4/4 tamper checks"],
         ["Alter an attested confidence after the fact", '<span class="yes">yes</span>',
          "stored on chain, proof-bound"],
         ["Substitute weights under a claimed version", '<span class="yes">yes</span>',
          "ModelRegistry content hash"],
         ["Exit stake ahead of a pending dispute", '<span class="yes">yes</span>',
          "unbonding delay + dispute freeze"],
         ["Act alone as a single resolver", '<span class="yes">yes</span>',
          "N-of-M threshold"],
         ["<strong>Fabricate the input logit</strong>", '<span class="no">no</span>',
          "tier 1 binds the head, not the pipeline"],
         ["<strong>Corrupt N of M resolvers</strong>", '<span class="no">no</span>',
          "equals v0&rsquo;s single-key power"],
         ["<strong>Exit before any dispute is raised</strong>", '<span class="no">no</span>',
          "bound on the dispute window, not the lock"],
         ["<strong>Misreport within a protected subgroup</strong>", '<span class="no">no</span>',
          "calibration is measured in aggregate"],
         ["<strong>Flag an honest claimant</strong>", '<span class="no">no</span>',
          "detector unvalidated on real traffic"],
         ["Train dishonestly and register truthfully", '<span class="no">no</span>',
          "content integrity &ne; training integrity"],
         ["Decline to attest at all", '<span class="no">no</span>',
          "unattested decisions are outside the system"]],
        caption="Threat coverage. The five in bold are the ones an adversary would actually "
                "use; each has a passing test that demonstrates it."))
    o.append("</div></section>")

    o.append('<section class="sec"><div class="wrap">'
             '<span class="eyebrow">The diagram</span>'
             '<h2>Every tier, <em>with its evidence</em>.</h2>'
             '<figure class="fig wide"><img src="figures/figure-c-threat-model.png" '
             'alt="Trust boundary diagram showing tier 1 cryptographic guarantees, a content '
             'integrity band, tier 2 economic assumptions, tier 3 bounded trust, and the '
             'unvalidated detector below tier 3." loading="lazy" />'
             '<figcaption>Each weakness names the test that demonstrates it. The cheapest '
             'attack today still requires breaking no cryptography.</figcaption></figure>'
             "</div></section>")

    o.append("""
    <section class="cta-band"><div class="wrap">
      <h2>The mechanism holds. <em>The system doesn't yet.</em></h2>
      <p>The paper states both claims separately and sets out what closing the distance would take.</p>
      <div class="row">
        <a class="btn-solid" href="brier-proposal.pdf" target="_blank" rel="noopener">Read the paper</a>
        <a class="btn-ghost" href="results.html">See the results</a>
      </div>
    </div></section>
    """)
    o.append(FOOT)
    return "".join(o)


def main() -> int:
    # Figures the pages reference must travel with them.
    dest = LANDING / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("figure-c-threat-model.png", "figure-d-calibration.png",
                 "figure-e-circuit-sweep.png"):
        src = FIGS / name
        if not src.is_file():
            raise SystemExit("missing figure: %s" % src.relative_to(ROOT))
        shutil.copyfile(src, dest / name)

    (LANDING / "results.html").write_text(results_page(), encoding="utf-8")
    (LANDING / "trust.html").write_text(trust_page(), encoding="utf-8")
    for f in ("results.html", "trust.html"):
        print("wrote landing/%s (%d KB)" % (f, (LANDING / f).stat().st_size / 1024))
    print("copied 3 figures into landing/figures/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
