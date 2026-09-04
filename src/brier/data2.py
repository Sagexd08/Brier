"""Second dataset: UCI "Default of Credit Card Clients" (Taiwan, 2005).

PAPER.md §8.6 limits every empirical claim to one dataset, one model family and
one decision class. This module exists to test whether those claims travel.

Source: https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients
30,000 real credit-card accounts from a Taiwanese bank, 23 features, binary
label (default next month). Fetched via OpenML data_id 42477.

WHY THIS ONE, and the choice matters more than it looks. A second dataset only
tests external validity if it differs on the axes that could be driving the
result. Against German Credit this differs on all four that plausibly matter:

  size          1,000 -> 30,000 rows (30x)
  geography     Germany -> Taiwan
  vintage       1994 -> 2005
  label         expert-assigned credit grade -> an OBSERVED default event

The last is the important one. German Credit's label is a human analyst's
judgement of creditworthiness; this one records whether the account actually
defaulted the following month. A calibration result that only held on
adjudicated opinion, and not on realised outcomes, would be a much weaker
result -- and the two datasets are the pair that can tell those apart.

The size difference is doing separate work. §8.4 reports that binned ECE is
biased upward at small n, and that the German Credit subgroup analysis is
dominated by that bias at n = 68. With 6,000 test rows and subgroups in the
thousands, this dataset sits well below the noise floor and can resolve a
subgroup question that the first one could not.

PROTOCOL PARITY. The split fractions, the seed protocol, the calibration
discipline and the metric definitions are all imported from the same modules
the German Credit pipeline uses -- not reimplemented here. Anything that
differs between the two runs is the data, which is the only way the comparison
means anything.

PROTECTED ATTRIBUTE. x2 is sex, and it is dropped from the feature set for the
same reason attribute 9 is dropped from German Credit: using it in a credit
decision would be unlawful in most regimes. It is recoverable as a grouping
label via `load_frame(drop_protected=False)`, which is what the subgroup
analysis needs and what the model must never see.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import CALIB_FRAC, SEED, TRAIN_FRAC

OPENML_ID = 42477

# Names from the UCI codebook, in the order OpenML serves them as x1..x23.
COLUMNS = {
    "x1": "limit_bal",       # credit limit, NT dollars
    "x2": "sex",             # 1 = male, 2 = female  -- PROTECTED, dropped
    "x3": "education",       # 1 grad school .. 4 other
    "x4": "marriage",        # 1 married, 2 single, 3 other
    "x5": "age",             # years
    "x6": "pay_0",           # repayment status, most recent month
    "x7": "pay_2",
    "x8": "pay_3",
    "x9": "pay_4",
    "x10": "pay_5",
    "x11": "pay_6",
    "x12": "bill_amt1",      # bill statement amounts
    "x13": "bill_amt2",
    "x14": "bill_amt3",
    "x15": "bill_amt4",
    "x16": "bill_amt5",
    "x17": "bill_amt6",
    "x18": "pay_amt1",       # previous payment amounts
    "x19": "pay_amt2",
    "x20": "pay_amt3",
    "x21": "pay_amt4",
    "x22": "pay_amt5",
    "x23": "pay_amt6",
}

PROTECTED_COLUMNS = ("sex",)

CACHE = Path(__file__).resolve().parents[2] / "data" / "raw" / "taiwan_credit.parquet"


def fetch_raw(path: Path | None = None) -> Path:
    """Fetch from OpenML once and cache locally.

    Cached as parquet rather than re-fetched per run: a network dependency in
    the middle of a reproducibility appendix is a way for results to become
    unreproducible when a remote changes.
    """
    path = path or CACHE
    if path.exists():
        return path

    from sklearn.datasets import fetch_openml

    d = fetch_openml(data_id=OPENML_ID, as_frame=True, parser="auto")
    df = d.data.copy()
    df["label"] = d.target.astype(int)

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return path


def load_frame(path: Path | None = None, drop_protected: bool = True) -> pd.DataFrame:
    """Load into a numeric feature frame + label, mirroring data.load_frame.

    y = 1 means DEFAULT -> the model's REJECT class, matching the first
    dataset's convention that y = 1 is the adverse decision.
    """
    df = pd.read_parquet(fetch_raw(path))
    df = df.rename(columns=COLUMNS)

    # Every column is already numeric; the categorical ones (education,
    # marriage) carry small integer codes with a natural ordering, so they are
    # left as ordinals for the same reason data.py keeps its ORDINAL_MAPS:
    # one-hot would inflate the feature space and break SHAP monotonicity.
    for c in df.columns:
        df[c] = pd.to_numeric(df[c])

    if drop_protected:
        df = df.drop(columns=[c for c in PROTECTED_COLUMNS if c in df.columns])

    return df


def split_three_way(df: pd.DataFrame, seed: int = SEED):
    """Stratified train / calibration / test split.

    Identical fractions and identical stratification to data.split_three_way.
    The calibration split is disjoint from train AND test, which is
    correctness-critical for the same reason it is there: fitting the head on
    data the base model saw measures memorisation, not generalisation
    confidence.
    """
    from sklearn.model_selection import train_test_split

    y = df["label"].values
    X = df.drop(columns=["label"])

    idx = np.arange(len(df))
    calib_plus_test = 1.0 - TRAIN_FRAC
    idx_train, idx_rest = train_test_split(
        idx, test_size=calib_plus_test, random_state=seed, stratify=y
    )
    idx_calib, idx_test = train_test_split(
        idx_rest, train_size=CALIB_FRAC / calib_plus_test,
        random_state=seed, stratify=y[idx_rest]
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
        "indices": {"train": idx_train, "calib": idx_calib, "test": idx_test},
    }
