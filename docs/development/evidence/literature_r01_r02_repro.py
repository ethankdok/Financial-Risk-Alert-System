"""Replay the df0fc44 review's two synthetic reproductions (R01, R02) against the checked-out source.

    cd fintrust_backend && python ../docs/development/evidence/literature_r01_r02_repro.py [--out file.json]

Uses only the API present both before and after the hardening (``FilingLines``, ``assemble``, ``prove_zero``) and the
synthetic official-shaped generators of the test suite, so the same script runs on a df0fc44 worktree ("before") and
on the hardened commit ("after"). Every case catches exceptions and records them as outcomes. No data is read or
written except ``--out``.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path.cwd()
sys.path.insert(0, str(BACKEND))

from app.services.financial_research.literature_inputs import (  # noqa: E402
    SOURCE_GATE_VERSION,
    ZERO_POLICY_VERSION,
    FilingLines,
    assemble,
    prove_zero,
)
from tests.test_literature_data_integrity import twgaap_filing  # noqa: E402
from tests.test_literature_models import obs  # noqa: E402

PREFERRED = ("TW_GAAP", "preferred_stock", "I:2012-12-31")


def flow(line: str, value: int) -> dict:
    return {**obs("F2015", 2015, line, value), "period_type": "duration", "period_start": "2015-01-01"}


def outcome(build) -> dict:
    try:
        value = build()
    except Exception as exc:  # recorded, not raised: an exception is itself the reproduced defect
        return {"exception": f"{type(exc).__name__}: {exc}"}
    return {"status": value.status, "value": None if value.value is None else str(value.value),
            "evidence_type": value.evidence_type, "reasons": value.reasons}


def cases() -> dict:
    r01 = {
        "tifrs_conflicting_cash_flow_anchors_100_vs_200": lambda: assemble(
            FilingLines([flow("CashFlowsFromUsedInOperatingActivities", 100),
                         flow("NetCashFlowsFromUsedInOperatingActivities", 200), flow("ProceedsFromIssuingShares", 50)]),
            "TIFRS", "stock_issued", "D:2015-01-01/2015-12-31"),
        "tifrs_agreeing_cash_flow_anchors_100_and_100": lambda: assemble(
            FilingLines([flow("CashFlowsFromUsedInOperatingActivities", 100),
                         flow("NetCashFlowsFromUsedInOperatingActivities", 100), flow("ProceedsFromIssuingShares", 50)]),
            "TIFRS", "stock_issued", "D:2015-01-01/2015-12-31"),
    }
    rows = twgaap_filing("G2012", 2012)
    proof = prove_zero(FilingLines(rows), *PREFERRED)
    tampered = {**copy.deepcopy(proof), "operands": [], "section_total_twd": "123456789",
                "evidence_fingerprint": "0" * 64}
    dropped = [r for r in rows if not (r["line_key"] == "code:3350" and r["period_end"] == "2012-12-31")]
    r02 = {
        "valid_proof": lambda: assemble(FilingLines(rows, [proof]), *PREFERRED),
        "tampered_operands_total_fingerprint": lambda: assemble(FilingLines(rows, [tampered]), *PREFERRED),
        "referenced_observation_removed": lambda: assemble(FilingLines(dropped, [proof]), *PREFERRED),
    }
    return {"R01": {k: outcome(v) for k, v in r01.items()}, "R02": {k: outcome(v) for k, v in r02.items()}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True).stdout.strip()
    report = {"source_commit": head, "source_gate_version": SOURCE_GATE_VERSION,
              "zero_evidence_policy_version": ZERO_POLICY_VERSION, **cases()}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
