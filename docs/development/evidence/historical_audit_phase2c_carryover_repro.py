"""Independent before/after reproduction of the Phase 2C carryover findings A1-A3 (offline; temporary files only).

Run from fintrust_backend/ in a checkout containing commit c4bb82f (the reviewed code) and the released strict ZIP
data/historical_audit/packages/fintrust_1785_asof_2016-11-14.zip (for A1):

    python ../docs/development/evidence/historical_audit_phase2c_carryover_repro.py [--before c4bb82f]

"before" modules come from ``git show <before>:<path>``; "after" modules from the working tree.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

VERIFY = "fintrust_backend/app/services/historical_audit/package_verify.py"
RUNNER = "fintrust_backend/scripts/recover_historical_conference_pdfs.py"
STRICT = Path("data/historical_audit/packages/fintrust_1785_asof_2016-11-14.zip")


def load(name: str, source: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = name
    sys.modules[name] = module
    exec(compile(source, name, "exec"), module.__dict__)
    return module


def a1_mutated_package(tmp: Path) -> Path:
    """Reviewer reproduction: FY2013 restated COGS 33223945000 -> 33223946000 in CSV and JSON, checksums recomputed."""
    from tests.historical_evidence_fixtures import mutate_csv, repack_package

    import zipfile

    root = "fintrust_historical_research_dataset/"
    with zipfile.ZipFile(STRICT) as archive:
        facts = archive.read(root + "data/financial_facts.csv")
        envelope = json.loads(archive.read(root + "data/financial_facts.json"))
    mutated = mutate_csv(facts, {"period": "2013FY", "metric_code": "cost_of_goods_sold"}, {"value": "33223946000"})
    typed = lambda v: None if v == "" else True if v == "true" else False if v == "false" else v  # noqa: E731
    envelope["records"] = [{k: typed(v) for k, v in r.items()} for r in csv.DictReader(io.StringIO(mutated.decode("utf-8")))]
    return repack_package(STRICT, tmp / "a1.zip", {"data/financial_facts.csv": mutated,
                                                   "data/financial_facts.json": json.dumps(envelope, ensure_ascii=False).encode()})


def a1(verify: types.ModuleType, package: Path) -> str:
    try:
        return "ACCEPTED status=" + verify.verify_package(package)["status"]
    except Exception as exc:  # noqa: BLE001
        return "REJECTED: " + str(exc)[:110]


def a2(runner: types.ModuleType) -> int:
    class Case:
        ticker, default_start_year, default_end_year = "1785", 2011, 2016

    class FailingRecorder:
        def record(self, *args, **kwargs):
            raise OSError("simulated database disk full")

    class Inner:
        def listing(self, *a, **k):
            raise AssertionError("no network")

        def pdf(self, *a, **k):
            raise AssertionError("no network")

    def pipeline(**_):
        return {"status": "complete", "listing_pages": [1], "errors": [], "expected_pdfs": 2, "downloaded_pdfs": 2,
                "documents": [{"filename": n, "sha256": "a" * 64, "status": "complete"} for n in ("a.pdf", "b.pdf")]}

    transport = runner.PacedTransport(Inner(), delay=0, max_consecutive_failures=3, sleep=lambda _: None)
    _report, code = runner.run_recovery(Case(), [2023], market="otc", output=Path("unused"), transport=transport,
                                        recorder=FailingRecorder(), pipeline=pipeline)
    return code


def a3(runner: types.ModuleType) -> dict:
    return {
        "listing_pages=[1], documents=[], errors=['parse error'], status=failed": runner.classify_year(
            {"listing_pages": [1], "documents": [], "errors": ["parse error"], "status": "failed"})[0],
        "listing_pages=[], errors=['service timeout'], status=no_listing": runner.classify_year(
            {"listing_pages": [], "documents": [], "errors": ["service timeout"], "status": "no_listing"})[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="c4bb82f")
    args = parser.parse_args()
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip())
    show = lambda path: subprocess.run(["git", "show", f"{args.before}:{path}"], check=True, capture_output=True,  # noqa: E731
                                       text=True, encoding="utf-8").stdout
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        package = a1_mutated_package(Path(tmp))
        for label, source in (("before", show), ("after", lambda p: (root / p).read_text(encoding="utf-8"))):
            verify = load(f"verify_{label}", source(VERIFY))
            runner = load(f"runner_{label}", source(RUNNER))
            out[label] = {"A1 reviewer mutation (FY2013 COGS +1000 TWD)": a1(verify, package),
                          "A2 exit code (acquisition complete, coverage storage OSError)": a2(runner),
                          "A3 classification": a3(runner)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
