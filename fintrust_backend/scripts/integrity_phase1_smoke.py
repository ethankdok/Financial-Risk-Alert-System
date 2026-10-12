"""Integrity Workbench Phase 1 E2E smoke on genuine local data: FastAPI + Flask processes, Flask proxy, headless browser.

    python -m scripts.integrity_phase1_smoke --out <dir> [--browser <chrome/edge exe>]

- The pipeline database is copied to a scratch file first and served from the copy (the existing SQLite repository
  commits its schema script on open); the original's SHA-256 is recorded before and after.
- The conference archive and literature input store are only read (file reads; ``mode=ro`` SQLite).
- Every browser-path request goes over real localhost HTTP through the Flask integrity proxy; a direct FastAPI
  call is compared for parity. Refusals (persist, STRICT_AS_OF, unknown ticker) are checked.
- With a Chromium-based browser, each of the four page sections is rendered headless with evidence expanded:
  PNG screenshot + DOM, checked for the key real-data strings.
- The sanitized real outputs (official URLs only, no filesystem paths) are written as JSON with the read-only
  commands and source digests.

No network beyond 127.0.0.1, no cloud, no LLM, no live MOPS fetch, no writes to any approved data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.research_ui_smoke import BROWSERS, free_port, get, wait

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DATA = BACKEND / "data"
PIPELINE_DB = DATA / "financial_pipeline.sqlite3"
ARCHIVE = DATA / "official-ir-pdfs-live-test"
LITERATURE_DB = DATA / "literature_models" / "literature_inputs.sqlite3"
VIEWS = {
    "overview": ["營收與應收帳款成長背離（F1）", "28.89", "需要補件確認", "MOPS 財報", "mops_t164sb01:2025:S4:C",
                 "未記錄（缺 source_sha256", "營業現金流低於淨利本身不是異常判定"],
    "models": ["Beneish (1999) M-Score", "Dechow, Ge, Larson &amp; Sloan (2011)", "無（不可計算）",
               "no_frozen_literature_inputs_for_ticker", "DRAFT_PENDING_METHOD_OWNER_REVIEW"],
    "cross": ["Net Sales 530,586 433,446 22.4%", "Net income 107,141 77,191 38.8%", "同一發行人自報", "0.078121",
              "0.944793", "未校準：不判定漂移等級", "c500c62f9450526f1db2a50c5790cc44e08ff51a67b0093686109ad00ce618fe"],
    "b2b": ["應收帳款帳齡表", "不估計停供或供應鏈中斷機率", "會計師查核報告"],
}
PATH_PATTERN = re.compile(r"[A-Za-z]:\\\\|/Users/|\\\\data\\\\|official-ir-pdfs|\.sqlite3")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", default=next((b for b in BROWSERS if Path(b).is_file()), None))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    sources_before = {str(p.relative_to(BACKEND)): sha(p) for p in (PIPELINE_DB, LITERATURE_DB)}
    scratch = Path(tempfile.mkdtemp(prefix="integrity-smoke-"))
    copy = scratch / "pipeline_copy.sqlite3"
    shutil.copyfile(PIPELINE_DB, copy)
    copy_matches = sha(copy) == sources_before[str(PIPELINE_DB.relative_to(BACKEND))]
    api_port, web_port = free_port(), free_port()
    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8",
           "DATASTORE_BACKEND": "sqlite", "FINANCIAL_DATABASE_PATH": str(copy),
           "FINANCIAL_FACT_DATABASE_PATH": str(scratch / "facts.sqlite3"),
           "CONFERENCE_PDF_ARCHIVE_BACKEND": "file", "CONFERENCE_PDF_ARCHIVE_ROOT": str(ARCHIVE),
           "JSD_CALIBRATION_BACKEND": "json", "LITERATURE_INPUTS_DATABASE_PATH": str(LITERATURE_DB),
           "FLASK_DATASTORE_BACKEND": "sqlite", "FLASK_DATABASE_PATH": str(scratch / "flask.sqlite3"),
           "ALLOW_DEMO_SEED_DATA": "false", "FINTRUST_API_BASE_URL": f"http://127.0.0.1:{api_port}",
           "RESEARCH_RESULTS_DATABASE_PATH": str(scratch / "research_results.sqlite3"),
           "FINANCIAL_LLM_PROVIDER": "", "CONFERENCE_DIGEST_LLM_PROVIDER": "", "TEXT_EMBEDDING_PROVIDER": "",
           "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": "", "INGESTION_API_TOKEN": ""}
    logs = {name: (scratch / f"{name}.log").open("w", encoding="utf-8") for name in ("fastapi", "flask")}
    processes = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                         cwd=BACKEND, env=env, stdout=logs["fastapi"], stderr=subprocess.STDOUT),
        subprocess.Popen([sys.executable, "-c", f"import app; app.app.run(host='127.0.0.1', port={web_port}, debug=False)"],
                         cwd=REPO, env=env, stdout=logs["flask"], stderr=subprocess.STDOUT),
    ]
    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "fastapi_port": api_port,
                    "flask_port": web_port, "http": {}, "views": {}, "browser": args.browser,
                    "served_from": "SHA-verified byte-identical scratch copy of fintrust_backend/data/financial_pipeline.sqlite3",
                    "copy_matched_original_before_start": copy_matches, "sources_before": sources_before}
    outputs: dict = {}
    try:
        wait(f"http://127.0.0.1:{api_port}/health")
        wait(f"http://127.0.0.1:{web_port}/health")
        web, api = f"http://127.0.0.1:{web_port}", f"http://127.0.0.1:{api_port}"
        body = lambda **kw: json.dumps(kw).encode()  # noqa: E731
        checks = {
            "flask_companies": get(f"{web}/api/integrity/companies"),
            "flask_readiness_2454": get(f"{web}/api/integrity/companies/2454/readiness"),
            "flask_preview_2454": get(f"{web}/api/integrity/assessments/preview", body(ticker="2454")),
            "flask_preview_2330": get(f"{web}/api/integrity/assessments/preview", body(ticker="2330")),
            "flask_preview_3711_no_snapshot": get(f"{web}/api/integrity/assessments/preview", body(ticker="3711")),
            "fastapi_direct_preview_2454": get(f"{api}/api/v1/integrity/assessments/preview", body(ticker="2454")),
            "flask_persist_true_refused": get(f"{web}/api/integrity/assessments/preview", body(ticker="2454", persist=True)),
            "fastapi_persist_true_refused": get(f"{api}/api/v1/integrity/assessments/preview", body(ticker="2454", persist=True)),
            "flask_strict_refused": get(f"{web}/api/integrity/assessments/preview",
                                        body(ticker="2454", review_mode="STRICT_AS_OF")),
            "flask_research_case_ticker_refused": get(f"{web}/api/integrity/assessments/preview", body(ticker="1785")),
            "existing_flask_health": get(f"{web}/health"),
            "existing_fastapi_health": get(f"{api}/health"),
            "existing_research_cases": get(f"{web}/api/research/cases"),
        }
        expected = {"flask_persist_true_refused": 400, "fastapi_persist_true_refused": 422, "flask_strict_refused": 409,
                    "flask_research_case_ticker_refused": 404}
        for name, (status, _payload) in checks.items():
            report["http"][name] = {"status": status, "ok": status == expected.get(name, 200)}
        proxied, direct = checks["flask_preview_2454"][1]["data"], checks["fastapi_direct_preview_2454"][1]
        report["http"]["proxy_parity_2454"] = {"ok": all(proxied[k] == direct[k] for k in (
            "financial_findings", "claim_checks", "paper_models", "data_shift", "investigation_priority", "evidence_records"))}
        no_snapshot = checks["flask_preview_3711_no_snapshot"][1]["data"]
        report["http"]["no_data_company_fails_closed"] = {
            "ok": no_snapshot["investigation_priority"]["queue"] == "insufficient_evidence"
            and no_snapshot["financial_overview"]["rows"] == [],
            "queue": no_snapshot["investigation_priority"]["queue"]}
        for ticker in ("2454", "2330", "3711_no_snapshot"):
            outputs[ticker] = checks[f"flask_preview_{ticker}"][1]["data"]
        outputs["companies"] = checks["flask_companies"][1]["data"]
        outputs["readiness_2454"] = checks["flask_readiness_2454"][1]["data"]
        serialized = json.dumps(outputs, ensure_ascii=False)
        leaks = sorted(set(PATH_PATTERN.findall(serialized)))
        report["http"]["no_filesystem_paths_in_outputs"] = {"ok": not leaks, "matches": leaks}
        if args.browser:
            profile = scratch / "browser-profile"
            for view, needles in VIEWS.items():
                url = f"{web}/financial-integrity.html?ticker=2454&expand=1#{view}"
                base = [args.browser, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
                        f"--user-data-dir={profile}", "--window-size=1366,3000", "--virtual-time-budget=25000",
                        "--hide-scrollbars"]
                png = (args.out / f"integrity_2454_{view}.png").resolve()
                subprocess.run(base + [f"--screenshot={png}", url], capture_output=True, timeout=180, check=False)
                dom = subprocess.run(base + ["--dump-dom", url], capture_output=True, timeout=180, check=False)
                html = dom.stdout.decode("utf-8", errors="replace")
                (args.out / f"integrity_2454_{view}.dom.html").write_text(html, encoding="utf-8")
                missing = [n for n in needles if n not in html]
                report["views"][view] = {
                    "url": url.replace(web, "http://127.0.0.1:<flask>"),
                    "screenshot": png.name if png.is_file() else None,
                    "screenshot_sha256": sha(png) if png.is_file() else None,
                    "screenshot_bytes": png.stat().st_size if png.is_file() else 0,
                    "dom_bytes": len(html), "missing_strings": missing, "ok": png.is_file() and not missing}
        else:
            report["views"] = {"skipped": "no Chromium-based browser found; pass --browser"}
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
        for handle in logs.values():
            handle.close()
        shutil.rmtree(scratch, ignore_errors=True)
    report["sources_after"] = {str(p.relative_to(BACKEND)): sha(p) for p in (PIPELINE_DB, LITERATURE_DB)}
    report["http"]["approved_sources_unchanged"] = {"ok": report["sources_after"] == sources_before and copy_matches}
    report["ok"] = all(v.get("ok") for v in report["http"].values()) and all(
        v.get("ok") for v in report["views"].values() if isinstance(v, dict))
    if outputs:
        (args.out / "integrity_phase1_real_outputs.json").write_text(json.dumps({
            "note": "Sanitized real read-only outputs (Flask proxy responses). Official URLs only; no filesystem paths.",
            "command": "cd fintrust_backend && python -m scripts.integrity_phase1_smoke --out <dir>",
            "source_digests": sources_before, "archive_documents_used": "pinned SHA-256 in each claim_checks[].statement",
            "outputs": outputs}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (args.out / "integrity_smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
