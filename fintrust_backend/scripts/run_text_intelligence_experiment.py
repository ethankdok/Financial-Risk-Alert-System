from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.text_experiments import summarize_annotation_quality
from app.services.text_experiments import load_annotation_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize annotation quality for Text Mining / Evidence v2 experiments.")
    parser.add_argument("--annotations", required=True, help="Ground Truth annotation CSV path")
    parser.add_argument("--output", help="Optional JSON report path")
    args = parser.parse_args()

    rows = load_annotation_csv(args.annotations)
    report = summarize_annotation_quality(rows)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

