"""CR-04 parser regression evidence: extract_claim with the old vs the new AMOUNT_RE on every amount-bearing string
literal found in the existing test suites (read-only).

    (cwd = fintrust_backend) python claim_parser_regression_diff.py --out <json>

Every changed parse is listed; a change is expected only where the old regex dropped a thousands group or a sign.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app.services import claim_parser  # noqa: E402

OLD = re.compile(r"(-?\d+(?:\.\d+)?)\s*(兆|億|百萬|萬|千|仟|元)(?:元)?")
AMOUNT_HINT = re.compile(r"\d\s*(兆|億|百萬|萬|千|仟|元)")


def corpus() -> list[str]:
    roots = [Path("tests"), Path("../tests")]
    texts = set()
    for root in roots:
        for path in root.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and AMOUNT_HINT.search(node.value):
                    if len(node.value) < 300:
                        texts.add(node.value)
    return sorted(texts)


def parse(text: str) -> dict:
    claim = claim_parser.extract_claim(text)
    return {"value": claim.claimed_value, "unit": claim.unit, "metric": claim.metric, "period": claim.period,
            "missing": claim.missing_fields}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    new_re = claim_parser.AMOUNT_RE
    texts = corpus()
    rows, changed = [], []
    for text in texts:
        claim_parser.AMOUNT_RE = OLD
        old = parse(text)
        claim_parser.AMOUNT_RE = new_re
        new = parse(text)
        rows.append({"text": text, "old": old, "new": new})
        if old != new:
            changed.append({"text": text, "old": old, "new": new,
                            "explained_by_grouping_or_sign": bool(re.search(r"\d,\d|-\d", text))})
    report = {"strings": len(texts), "changed": changed, "unchanged": len(texts) - len(changed),
              "unexplained_changes": [c for c in changed if not c["explained_by_grouping_or_sign"]]}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: (v if k != "changed" else v) for k, v in report.items()}, ensure_ascii=False, indent=1))
    sys.exit(1 if report["unexplained_changes"] else 0)


if __name__ == "__main__":
    main()
