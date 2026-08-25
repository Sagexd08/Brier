"""The monitoring service: run the detector, flag what it flags.

This is the piece that closes the loop from the GNN of Phase E to the
CollusionOracle on chain. It is the component the ablation report previously
said did not exist, and the reason it now does is a deliberate decision to give
an unvalidated model an enforcement path.

WHAT THAT MEANS IN PRACTICE, restated at the point of use:

  The detector has never been validated against real collusion. Its
  false-positive rate on genuine dispute traffic is unmeasured. Every address
  this script flags is blocked from filing disputes and has its payouts
  withheld once the appeal window elapses. Some of those addresses will be
  innocent, and nobody currently knows what fraction.

The script therefore defaults to --dry-run, refuses to submit without an
explicit --i-understand-this-is-unvalidated flag, and caps how many addresses
one invocation may flag. Those are speed bumps, not safety. The only real
safety here is the on-chain appeal window and the reversible quarantine.

    python scripts/20_collusion_reporter.py --dry-run
    python scripts/20_collusion_reporter.py --submit --i-understand-this-is-unvalidated

Writes artifacts/ablation/collusion_flags.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brier.collusion import (  # noqa: E402
    build_adjacency,
    claimant_features,
    generate_dispute_graph,
    predict_scores,
    train_detector,
)
from brier.config import ARTIFACTS  # noqa: E402

OUT = ARTIFACTS / "ablation"

# Must match CollusionOracle.MIN_SCORE. A flag below this is refused on chain,
# so submitting one wastes gas and signals the threshold has drifted.
MIN_SCORE_WAD = int(0.8e18)

# Ceiling on a single run. A detector that suddenly flags half the claimant
# population is malfunctioning, and the correct response is to stop rather than
# to faithfully relay it.
MAX_FLAGS_PER_RUN = 10


def score_graph(seed: int) -> tuple[np.ndarray, dict]:
    """Train on the labelled synthetic graph, score every claimant.

    NOTE: training on injected rings is the only option available, and it is
    exactly the limitation that makes the output unvalidated. A production
    deployment would need a labelled corpus of real disputes here, and does not
    have one.
    """
    g = generate_dispute_graph(seed=seed)
    x = claimant_features(g)
    nb = build_adjacency(g)
    y = g["labels"]

    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(y))
    train_mask = np.zeros(len(y), dtype=bool)
    train_mask[perm[: len(y) // 2]] = True

    model = train_detector(x, nb, y, train_mask, seed=seed)
    return predict_scores(model, x, nb), g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--submit", action="store_true",
                    help="actually send flag() transactions")
    ap.add_argument("--i-understand-this-is-unvalidated", action="store_true",
                    help="required alongside --submit; see this file's header")
    ap.add_argument("--rpc", default="http://127.0.0.1:8545")
    ap.add_argument("--oracle", help="CollusionOracle address")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model-version", default="gnn-v1")
    args = ap.parse_args()

    scores, graph = score_graph(args.seed)

    flagged = [
        {
            "claimant_index": int(i),
            "score": float(scores[i]),
            "score_wad": int(scores[i] * 1e18),
            "is_injected_ring_member": bool(graph["labels"][i]),
        }
        for i in np.argsort(-scores)
        if scores[i] >= MIN_SCORE_WAD / 1e18
    ]

    # Against synthetic ground truth we can state the error directly. This is
    # the number a real deployment would not have.
    true_pos = sum(1 for f in flagged if f["is_injected_ring_member"])
    false_pos = len(flagged) - true_pos

    report = {
        "seed": args.seed,
        "model_version": args.model_version,
        "threshold_wad": MIN_SCORE_WAD,
        "n_flagged": len(flagged),
        "true_positives_vs_injected_labels": true_pos,
        "false_positives_vs_injected_labels": false_pos,
        "precision_on_synthetic_labels": (true_pos / len(flagged)) if flagged else None,
        "flags": flagged,
        "validation_status": "synthetic_only",
        "warning": (
            "These flags come from a detector validated only against injected "
            "rings. The false-positive count above is measured against synthetic "
            "labels and says nothing about real traffic, where the rate is "
            "unknown. Enforcement blocks disputes and withholds payouts."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "collusion_flags.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"  detector flagged {len(flagged)} claimants at score >= "
          f"{MIN_SCORE_WAD / 1e18:.2f}")
    print(f"  against injected labels: {true_pos} true, {false_pos} FALSE POSITIVE")
    if flagged:
        print(f"  precision on synthetic labels: {true_pos / len(flagged):.3f}")
    print(f"  wrote {(OUT / 'collusion_flags.json').relative_to(ROOT)}")

    if not args.submit:
        print("\n  DRY RUN - nothing submitted. Pass --submit to send transactions.")
        return 0

    if not args.i_understand_this_is_unvalidated:
        print("\n  REFUSED: --submit requires --i-understand-this-is-unvalidated.")
        print("  The detector has never been validated against real collusion;")
        print("  flagging blocks disputes and withholds payouts from real addresses.")
        return 2

    if len(flagged) > MAX_FLAGS_PER_RUN:
        print(f"\n  REFUSED: {len(flagged)} flags exceeds the per-run cap of "
              f"{MAX_FLAGS_PER_RUN}.")
        print("  A detector flagging this many addresses at once is more likely")
        print("  malfunctioning than correct. Investigate before relaying it.")
        return 3

    if not args.oracle:
        print("\n  REFUSED: --oracle address is required to submit.")
        return 4

    print("\n  Submission path requires an address book mapping claimant indices")
    print("  to real addresses, which this synthetic graph does not have.")
    print("  Wire that in before running against a live chain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
