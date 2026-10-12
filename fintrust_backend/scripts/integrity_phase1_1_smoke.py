"""Phase 1.1 E2E smoke on genuine local data: FastAPI + Flask processes, Flask proxy, headless browser.

    python -m scripts.integrity_phase1_1_smoke --out <dir> [--browser <chrome/edge exe>]

Covers the hardened CURRENT_REVIEW workbench (2454) and the new read-only RETROSPECTIVE_CASE view (1785, both
version series). The pipeline database is served from a SHA-verified scratch copy; the historical audit archive and
literature inputs are opened read-only by the existing research layer. Every approved store's SHA-256 is recorded
before and after. No network beyond 127.0.0.1, no cloud, no LLM, no live MOPS fetch, nothing persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.integrity_phase1_smoke import ARCHIVE, LITERATURE_DB, PATH_PATTERN, PIPELINE_DB
from scripts.research_ui_smoke import BROWSERS, free_port, get, wait

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DATA = BACKEND / "data"
STORES = [PIPELINE_DB, LITERATURE_DB, DATA / "historical_audit" / "historical_audit.sqlite3",
          DATA / "historical_audit" / "research_results.sqlite3"]
VIEWS = {
    "workbench_2454_overview": ("financial-integrity.html?ticker=2454&expand=1#overview",
                                ["營收與應收帳款成長背離（F1）", "28.89", "需要補件確認", "最新年度不可計算的檢查 0 項"]),
    "workbench_2454_cross": ("financial-integrity.html?ticker=2454&expand=1#cross",
                             ["Net Sales 530,586 433,446 22.4%", "同一發行人自報", "未校準：不判定漂移等級"]),
    "case_1785_latest": ("financial-integrity-case.html?version_policy=latest_available&variable=TATA",
                         ["事後研究／包含後續申報版本，不代表事件曝光前可用資訊", "rrun1_3aee901dc66e02346710d41e9fd0bc02",
                          "一致：26／34、run id 相同", "23 已計算／7 不可計算", "待來源驗證（未進入計算）",
                          "實體資產事件（黃金不法轉出）", "官方原文已驗證（E2）",
                          "事件公開前（2016-05-13 截點）沒有任何可驗證的文獻模型分數", "凍結輸入無此科目"]),
    "case_1785_original_fy2012": ("financial-integrity-case.html?version_policy=original_only&variable=ch_inv"
                                  "&cell=dechow_2011_model1_v1:2012",
                                  ["rrun1_2120551b6b6763dd65b49439602a28f4", "0.892005", "verified_zero",
                                   "3 已計算／27 不可計算", "原始申報"]),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", default=next((b for b in BROWSERS if Path(b).is_file()), None))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    before = {str(p.relative_to(BACKEND)): sha(p) for p in STORES if p.is_file()}
    scratch = Path(tempfile.mkdtemp(prefix="integrity11-smoke-"))
    copy = scratch / "pipeline_copy.sqlite3"
    shutil.copyfile(PIPELINE_DB, copy)
    copy_matches = sha(copy) == before[str(PIPELINE_DB.relative_to(BACKEND))]
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
    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "fastapi_port": api_port, "flask_port": web_port,
                    "http": {}, "views": {}, "browser": args.browser, "copy_matched_original_before_start": copy_matches,
                    "sources_before": before}
    outputs: dict = {}
    try:
        wait(f"http://127.0.0.1:{api_port}/health")
        wait(f"http://127.0.0.1:{web_port}/health")
        web, api = f"http://127.0.0.1:{web_port}", f"http://127.0.0.1:{api_port}"
        case = "/research-cases/1785/summary?version_policy="
        checks = {
            "flask_case_latest": get(f"{web}/api/integrity{case}latest_available"),
            "flask_case_original": get(f"{web}/api/integrity{case}original_only"),
            "fastapi_case_original": get(f"{api}/api/v1/integrity{case}original_only"),
            "flask_case_2454_refused": get(f"{web}/api/integrity/research-cases/2454/summary?version_policy=latest_available"),
            "flask_case_missing_policy": get(f"{web}/api/integrity/research-cases/1785/summary"),
            "fastapi_case_missing_policy": get(f"{api}/api/v1/integrity/research-cases/1785/summary"),
            "flask_current_review_1785_refused": get(f"{web}/api/integrity/assessments/preview",
                                                     json.dumps({"ticker": "1785"}).encode()),
            "flask_preview_2454": get(f"{web}/api/integrity/assessments/preview", json.dumps({"ticker": "2454"}).encode()),
            "existing_research_cases": get(f"{web}/api/research/cases"),
            "existing_flask_health": get(f"{web}/health"),
        }
        expected = {"flask_case_2454_refused": 404, "flask_case_missing_policy": 400, "fastapi_case_missing_policy": 422,
                    "flask_current_review_1785_refused": 404}
        for name, (status, _payload) in checks.items():
            report["http"][name] = {"status": status, "ok": status == expected.get(name, 200)}
        latest, original = checks["flask_case_latest"][1]["data"], checks["flask_case_original"][1]["data"]
        direct = checks["fastapi_case_original"][1]
        report["http"]["case_proxy_parity"] = {"ok": original["dataset_identity"] == direct["dataset_identity"]
                                               and original["cells"] == direct["cells"]}
        report["http"]["case_baseline_matches_accepted"] = {
            "ok": latest["baseline_check"]["matches"] and original["baseline_check"]["matches"],
            "observed": latest["baseline_check"]["observed"], "run_ids": {
                "latest_available": latest["dataset_identity"]["run_id"], "original_only": original["dataset_identity"]["run_id"]}}
        report["http"]["case_mode_separation"] = {"ok": latest["review_mode"] == "RETROSPECTIVE_CASE"
                                                  and latest["hindsight"] is True and latest["persist"] is False
                                                  and checks["flask_preview_2454"][1]["data"]["review_mode"] == "CURRENT_REVIEW"}
        report["http"]["case_strict_pre_event_no_score"] = {
            "ok": latest["strict_pre_event"]["status"] == "insufficient_point_in_time_evidence",
            "status": latest["strict_pre_event"]["status"]}
        report["http"]["case_event_statuses"] = {"ok": True, "statuses": {e["event_id"]: e["verification_status"]
                                                                        for e in latest["events"]}}
        outputs = {"case_1785_latest_available": latest, "case_1785_original_only": original,
                   "workbench_2454": checks["flask_preview_2454"][1]["data"]}
        leaks = sorted(set(PATH_PATTERN.findall(json.dumps(outputs, ensure_ascii=False))))
        report["http"]["no_filesystem_paths_in_outputs"] = {"ok": not leaks, "matches": leaks}
        if args.browser:
            profile = scratch / "browser-profile"
            for view, (path, needles) in VIEWS.items():
                url = f"{web}/{path}"
                base = [args.browser, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
                        f"--user-data-dir={profile}", "--window-size=1366,3600", "--virtual-time-budget=30000",
                        "--hide-scrollbars"]
                png = (args.out / f"{view}.png").resolve()
                subprocess.run(base + [f"--screenshot={png}", url], capture_output=True, timeout=180, check=False)
                dom = subprocess.run(base + ["--dump-dom", url], capture_output=True, timeout=180, check=False)
                html = dom.stdout.decode("utf-8", errors="replace")
                (args.out / f"{view}.dom.html").write_text(html, encoding="utf-8")
                missing = [n for n in needles if n not in html]
                report["views"][view] = {"url": f"http://127.0.0.1:<flask>/{path}",
                                         "screenshot": png.name if png.is_file() else None,
                                         "screenshot_sha256": sha(png) if png.is_file() else None,
                                         "screenshot_bytes": png.stat().st_size if png.is_file() else 0,
                                         "dom_bytes": len(html), "missing_strings": missing,
                                         "ok": png.is_file() and not missing}
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
    report["sources_after"] = {str(p.relative_to(BACKEND)): sha(p) for p in STORES if p.is_file()}
    report["http"]["approved_sources_unchanged"] = {"ok": report["sources_after"] == before and copy_matches}
    report["ok"] = all(v.get("ok") for v in report["http"].values()) and all(
        v.get("ok") for v in report["views"].values() if isinstance(v, dict))
    if outputs:
        (args.out / "integrity_phase1_1_real_outputs.json").write_text(json.dumps({
            "note": "Sanitized real read-only outputs (Flask proxy responses). Official URLs only; no filesystem paths. "
                    "The 1785 case view is RETROSPECTIVE_CASE (hindsight), never a current review or a prediction.",
            "command": "cd fintrust_backend && python -m scripts.integrity_phase1_1_smoke --out <dir>",
            "source_digests": before, "outputs": outputs}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (args.out / "integrity_smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                          encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
