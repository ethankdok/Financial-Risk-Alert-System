
import csv
import hashlib
import json
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["research-evidence"])

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "data/research-results"


def get_id(item):
    fields = [
        str(item.get(k, ""))
        for k in (
            "sha256", "period", "term",
            "page", "snippet"
        )
    ]
    return hashlib.sha256(
        "\n".join(fields).encode("utf-8")
    ).hexdigest()[:20]


@router.get(
    "/research-provider-excerpts",
    response_class=HTMLResponse
)
def provider_excerpts(
    period: str = "",
    offset: int = Query(0, ge=0)
):
    data = json.loads(
        (FOLDER / "tsmc_provider_evidence.json")
        .read_text(encoding="utf-8")
    )
    items = data.get("evidence", [])

    reviews = {}
    review_path = FOLDER / "tsmc_evidence_reviews.csv"

    if review_path.exists():
        with review_path.open(
            encoding="utf-8-sig", newline=""
        ) as f:
            reviews = {
                row["evidence_id"]: row
                for row in csv.DictReader(f)
            }

    if period in ("2025Q3", "2025Q4"):
        items = [
            item for item in items
            if item.get("period") == period
        ]
    else:
        period = ""

    total = len(items)
    items = items[offset:offset + 20]

    def safe(value):
        return escape(str(value), quote=True)

    page = """
    <!doctype html>
    <html lang="zh-Hant">
    <head>
    <meta charset="utf-8">
    <meta name="viewport"
          content="width=device-width,initial-scale=1">
    <title>FinTrust 原文證據</title>
    <style>
    body{font-family:Arial,sans-serif;
         background:#f4f7fc;color:#20314b;
         margin:30px auto;padding:0 18px;
         max-width:1050px}
    .card{background:white;padding:24px;
          border-radius:12px;margin:18px 0}
    .pending{color:#b7791f}
    .confirmed{color:#16803c}
    .rejected{color:#c53030}
    .excerpt{background:#f3f6fa;padding:15px;
             border-radius:8px;line-height:1.8;
             overflow-wrap:anywhere}
    a{color:#245fc0}
    .button{display:inline-block;padding:10px;
            margin:5px;border:1px solid #ddd;
            border-radius:8px;text-decoration:none}
    </style>
    </head>
    <body>
    <a href="/research-provider-evidence">
    返回供應商實驗
    </a>
    <h1>台積電原始文字證據</h1>
    <p>頁碼依文字檔標記，尚須與 PDF 人工核對。</p>
    """

    for value, label in [
        ("", "全部"),
        ("2025Q3", "2025Q3"),
        ("2025Q4", "2025Q4")
    ]:
        page += (
            '<a class="button" href="?period='
            + value + '">' + label + "</a>"
        )

    page += "<p>符合條件的證據：" + str(total) + "</p>"

    for item in items:
        key = get_id(item)
        review = reviews.get(key, {})
        status = review.get("status", "PENDING")
        if status not in ("PENDING", "CONFIRMED", "REJECTED"):
            status = "PENDING"

        url = str(item.get("source_url", ""))
        parsed = urlparse(url)

        # 僅產生台積電官方網站的外部連結
        official = (
            parsed.scheme == "https"
            and parsed.hostname == "investor.tsmc.com"
        )

        page += '<section class="card">'
        page += "<h2>" + safe(item.get("period", "")) + "</h2>"
        page += "<p>詞彙：" + safe(item.get("term", "")) + "</p>"
        page += "<p>文字標記頁碼：" + safe(
            item.get("page", "")
        ) + "</p>"
        page += '<div class="excerpt">' + safe(
            item.get("snippet", "")
        ) + "</div>"
        page += "<p>證據 ID：" + safe(key) + "</p>"
        page += '<p class="' + {
            "PENDING": "pending",
            "CONFIRMED": "confirmed",
            "REJECTED": "rejected"
        }[status] + '">核對狀態：' + status + "</p>"

        if official:
            page += (
                '<a target="_blank" rel="noopener noreferrer" href="'
                + safe(url) + '">開啟官方原始文件</a>'
            )

        page += "</section>"

    page += '<div class="card">'

    if offset > 0:
        page += (
            '<a class="button" href="?period=' + period
            + '&offset=' + str(max(0, offset - 20))
            + '">上一頁</a>'
        )

    if offset + 20 < total:
        page += (
            '<a class="button" href="?period=' + period
            + '&offset=' + str(offset + 20)
            + '">下一頁</a>'
        )

    page += "</div></body></html>"
    return HTMLResponse(page)
