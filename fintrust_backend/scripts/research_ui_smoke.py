"""Local E2E smoke: real FastAPI + Flask dev processes, HTTP through the Flask proxy, headless-browser rendering.

    python -m scripts.research_ui_smoke --out <dir> [--browser <chrome/edge exe>]

- FastAPI (uvicorn) and Flask run as separate local processes on 127.0.0.1 with isolated scratch databases for
  their production stores (``FINANCIAL_DATABASE_PATH``, ``FINANCIAL_FACT_DATABASE_PATH``, ``FLASK_DATABASE_PATH``);
  the research API opens the approved historical archive read-only.
- Every request goes over real localhost HTTP through the Flask research proxy.
- With a Chromium-based browser, each of the six research views is rendered headless: a PNG screenshot and the
  rendered DOM are saved, and the DOM is checked for the key evidence strings.

No network beyond 127.0.0.1, no cloud, no LLM, no writes to the approved archive or the existing local databases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
VIEWS = {
    "overview": ["光洋科", "production_universe=false", "234", "67", "158"],
    "bridge": ["依 2016 年 11 月公告回溯重述", "967,367 千元", "TW-GAAP", "TIFRS"],
    "timeline": ["STRICT_AS_OF", "E1_official_listing_metadata", "僅官方清單"],
    "signals": ["目前缺乏可核驗的事件前財務輸入", "NOT_COMPUTABLE"],
    "discrepancy": ["1,721 千元", "34,436,171 千元", "34,434,450 千元", "第 8 頁", "來源數值差異待查證"],
    "text": ["NOT_APPLICABLE", "1190／1139", "NOT_READY"],
}
BROWSERS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - localhost only
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not become healthy")


def get(url: str, data: bytes | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - localhost only
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", default=next((b for b in BROWSERS if Path(b).is_file()), None))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="research-smoke-"))
    api_port, web_port = free_port(), free_port()
    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8",
           "DATASTORE_BACKEND": "sqlite", "FINANCIAL_DATABASE_PATH": str(scratch / "pipeline.sqlite3"),
           "FINANCIAL_FACT_DATABASE_PATH": str(scratch / "facts.sqlite3"),
           "FLASK_DATASTORE_BACKEND": "sqlite", "FLASK_DATABASE_PATH": str(scratch / "flask.sqlite3"),
           "ALLOW_DEMO_SEED_DATA": "false", "FINTRUST_API_BASE_URL": f"http://127.0.0.1:{api_port}",
           "RESEARCH_RESULTS_DATABASE_PATH": str(BACKEND / "data" / "historical_audit" / "research_results.sqlite3"),
           "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": "", "INGESTION_API_TOKEN": ""}
    logs = {name: (scratch / f"{name}.log").open("w", encoding="utf-8") for name in ("fastapi", "flask")}
    processes = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                         cwd=BACKEND, env=env, stdout=logs["fastapi"], stderr=subprocess.STDOUT),
        subprocess.Popen([sys.executable, "-c", f"import app; app.app.run(host='127.0.0.1', port={web_port}, debug=False)"],
                         cwd=REPO, env=env, stdout=logs["flask"], stderr=subprocess.STDOUT),
    ]
    report: dict = {"fastapi_port": api_port, "flask_port": web_port, "http": {}, "views": {}, "browser": args.browser}
    try:
        wait(f"http://127.0.0.1:{api_port}/health")
        wait(f"http://127.0.0.1:{web_port}/health")
        web = f"http://127.0.0.1:{web_port}"
        checks = {
            "flask_cases": get(f"{web}/api/research/cases"),
            "flask_bridge": get(f"{web}/api/research/cases/1785/restatement-bridge?analysis_mode=RETROSPECTIVE_FORENSIC"),
            "flask_strict_without_cutoff": get(f"{web}/api/research/cases/1785/timeline?analysis_mode=STRICT_AS_OF"),
            "flask_production_ticker": get(f"{web}/api/research/cases/2330"),
            "flask_discrepancies": get(f"{web}/api/research/cases/1785/source-discrepancies?analysis_mode=CURRENT_EVIDENCE_RECONCILIATION"),
            "flask_compute_strict": get(f"{web}/api/research/financial-signals/compute", json.dumps({
                "ticker": "1785", "analysis_mode": "STRICT_AS_OF", "cutoff_at": "2016-05-13T00:00:00+08:00",
                "version_policy": "latest_available", "start_year": 2011, "end_year": 2016, "persist": True}).encode()),
            "fastapi_direct_bridge": get(f"http://127.0.0.1:{api_port}/api/v1/research/cases/1785/restatement-bridge?analysis_mode=RETROSPECTIVE_FORENSIC"),
            "existing_flask_health": get(f"{web}/health"),
            "existing_fastapi_health": get(f"http://127.0.0.1:{api_port}/health"),
        }
        expected = {"flask_strict_without_cutoff": 422, "flask_production_ticker": 404}
        for name, (status, _payload) in checks.items():
            report["http"][name] = {"status": status, "ok": status == expected.get(name, 200)}
        report["http"]["proxy_parity_bridge"] = {
            "ok": checks["flask_bridge"][1].get("data") == checks["fastapi_direct_bridge"][1]}
        report["http"]["browser_compute_not_persisted"] = {
            "ok": checks["flask_compute_strict"][1]["data"]["persisted"] is False,
            "status": checks["flask_compute_strict"][1]["data"]["result"]["status"]}
        if args.browser:
            profile = scratch / "browser-profile"
            for view, needles in VIEWS.items():
                url = f"{web}/historical-research.html#{view}"
                base = [args.browser, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
                        f"--user-data-dir={profile}", "--window-size=1366,2200", "--virtual-time-budget=20000",
                        "--hide-scrollbars"]
                png = (args.out / f"research_{view}.png").resolve()
                subprocess.run(base + [f"--screenshot={png}", url], capture_output=True, timeout=120, check=False)
                dom = subprocess.run(base + ["--dump-dom", url], capture_output=True, timeout=120, check=False)
                html = dom.stdout.decode("utf-8", errors="replace")
                (args.out / f"research_{view}.dom.html").write_text(html, encoding="utf-8")
                missing = [n for n in needles if n not in html]
                report["views"][view] = {
                    "screenshot": png.name if png.is_file() else None,
                    "screenshot_sha256": hashlib.sha256(png.read_bytes()).hexdigest() if png.is_file() else None,
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
    report["ok"] = all(v.get("ok") for v in report["http"].values()) and all(
        v.get("ok") for v in report["views"].values() if isinstance(v, dict))
    (args.out / "ui_smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
