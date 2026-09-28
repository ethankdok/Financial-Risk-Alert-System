from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
RESULTS = BACKEND / "data" / "research-results"
DATABASE = RESULTS / "research_snapshots.sqlite3"

API = "/api/v1/financial/research-validation/comparison"

REQUIRED_FILES = [
    "tsmc_history.json",
    "mediatek_history.json",
]

OPTIONAL_FILES = [
    "tsmc_cleaned_tfidf.json",
    "mediatek_tfidf_validation.json",
]

EXPECTED_COMPANIES = {"TSMC", "MediaTek"}


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def collect_sources():
    sources = []

    for filename in REQUIRED_FILES + OPTIONAL_FILES:
        path = RESULTS / filename

        if not path.is_file():
            if filename in REQUIRED_FILES:
                raise FileNotFoundError(
                    f"缺少必要研究資料：{path}"
                )
            continue

        content = path.read_bytes()

        # 確認原始研究 JSON 可以解析
        json.loads(content.decode("utf-8"))

        sources.append({
            "filename": filename,
            "sha256": sha256(content),
            "size": len(content),
        })

    return sources


def collect_api_results():
    client = TestClient(app)

    response = client.get(API)

    if response.status_code != 200:
        raise RuntimeError(
            f"研究 API 失敗："
            f"HTTP {response.status_code}\n"
            f"{response.text[:1500]}"
        )

    result = response.json()
    companies = result.get("companies", [])

    if len(companies) != 2:
        raise RuntimeError(
            f"預期兩家公司，實際取得 {len(companies)} 家"
        )

    names = [item.get("company") for item in companies]

    if set(names) != EXPECTED_COMPANIES:
        raise RuntimeError(
            f"公司清單不符：{names}"
        )

    if len(set(names)) != 2:
        raise RuntimeError("公司資料重複")

    for item in companies:
        name = item["company"]
        rows = item.get("comparisons", [])

        if len(rows) != 7:
            raise RuntimeError(
                f"{name} 應有 7 組，"
                f"實際取得 {len(rows)} 組"
            )

        if item.get("status") != "EXPLORATORY_ONLY":
            raise RuntimeError(
                f"{name} 研究狀態不符合預期"
            )

    return sorted(
        companies,
        key=lambda item: item["company"],
    )


def initialize_database(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS research_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            method_status TEXT NOT NULL,
            company_count INTEGER NOT NULL,
            comparison_count INTEGER NOT NULL,
            sources_json TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS research_company_results (
            snapshot_id TEXT NOT NULL,
            company TEXT NOT NULL,
            status TEXT NOT NULL,
            comparison_count INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            PRIMARY KEY (snapshot_id, company),
            FOREIGN KEY (snapshot_id)
                REFERENCES research_snapshots(snapshot_id)
        )
    """)


def main():
    print("=== FinTrust 研究資料庫整合 ===")

    RESULTS.mkdir(parents=True, exist_ok=True)

    # 先確認 API 和研究來源
    sources = collect_sources()
    companies = collect_api_results()

    total = sum(
        len(company["comparisons"])
        for company in companies
    )

    # 以資料內容和來源版本產生固定 ID
    payload = {
        "sources": sources,
        "companies": companies,
        "status": "EXPLORATORY_ONLY",
    }

    snapshot_id = sha256(
        canonical_json(payload).encode("utf-8")
    )

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

    with sqlite3.connect(DATABASE) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        initialize_database(connection)

        # 所有寫入都在同一筆交易中
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            """
            SELECT snapshot_id
            FROM research_snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()

        if existing is None:
            connection.execute(
                """
                INSERT INTO research_snapshots (
                    snapshot_id,
                    created_at,
                    method_status,
                    company_count,
                    comparison_count,
                    sources_json,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    created_at,
                    "EXPLORATORY_ONLY",
                    len(companies),
                    total,
                    canonical_json(sources),
                    canonical_json(payload),
                ),
            )

            for company in companies:
                connection.execute(
                    """
                    INSERT INTO research_company_results (
                        snapshot_id,
                        company,
                        status,
                        comparison_count,
                        result_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        company["company"],
                        company["status"],
                        len(company["comparisons"]),
                        canonical_json(company),
                    ),
                )

            print("新增研究資料版本")
        else:
            print("相同研究版本已存在，不重複新增")

        connection.commit()

        # 寫入後重新從資料庫讀取
        saved = connection.execute(
            """
            SELECT company, comparison_count, result_json
            FROM research_company_results
            WHERE snapshot_id = ?
            ORDER BY company
            """,
            (snapshot_id,),
        ).fetchall()

        if len(saved) != 2:
            raise RuntimeError(
                "資料庫驗證失敗：公司數量不正確"
            )

        saved_total = 0

        print("\n=== 資料庫讀取驗證 ===")

        for name, count, raw_json in saved:
            stored = json.loads(raw_json)
            saved_total += count

            original = next(
                company
                for company in companies
                if company["company"] == name
            )

            if stored != original:
                raise RuntimeError(
                    f"{name} 儲存內容與 API 不一致"
                )

            if count != len(stored["comparisons"]):
                raise RuntimeError(
                    f"{name} 比較組數不一致"
                )

            print(
                f"{name}: {count} 組，"
                f"狀態 {stored['status']}"
            )

        if saved_total != 14:
            raise RuntimeError(
                f"預期 14 組，實際 {saved_total} 組"
            )

        print("\n資料庫驗證成功")
        print("公司數量:", len(saved))
        print("比較總數:", saved_total)
        print("來源文件數:", len(sources))
        print("版本 ID:", snapshot_id)
        print("資料庫:", DATABASE)
        print("研究狀態: EXPLORATORY_ONLY")


if __name__ == "__main__":
    main()
