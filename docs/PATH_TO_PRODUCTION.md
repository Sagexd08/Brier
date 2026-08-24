# Path to production

What would have to change before an insurer or regulator could take this
seriously. Written as a gap list, not a roadmap promise.

## 1. The dispute layer is the weakest link

The MVP resolves disputes with `onlyAdmin`. A single key decides whether a
decision was correct, and therefore decides who loses money. That is not an
insurance mechanism; it is an escrow with a trusted operator.

Production needs: an evidentiary standard for what "the decision was wrong"
means for a loan rejection (the counterfactual is unobservable — a rejected
applicant never demonstrates repayment); an adjudication process with
independent adjudicators and economic security exceeding the value at risk;
an appeals path; and a defined statute of limitations, since credit outcomes
resolve over months to years, not blocks.

The unobservable-counterfactual problem is genuinely hard and is not solved
here. Realistic resolution sources are regulator findings, successful
applicant appeals, or lender-side outcome data on overturned decisions.

## 2. Only the calibration head is proved

An operator can submit an honest proof over a fabricated logit. The proof binds
the calibration step, not the pipeline. Production needs the base classifier
committed and proved (expensive today for tree ensembles), or a trusted
execution / attested-inference path for the base model, or the proof reframed
as covering a strictly narrower claim than users will assume.

Any product copy claiming "the AI decision is zero-knowledge proved" would be
false against this architecture.

## 3. Calibration drift

The head is calibrated once on a static split. Real populations shift, and a
model calibrated in January is miscalibrated by June. Production needs periodic
recalibration with on-chain versioning, plus a rule for which model version a
decision is judged against — an operator must not be slashed under a
calibration they had not yet deployed.

## 4. Economic parameters are invented

Stake sizes, slash caps, and payout amounts here are demonstration values. Real
parameters require actuarial work: expected dispute frequency, correlation
across decisions (one bad model version produces thousands of correlated
claims, unlike independent risks), reinsurance, and capital adequacy.

Correlated tail risk is a serious concern — an insurance pool covering a single
model can be wiped out by a single systematic failure.

## 5. Gaming the scoring rule

The Brier rule makes honest reporting optimal *given* that disputes are
resolved fairly and every decision is equally likely to be disputed. If only
rejections are ever disputed, an operator can exploit the asymmetry. Production
needs analysis of the operator's true objective under selective disputes,
including whether the mechanism discourages issuing decisions at all in
uncertain regions.

## 6. Regulatory and legal wrapper

Whether this is insurance is a legal question with a jurisdiction-specific
answer, and if it is, it is a regulated activity. Adjacent obligations include
ECOA/Reg B and FCRA adverse-action notice requirements in the US and GDPR
Art. 22 in the EU. On-chain publication of decision artefacts must not leak
personal data — the current design hashes SHAP vectors, which is a start, but
hashes of low-entropy inputs are not anonymisation.

## 7. Fairness

The protected attribute is dropped, which does not prevent proxy discrimination.
A production system needs disparate-impact testing, and calibration measured
*within* protected groups — a model can be well calibrated overall and badly
miscalibrated for a subgroup, which is exactly the harm this mechanism should
be catching and currently does not.
