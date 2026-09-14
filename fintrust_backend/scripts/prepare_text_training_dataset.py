from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.text_experiments import group_aware_split, load_annotation_csv, to_train_ready_rows, validate_annotation_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate human annotations and create a group-aware train/test manifest.")
    parser.add_argument("--annotations", required=True, help="Completed human annotation CSV.")
    parser.add_argument("--output", required=True, help="Output train-ready JSON path.")
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = load_annotation_csv(args.annotations)
    validation = validate_annotation_rows(rows)
    ready = to_train_ready_rows(rows)
    split = group_aware_split(ready, test_ratio=args.test_ratio, seed=args.seed)
    payload = {
        "schema_version": "text-training-dataset-v1.0",
        "annotation_version": Path(args.annotations).stem,
        "validation": validation,
        "train_ready_count": len(ready),
        "split_manifest": {
            "seed": split["seed"],
            "test_ratio": split["test_ratio"],
            "train_groups": split["train_groups"],
            "test_groups": split["test_groups"],
            "document_leakage_prevented": split["document_leakage_prevented"],
        },
        "train": split["train"],
        "test": split["test"],
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "valid": validation["valid"], "train_ready_count": len(ready)}, ensure_ascii=False))
    return 0 if validation["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
