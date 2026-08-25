# Brier UI — design record

Written before the code, so the choices are traceable rather than asserted
after the fact. Two critique passes are recorded at the end.

---

## 1. Grounding: what world does this belong to?

Brier is not a DeFi product and not an analytics SaaS. Its native vocabulary is
**calibration** — the discipline of checking a stated probability against what
actually happened. That world has an existing visual language, and it is not
the one crypto dashboards use:

- **The reliability diagram.** Predicted confidence on x, empirical frequency on
  y, and a diagonal `y = x` marking perfect calibration. Everything is read as a
  *deviation from that line*.
- **Measurement against a known scale.** Laboratory instruments — a gauge with
  tick marks, a calibration certificate, a burette read to the meniscus. The
  reference is always visible next to the reading.
- **Actuarial ledgers.** Columns of figures that must reconcile. Precision at
  small sizes. No decoration on a number.

The single most important idea in the subject: **a claim is meaningless without
the reference it is measured against.** That is literally what a proper scoring
rule does, and literally what the diagonal on a reliability diagram is for.

This becomes the organising principle of the interface, not just its chart
style: **every figure on screen appears next to the thing that qualifies it.**
A slash percentage appears next to the confidence that produced it. A gas cost
appears next to what it is a multiple of. A guarantee appears next to the tier
of trust it actually rests on. Nothing is shown as a bare number.

### The three defaults being avoided

| Default | Why it is wrong here |
|---|---|
| Cream + high-contrast serif + terracotta | Reads editorial/artisanal. This is instrumentation, not an essay. |
| Near-black + single neon accent | The crypto-dashboard house style. Would imply exactly the "sophisticated protocol" framing the trust docs spend their length denying. |
| Broadsheet, hairline rules, zero radius | Currently fashionable for technical work, and it flattens hierarchy — everything looks equally authoritative, which is the opposite of what a three-tier trust model needs. |

Checked against the third especially: the trust panel *requires* three visually
distinct confidence levels. A design where guaranteed and merely-assumed look
alike would be actively dishonest.

---

## 2. Token system

### Colour — derived from measurement, not from crypto UI

Ground is a **cool paper grey**, the colour of graph paper and lab notebooks,
not white and not black. Against it, three semantic colours carry the trust
tiers, and they are the *only* saturated colours in the interface — so hue is
never decorative here, it always means a trust level.

| Token | Hex | Role |
|---|---|---|
| `--ground` | `#EDEFF2` | Page. Cool grey — graph paper, not white. |
| `--surface` | `#F7F8FA` | Panels lifted off the ground. |
| `--ink` | `#161A1F` | Primary text. Near-black with a blue cast, not pure black. |
| `--reference` | `#5B6B7C` | The diagonal, axes, tick marks, muted text. Slate. |
| `--verified` | `#2E7D4F` | Tier 1: cryptographically guaranteed. |
| `--assumed` | `#9A7B2F` | Tier 2: economically assumed. |
| `--trusted` | `#C44536` | Tier 3: fully trusted, and every measured deviation. |

The three semantic colours are **carried over deliberately from Figure C**, the
threat-model diagram already committed in the repo. The UI and the paper's
diagram must not use different colours for the same tier — a reader moving
between them should not have to re-learn the code.

`--trusted` doubles as the deviation colour on reliability diagrams. That is
intentional: the gap between a claim and reality is the same idea in both
places.

### Type

| Role | Face | Why |
|---|---|---|
| Display | **Fraunces** (optical size, low softness) | A characterful serif with real variation, used *only* at section level. Gives the interface a scientific-publication register without tipping into the cream/serif default, because it sits on cool grey with sans body text. |
| Body | **Inter** | Neutral, high x-height, unopinionated next to a characterful display face. |
| Data | **Fira Code** | Tabular figures, unambiguous `0/O` and `1/l`. Every number in this interface is a measurement, and measurements get a face that aligns in columns. |

Fira Code is the skill's "Dashboard Data" recommendation, kept. Its Fira Sans
partner was dropped for Inter — Fira Sans is warm where this interface wants
neutral, and Inter's tabular numerals pair more cleanly with a serif display.

Rejected: the skill's top recommendation (Exo + Roboto Mono). Exo is a
techno/futuristic face; it would imply the "advanced protocol" framing the docs
explicitly deny.

### Layout concept

> A measurement column down the left carries the reference values the whole page
> is read against; content to its right is always positioned relative to that
> reference, the way a reading is taken against a scale.

```
┌────────────────────────────────────────────────────────────────┐
│  BRIER                          [ chain: anvil ● / not connected ]│
│  Confidence-calibrated slashing            what is / isn't proved │
├──────────────┬─────────────────────────────────────────────────┤
│              │                                                  │
│  REFERENCE   │   DECISION EXPLORER                              │
│  ─────────   │   ┌────────────────────────────────────────┐    │
│  ECE  0.1853 │   │ loan #043   margin +7.415              │    │
│    ↓ 0.0870  │   │ ├──────────────────────────────────────│    │
│              │   │ │ confidence  0.9845                   │    │
│  T    3.47   │   │ │ SHAP top-5  ▇▇▇▇▁ duration_months    │    │
│              │   │ │             ▇▇▇░░ checking_status    │    │
│  gas  684696 │   │ └──────────────────────────────────────│    │
│  =33× xfer   │   │ on-chain: 0x7d9c… ✓ verified           │    │
│              │   └────────────────────────────────────────┘    │
│  prove       │                                                  │
│  2.13s ±0.09 │   RELIABILITY  (the diagonal is the page's spine)│
│              │        1.0 ┆                              ╱      │
│  ─────────   │            ┆                        ╱  ● bin     │
│  TRUST       │            ┆                  ╱   ●               │
│  ▉ verified  │            ┆            ╱  ●                      │
│  ▉ assumed   │            ┆      ╱ ●                             │
│  ▉ trusted   │        0.0 ┆╱ ●                                   │
│              │            0.0 ─────────────────────────── 1.0    │
└──────────────┴─────────────────────────────────────────────────┘
```

### Signature element

**The diagonal as a structural device, not just a chart axis.**

The brief proposed the reliability diagram as a recurring motif. Taking it
literally — plotting every section against a diagonal — would be a gimmick that
fights the content: a gas table has no meaningful position relative to `y = x`.

What survives critique is the *idea underneath* it: **a reference line always
visible next to a reading.** So the diagonal appears where it is truthful:

1. Literally, in the reliability diagram, drawn from real bin values.
2. As a **deviation rule** elsewhere — each headline figure is drawn with a thin
   `--reference` baseline behind it and its deviation marked in `--trusted`.
   The uncalibrated-vs-calibrated ECE, the slash-vs-stake proportion, and the
   confident-wrong vs uncertain-wrong comparison all use this same mark.

One visual grammar, applied where it carries meaning, absent where it would not.

---

## 3. Critique pass 1 — before writing code

**"Would this look identical for a generic AI-insurance brief with no context?"**

Three parts failed that test and were changed:

| Failed | Change |
|---|---|
| First palette draft was slate-blue primary + green/amber/red status — indistinguishable from any admin dashboard, and status colours meant nothing beyond good/warn/bad. | Semantic colours now come from Figure C's trust tiers and are the **only** saturated hues. Hue always encodes trust level, never decoration or generic status. |
| Layout was a standard 3-column stat-card grid: four cards, big number, small label. Generic, and worse, it presents every number as equally authoritative — a measured gas cost sits identically next to an unmeasured one. | Replaced with the persistent reference column. Numbers appear against what qualifies them, and unmeasured values are *structurally* distinguishable rather than just annotated. |
| Signature was "the diagonal, everywhere" — as briefed. | Kept the principle (reference beside reading), dropped the literal application where it would be decorative. Stated above. |

**Does it match the subject's own honesty standard?** One more change: the trust
panel was going to be a section near the bottom. It now shares the top-level
navigation with results and has equal visual weight, because the standing rule
is that limitations are not undersold relative to results. A reviewer must not
be able to see the results without seeing what backs them.

---

## 4. Critique pass 2 — after building

Run against screenshots of all four tabs at 1440px, at 390px, and with the chain
deliberately killed.

### Does any part imply a claim the docs do not back?

The question that mattered most: **does the dispute panel look more
decentralised than a 2-of-3 admin-appointed committee actually is?**

It does not, and the reason is structural rather than editorial. The trust panel
reads `threshold`, `committeeSize`, and `unbondingPeriod` *from the deployed
contract* and renders what it finds. It cannot flatter the deployment, because
it is not describing the repository — it is describing the chain. Where the
committee exists it prints `2-of-3` immediately followed by "This is bounded
trust, not decentralisation", names that the admin can replace the committee,
and states that 2 colluding members have exactly the power a single admin key
had. Tier 3 keeps the red treatment either way: a smaller red region, not a
different colour.

A grep over the components for `trustless`, `decentralised`, `permissionless`,
and similar returns only the explicit denial. Nothing else uses that vocabulary.

### Three defects found and fixed

| Found | Fix |
|---|---|
| **Mobile was broken.** The decision explorer's inner grid was `1fr auto` as an inline style, so at 390px the reliability diagram overlapped the attribution table and feature labels wrapped to one word per line. | Moved to a `.explorer-grid` class that collapses to a single column below 1080px. Verified by re-screenshotting at 390px. |
| Touch targets on the decision `<select>` and the tab buttons were under 44px on small screens. | `min-height: 44px` below 560px. |
| The offline path was written but unverified — the risk being that it silently retained the last-known chain values, which would be exactly the fabricated-placeholder failure the brief forbids. | Killed the node and re-screenshotted. Deployed-status fields degrade to a hatched `cannot read: no chain connected`, and the notice states what failed plus the two commands that fix it. No stale value survives. |

### What the honesty rules produced visually

The `.unmeasured` treatment — hatched background, dashed border, monospace —
appears in three places: SP1 proving time, circuit behaviour above logrows 15,
and every deployed-status field when the chain is unreachable. It is
deliberately *ugly* relative to a real measurement. A reviewer skimming cannot
mistake one for the other, which is the point; an annotation alone would not
survive a skim.

### Left alone deliberately

The reference column repeats on every tab rather than appearing once. That is
redundant in a conventional layout review, but it is the design's organising
idea — a reading is always shown against its reference — and dropping it on
three of four tabs would undo it.
