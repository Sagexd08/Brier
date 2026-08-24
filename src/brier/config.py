"""Central configuration. Seeds live here so every stage is reproducible."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROC = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "artifacts"
MODELS = ARTIFACTS / "models"
CALIB = ARTIFACTS / "calibration"
SHAP_DIR = ARTIFACTS / "shap"
ZK = ARTIFACTS / "zk"
CONTRACTS = ROOT / "contracts"

SEED = 42

# Three-way split. The calibration set is disjoint from BOTH train and test.
# Calibrating on training data is the classic correctness bug in this pipeline:
# the base model's train-set logits are overconfident in a way that does not
# generalise, so a head fitted there learns the wrong temperature.
TRAIN_FRAC = 0.60
CALIB_FRAC = 0.20
TEST_FRAC = 0.20

# Number of equal-width bins for Expected Calibration Error.
ECE_BINS = 10

# Attribute 9 of the UCI German Credit data encodes personal status AND sex.
# Excluded by default: a credit-decision demo must not silently train on a
# protected attribute. Documented in docs/PHASE1.md.
PROTECTED_COLUMNS = ("personal_status_sex",)

MODEL_VERSION = "brier-mvp-v1"
