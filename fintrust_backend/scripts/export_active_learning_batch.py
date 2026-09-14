from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.text_experiments import rank_active_learning_candidates


def _load_json_rows(path: str | Path) -> list[dict[str, object]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("unlabeled") or payload.get("rows") or [])


def _load_probabilities(path: str | Path) -> list[dict[str, float]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("predictions", [])
    return [{str(key): float(value) for key, value in row.items() if key not in {"sample_id", "text"}} for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank unlabeled official sentences for the next active-learning annotation batch.")
    parser.add_argument("--unlabeled", required=True, help="JSON rows exported from text evidence candidates.")
    parser.add_argument("--probabilities", required=True, help="JSON prediction probabilities aligned with unlabeled rows.")
    parser.add_argument("--output", required=True, help="CSV output path.")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    ranked = rank_active_learning_candidates(
        _load_json_rows(args.unlabeled),
        _load_probabilities(args.probabilities),
        limit=args.limit,
    )
    fieldnames = ["sample_id", "text", "predicted_label", "confidence", "uncertainty", "source", "period"]
    with Path(args.output).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ranked)
    print(json.dumps({"output": args.output, "count": len(ranked)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
