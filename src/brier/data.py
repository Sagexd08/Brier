"""UCI Statlog German Credit loader.

Source: https://archive.ics.uci.edu/dataset/144/statlog+german+credit+data
1,000 real credit applications, 20 attributes, binary label.

Label convention in the raw file: 1 = Good credit, 2 = Bad credit.
We model the REJECT decision, so y = 1 means "bad credit -> reject".
The dataset ships an asymmetric cost matrix (misclassifying a bad
applicant as good costs 5x the reverse); we record it but the MVP's
slashing economics are driven by calibration, not by this matrix.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA_RAW, PROTECTED_COLUMNS, SEED, TRAIN_FRAC, CALIB_FRAC

UCI_URL = "https://archive.ics.uci.edu/static/public/144/statlog+german+credit+data.zip"

COLUMNS = [
    "checking_status", "duration_months", "credit_history", "purpose",
    "credit_amount", "savings_status", "employment_since",
    "installment_rate_pct_income", "personal_status_sex", "other_debtors",
    "residence_since", "property", "age_years", "other_installment_plans",
    "housing", "n_existing_credits", "job", "n_liable_maintenance",
    "telephone", "foreign_worker", "label_raw",
]

# Ordinal encodings taken directly from german.doc. Encoding these as ordered
# integers (rather than one-hot) keeps the feature space small and, more
# importantly, keeps SHAP attributions interpretable in Phase 2: "worse
# checking account status" must move monotonically in one direction.
ORDINAL_MAPS = {
    # A11 <0 DM, A12 0-200, A13 >=200, A14 no account.
    # Ordered worst->best financial position; "no account" placed at the top
    # because in this dataset it empirically associates with LOW risk.
    "checking_status": {"A11": 0, "A12": 1, "A13": 2, "A14": 3},
    "savings_status": {"A61": 0, "A62": 1, "A63": 2, "A64": 3, "A65": 4},
    "employment_since": {"A71": 0, "A72": 1, "A73": 2, "A74": 3, "A75": 4},
    # Credit history. Ordered by EMPIRICAL creditworthiness in this dataset,
    # not by a naive reading of the label text. Measured bad rates:
    #   A30 "no credits taken/all paid duly"      62.5% bad  (n=40)   <- worst
    #   A31 "all credits at this bank paid duly"  57.1% bad  (n=49)
    #   A33 "delay in paying off in the past"     31.8% bad  (n=88)
    #   A32 "existing credits paid duly till now" 31.9% bad  (n=530)
    # A32 and A33 differ by 0.0007 in bad rate (indistinguishable at these
    # sample sizes), so they are ordered by the codebook's semantics --
    # "delay in the past" ranked below "paid duly till now" -- rather than by
    # a difference that is pure noise.
    #   A34 "critical account/other credits"      17.1% bad  (n=293)  <- best
    # This inversion is real and well known for this dataset: a thin file
    # ("no credits taken") is riskier than a thick, currently-serviced file,
    # because the latter is evidence of demonstrated creditworthiness.
    # An earlier version of this map encoded the naive order and made the
    # Phase 2 directional sanity check fail; the model was right and the
    # encoding was wrong. See docs/PHASE2.md.
    "credit_history": {"A30": 0, "A31": 1, "A33": 2, "A32": 3, "A34": 4},
    "property": {"A124": 0, "A123": 1, "A122": 2, "A121": 3},
    "job": {"A171": 0, "A172": 1, "A173": 2, "A174": 3},
    "other_debtors": {"A101": 0, "A102": 1, "A103": 2},
    "other_installment_plans": {"A141": 0, "A142": 1, "A143": 2},
    "housing": {"A153": 0, "A151": 1, "A152": 2},
    "telephone": {"A191": 0, "A192": 1},
    "foreign_worker": {"A202": 0, "A201": 1},
}

NUMERIC_COLUMNS = [
    "duration_months", "credit_amount", "installment_rate_pct_income",
    "residence_since", "age_years", "n_existing_credits",
    "n_liable_maintenance",
]

# Human-readable descriptions used by the SHAP sanity checks and the demo.
FEATURE_DESCRIPTIONS = {
    "checking_status": "Checking account status (0=<0DM, 1=0-200DM, 2=>=200DM, 3=no checking account)",
    "duration_months": "Loan duration in months (higher = riskier)",
    "credit_history": "Credit history, empirical risk order (0=thin file/no credits, 4=established account with other credits)",
    "credit_amount": "Credit amount requested in DM (higher = riskier)",
    "savings_status": "Savings account/bonds (0=<100DM ... 3=>=1000DM, 4=unknown/no savings account)",
    "employment_since": "Years in present employment (0=unemployed, 4=7+ yrs)",
    "installment_rate_pct_income": "Installment as % of disposable income (DTI proxy; higher = riskier)",
    "other_debtors": "Co-applicant/guarantor present (2=guarantor)",
    "residence_since": "Years at present residence",
    "property": "Property owned (0=none/unknown, 3=real estate)",
    "age_years": "Age in years",
    "other_installment_plans": "Other installment plans (2=none)",
    "housing": "Housing (0=for free, 1=rent, 2=own)",
    "n_existing_credits": "Number of existing credits at this bank",
    "job": "Job skill level (0=unemployed/unskilled, 3=management)",
    "n_liable_maintenance": "Dependants requiring maintenance",
    "telephone": "Registered telephone (1=yes)",
    "foreign_worker": "Foreign worker (1=yes)",
    "purpose": "Loan purpose (categorical code)",
}


def fetch_raw(dest: Path = DATA_RAW) -> Path:
    """Download and extract german.data if not already present."""
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "german.data"
    if target.exists():
        return target
    import urllib.request
    with urllib.request.urlopen(UCI_URL, timeout=120) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        zf.extractall(dest)
    if not target.exists():
        raise RuntimeError(f"german.data not found after extracting {UCI_URL}")
    return target


def load_frame(path: Path | None = None, drop_protected: bool = True) -> pd.DataFrame:
    """Load and encode the dataset into a numeric feature frame + label."""
    path = path or fetch_raw()
    df = pd.read_csv(path, sep=r"\s+", header=None, names=COLUMNS)

    # y = 1 means BAD credit -> the model's REJECT class.
    df["label"] = (df["label_raw"] == 2).astype(int)
    df = df.drop(columns=["label_raw"])

    for col, mapping in ORDINAL_MAPS.items():
        unknown = set(df[col].unique()) - set(mapping)
        if unknown:
            raise ValueError(f"unmapped codes in {col}: {sorted(unknown)}")
        df[col] = df[col].map(mapping).astype(int)

    # 'purpose' has no natural order; encode as stable integer codes.
    purpose_levels = sorted(df["purpose"].unique())
    df["purpose"] = df["purpose"].map({v: i for i, v in enumerate(purpose_levels)}).astype(int)

    if drop_protected:
        df = df.drop(columns=[c for c in PROTECTED_COLUMNS if c in df.columns])
    else:
        df["personal_status_sex"] = df["personal_status_sex"].astype("category").cat.codes

    for col in NUMERIC_COLUMNS:
        df[col] = df[col].astype(float)
    return df


def split_three_way(df: pd.DataFrame, seed: int = SEED):
    """Stratified train / calibration / test split.

    The calibration split is disjoint from train AND test. This is
    correctness-critical: fitting the calibration head on data the base model
    was trained on measures the base model's memorisation, not its
    generalisation confidence, and yields the wrong temperature.
    """
    from sklearn.model_selection import train_test_split

    y = df["label"].values
    X = df.drop(columns=["label"])

    idx = np.arange(len(df))
    calib_plus_test = 1.0 - TRAIN_FRAC
    idx_train, idx_rest = train_test_split(
        idx, test_size=calib_plus_test, random_state=seed, stratify=y
    )
    # Split the remainder into calibration and test.
    rest_calib_frac = CALIB_FRAC / calib_plus_test
    idx_calib, idx_test = train_test_split(
        idx_rest, train_size=rest_calib_frac, random_state=seed, stratify=y[idx_rest]
    )

    assert not (set(idx_train) & set(idx_calib)), "train/calib overlap"
    assert not (set(idx_train) & set(idx_test)), "train/test overlap"
    assert not (set(idx_calib) & set(idx_test)), "calib/test overlap"

    def take(ix):
        return X.iloc[ix].reset_index(drop=True), y[ix]

    return {
        "train": take(idx_train),
        "calib": take(idx_calib),
        "test": take(idx_test),
        "feature_names": list(X.columns),
    }
