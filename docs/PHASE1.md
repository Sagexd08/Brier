# Phase 1 — base classifier and calibration head

## Dataset

UCI Statlog German Credit (1,000 real credit applications, 20 attributes),
downloaded at build time. Label: raw 1 = good credit, 2 = bad credit. We model
the **reject** class, so `y = 1` means "bad credit → reject".

### Protected attribute

Attribute 9 (`personal_status_sex`) combines marital status and sex. It is
**dropped by default** (`config.PROTECTED_COLUMNS`). Training a credit model on
sex is indefensible in a demo aimed at regulators, and leaving it in would have
contaminated the Phase 2 SHAP narrative too.

Dropping it does **not** make the model fair — proxy discrimination through
correlated features is untested here. See `docs/PATH_TO_PRODUCTION.md` §7.

### Encoding

Ordinal attributes are mapped to ordered integers using the codebook in
`german.doc`, rather than one-hot encoded. Two reasons: it keeps the feature
space at 19 columns, and it keeps SHAP attributions interpretable in Phase 2
("worse checking status" must move monotonically in one direction, which a
one-hot encoding would scatter across several columns).

## Splits

60 / 20 / 20 train / calibration / test, stratified on the label, seed 42.
All three are mutually disjoint, asserted in `split_three_way` and re-verified
in `tests/test_phase1.py::test_splits_are_mutually_disjoint`.

**Why the calibration split must be held out.** The base model is trained to
100% training accuracy. Its training-set margins are therefore nearly
separable, and a temperature fitted on them learns to *sharpen* rather than
soften. Measured: fitting on train gives T = 0.1382 and a test ECE of 0.2579,
**worse than not calibrating at all** (0.2241). Fitting on the held-out
calibration split gives T = 3.0736 and a test ECE of 0.1007.

This is the single most consequential correctness detail in the phase, so it
is measured as a control run in every execution of
`scripts/10_train_calibrate.py` rather than left as a comment.

## Base model: a deliberately overfit regime

`train_base_classifier` uses depth-8 trees, learning rate 0.3, no L2/L1, and
`min_child_weight=1`. This is *not* a tuned model and is not meant to be.

The project's thesis is that deployed models are overconfident and that
miscalibration is worth insuring against. Demonstrating that on a model which
is already well calibrated would prove nothing. XGBoost with sane
regularisation on this dataset is only mildly miscalibrated; the overfit regime
reproduces the realistic failure (train accuracy 1.0000, test 0.7150) that
makes calibration matter.

Stated plainly: **the base model's 71.5% test accuracy is not a selling point,
and the overfit regime was chosen to make the calibration effect visible.**
Both facts are in `RESULTS.md`.

## Calibration heads

| Head | Params | Role |
|---|---|---|
| `TemperatureScaler` | 1 | `sigmoid(margin / T)`. Primary. |
| `MLPCalibrationHead` | 321 | 1→16→16→1 with ReLU. Circuit-feasibility candidate. |

Both output a **logit**; the sigmoid is applied outside the module. This is
deliberate for Phase 3: an affine+ReLU circuit is far cheaper to prove than one
containing a sigmoid, so the nonlinearity stays out of the circuit.

The MLP normalises its input inside the module (`fit_input_scale`, fitted on
calibration margins only). This is not cosmetic — see below.

### A real bug found and fixed in this phase

The first working version of the MLP fit **diverged to a `nan` loss while still
returning finite-looking probabilities**, and the pipeline happily computed an
ECE from it. The reported "MLP underperforms due to overfitting" conclusion was
wrong: the in-sample ECE (0.1604) was *worse* than the held-out ECE (0.1491),
which is the opposite of overfitting and was the clue that the fit was broken.

Root cause: LBFGS with `max_iter=2000` and no line search walked past
convergence into numerical breakdown on margins spanning [-10.9, +9.1].

Fix: strong-Wolfe line search, bounded iterations, best-finite-iterate
retention, and a hard `RuntimeError` on a non-finite final loss. A silent
`nan` can no longer produce a published number.

### Result: the 1-parameter head wins

After the fix, temperature scaling (ECE 0.1007) still beats the MLP (0.1466)
on the test split, despite the MLP reaching a lower calibration-set NLL. With
200 calibration points, the extra capacity does not generalise.

Convenient for Phase 3 — the cheapest circuit is also the best head — but it is
a result, not an assumption, and the MLP is still exported and proved so the
comparison is measured rather than asserted.
