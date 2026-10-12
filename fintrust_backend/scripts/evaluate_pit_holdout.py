"""Read-only research CLI for explicit, independently verified PIT holdout cohorts.

Example:
  python -m scripts.evaluate_pit_holdout --input sanitized_cohort.json \
      --threshold 0.5 --threshold-id frozen_v1 --experiment-id trial_v1

Input is local user-provided JSON; no network, ingestion or DB writes.
Output goes to stdout; data claims remain unverified until reviewed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.integrity.research_evaluation import evaluate_holdout


def main() -> int:
    parser = argparse.ArgumentParser(description="FinTrust PIT holdout research diagnostic (read-only)")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--threshold", required=True)
    parser.add_argument("--threshold-id", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--horizon-days", type=int, default=365)
    parser.add_argument("--training-ticker", action="append", default=[])
    args = parser.parse_args()
    if not args.input.is_file() or args.input.suffix.lower() != ".json":
        parser.error("input must be an existing explicit .json file")
    try:
        observations = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read input: {type(exc).__name__}")
    if not isinstance(observations, list) or len(observations) > 10000 or not all(
        isinstance(row, dict) for row in observations
    ):
        parser.error("input must be a JSON array (max 10000 objects)")
    try:
        result = evaluate_holdout(
            observations, threshold=args.threshold,
            threshold_id=args.threshold_id, experiment_id=args.experiment_id,
            horizon_days=args.horizon_days, training_tickers=args.training_ticker,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "descriptive_holdout_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
