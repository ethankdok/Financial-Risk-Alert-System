import csv
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.routers.provider_review import (
    FOLDER,
    REVIEWS,
    load_data,
    load_reviews,
    save_reviews,
)

router = APIRouter(tags=["research-batch-review"])

AUDIT = FOLDER / "tsmc_review_audit.csv"


def esc(value):
    return escape(str(value), quote=True)


def pending_groups():
    items = load_data()
    reviews = load_reviews()
    groups = {}

    for evidence_id, item in items.items():
        status = reviews.get(
            evidence_id, {}
        ).get("status", "PENDING")

        if status != "PENDING":
            continue

        key = (
            item.get("sha256", ""),
            str(item.get("page", ""))
        )
        groups.setdefault(key, []).append(
            (evidence_id, item)
        )

    return groups


def html_page(content):
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>FinTrust 批次人工審查</title>
<style>
body {
    font-family: Arial, sans-serif;
    max-width: 980px;
    margin: 35px auto;
    padding: 20px;
    color: #20314b;
    background: #f4f7fc;
}
.card {
    background: white;
    border-radius: 12px;
    padding: 22px;
    margin: 16px 0;
}
.item {
    border-bottom: 1px solid #ddd;
    padding: 16px 0;
}
.excerpt {
    background: #f1f5f9;
    padding: 12px;
    line-height: 1.8;
    overflow-wrap: anywhere;
}
input[type=text] {
    padding: 12px;
    width: 95%;
}
button {
    background: #245fc0;
    color: white;
    padding: 12px 20px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
}
a { color: #245fc0; }
</style>
</head>
<body>
""" + content + "</body></html>")


@router.get("/research-batch-review")
def batch_list():
    groups = pending_groups()
    body = (
        '<a href="/research-review">返回人工審查</a>'
        "<h1>同頁批次人工審查</h1>"
        "<p>尚待審查的文件頁面："
        + str(len(groups)) + "</p>"
    )

    for (sha, page), items in list(groups.items())[:30]:
        first = items[0][1]

        body += (
            '<section class="card">'
            "<h3>" + esc(first.get("period", ""))
            + "｜第 " + esc(page) + " 頁</h3>"
            "<p>待確認證據：" + str(len(items)) + " 筆</p>"
            '<a href="/research-batch-review/'
            + esc(sha) + "/" + esc(page)
            + '">開始核對這一頁</a>'
            "</section>"
        )

    return html_page(body)


def group_items(sha, page):
    return pending_groups().get(
        (sha, str(page)), []
    )


@router.get("/research-batch-review/{sha}/{page}")
def batch_form(sha: str, page: int):
    items = group_items(sha, page)

    if not items:
        raise HTTPException(404, "沒有待審查證據")

    first = items[0][1]
    url = str(first.get("source_url", ""))
    parsed = urlparse(url)

    body = (
        '<a href="/research-batch-review">返回分組列表</a>'
        "<h1>同頁證據核對</h1>"
        "<h2>" + esc(first.get("period", ""))
        + "｜第 " + esc(page) + " 頁</h2>"
        "<p>請先開啟官方 PDF，逐筆核對。</p>"
    )

    if (
        parsed.scheme == "https"
        and parsed.hostname == "investor.tsmc.com"
    ):
        body += (
            '<a target="_blank" rel="noopener noreferrer" href="'
            + esc(url) + '">開啟官方 PDF</a>'
        )

    body += '<form method="post" class="card">'

    # 每次最多顯示 25 筆，剩餘紀錄下次處理
    for evidence_id, item in items[:25]:
        body += (
            '<div class="item">'
            '<label><input type="checkbox" name="selected" value="'
            + esc(evidence_id) + '">'
            " 已逐筆確認此證據</label>"
            "<p>詞彙：" + esc(item.get("term", "")) + "</p>"
            '<div class="excerpt">'
            + esc(item.get("snippet", ""))
            + "</div></div>"
        )

    body += """
<p><strong>只有確實核對的證據才能勾選。</strong></p>
<label>核對人</label>
<input type="text" name="reviewer"
       required maxlength="100">

<p>
<label>
<input type="checkbox" name="pdf_checked" value="yes" required>
我已開啟 PDF，逐筆核對所勾選的原文及頁碼。
</label>
</p>

<button type="submit">儲存已勾選的證據</button>
</form>
"""
    return html_page(body)


@router.post("/research-batch-review/{sha}/{page}")
def submit_batch(
    sha: str,
    page: int,
    reviewer: str = Form(...),
    selected: list[str] = Form(default=[]),
    pdf_checked: str = Form("")
):
    reviewer = reviewer.strip()

    if not reviewer or len(reviewer) > 100:
        raise HTTPException(400, "核對人格式錯誤")

    if pdf_checked != "yes":
        raise HTTPException(400, "請確認已實際核對 PDF")

    allowed = {
        evidence_id
        for evidence_id, _ in group_items(sha, page)[:25]
    }

    chosen = set(selected)

    if not chosen or not chosen.issubset(allowed):
        raise HTTPException(
            400, "沒有選取證據或包含無效證據"
        )

    records = load_reviews()
    now = datetime.now(timezone.utc).isoformat()

    # 先備份，再修改
    backup = REVIEWS.with_suffix(".before_batch.bak")
    if not backup.exists():
        import shutil
        shutil.copy2(REVIEWS, backup)

    for evidence_id in chosen:
        records[evidence_id] = {
            "evidence_id": evidence_id,
            "status": "CONFIRMED",
            "reviewer": reviewer,
            "reviewed_at": now,
            "notes": "批次審查：已逐筆核對 PDF 原文及頁碼"
        }

    save_reviews(records)

    # 保留操作紀錄
    fields = [
        "evidence_id", "action", "reviewer",
        "reviewed_at", "sha256", "page"
    ]

    new_file = not AUDIT.exists()

    with AUDIT.open(
        "a", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=fields
        )

        if new_file:
            writer.writeheader()

        for evidence_id in sorted(chosen):
            writer.writerow({
                "evidence_id": evidence_id,
                "action": "CONFIRMED",
                "reviewer": reviewer,
                "reviewed_at": now,
                "sha256": sha,
                "page": page
            })

        f.flush()
        os.fsync(f.fileno())

    return RedirectResponse(
        "/research-batch-review",
        status_code=303
    )
