"""Independent before/after reproduction of review findings F-2B-01 and F-2B-02 (offline, no network, no writes
outside a temporary directory).

Run from fintrust_backend/ in a checkout that contains commit 98952ce (the reviewed code):

    python ../docs/development/evidence/historical_audit_phase2b_carryover_repro.py [--before 98952ce]

The "before" modules are loaded from ``git show <before>:<path>``; the "after" modules from the working tree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

RUNNER = "fintrust_backend/scripts/recover_historical_conference_pdfs.py"
COVERAGE = "fintrust_backend/app/services/historical_audit/conference_coverage.py"


def load(name: str, source: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = name
    exec(compile(source, name, "exec"), module.__dict__)
    return module


def git_show(revision: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{revision}:{path}"], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def failed_year_result() -> dict:
    """A year whose listing names 2 PDFs and neither was archived (genuine acquisition failure)."""
    return {"status": "failed", "listing_pages": [1], "rows": 1, "expected_pdfs": 2, "downloaded_pdfs": 0,
            "documents": [{"filename": "178520200910M001.pdf", "status": "failed", "error": "timeout"},
                          {"filename": "178520200910E001.pdf", "status": "failed", "error": "timeout"}],
            "errors": ["178520200910M001.pdf: timeout", "178520200910E001.pdf: timeout"]}


def runner_exit(module: types.ModuleType, result: dict, tmp: Path) -> int:
    class Stub:
        def __init__(self, *args, **kwargs):
            pass

        def record(self, ticker, years, **_):
            return [{"status": "x", "conference_rows": 0, "meeting_dates_json": "[]", "expected_documents": 0,
                     "downloaded_documents": 0, "non_pdf_attachments": 0, "missing_documents": 0}]

    def fake_pipeline(**_):
        return result

    module.ConferenceCoverageRecorder = Stub
    module.HttpMopsTransport = Stub
    module.HistoricalAuditRepository = Stub
    module.RawEvidenceArchive = Stub
    module.run_mops_pdf_pipeline = fake_pipeline
    if hasattr(module, "run_recovery"):
        module.run_recovery.__kwdefaults__["pipeline"] = fake_pipeline
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        return module.main(["--ticker", "1785", "--years", "2020", "--market", "otc", "--output", str(tmp)])


def coverage_row(module: types.ModuleType, tmp: Path) -> dict:
    from app.services.historical_audit.archive import RawEvidenceArchive
    from app.services.historical_audit.repository import HistoricalAuditRepository

    def link(name: str) -> str:
        return (f'<a onclick="document.fm_fileDownload.fileName.value=&quot;{name}&quot;;'
                'document.fm_fileDownload.filePath.value=&quot;/home/html/nas/STR/&quot;;'
                'document.fm_fileDownload.functionName.value=&quot;t100sb02_1&quot;;document.fm_fileDownload.submit();">'
                f'{name}</a>')
    listing = ('<form action="/server-java/FileDownLoad"></form><table><thead><tr><th>公司代號</th><th>法人說明會簡報內容</th>'
               '</tr></thead><tbody><tr data-type="body"><td>1785</td><td>光洋科</td><td>109/09/10</td><td>x</td><td>x</td>'
               f'<td>x</td><td>{link("178520200910M001.pdf")}</td><td>{link("178520200910E001.pdf")}</td></tr></tbody></table>'
               '<input onclick="page(1)" value="1">').encode()

    class Transport:
        def listing(self, *_args, **_kwargs):
            return listing

    repository = HistoricalAuditRepository(str(tmp / "db.sqlite3"))
    repository.initialize()
    recorder = module.ConferenceCoverageRecorder(repository, RawEvidenceArchive(tmp / "raw"), tmp / "conf",
                                                 transport=Transport(), sleep=lambda _: None)
    row = recorder.record("1785", [2020], market="otc", start_year=2011, end_year=2022)[0]
    return {key: row[key] for key in ("status", "expected_documents", "downloaded_documents", "missing_documents")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="98952ce")
    args = parser.parse_args()
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True,
                               text=True).stdout.strip())
    out: dict = {}
    for label, source in (("before", lambda p: git_show(args.before, p)),
                          ("after", lambda p: (root / p).read_text(encoding="utf-8"))):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runner = load(f"runner_{label}", source(RUNNER))
            coverage = load(f"coverage_{label}", source(COVERAGE))
            out[label] = {
                "F-2B-01 exit code for a year with 2 listed / 0 archived PDFs": runner_exit(runner, failed_year_result(), tmp_path),
                "F-2B-02 coverage row for 2 listed / 0 archived (no manifest)": coverage_row(coverage, tmp_path),
            }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
