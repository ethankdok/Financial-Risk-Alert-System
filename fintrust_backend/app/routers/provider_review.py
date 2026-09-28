import csv
import json
import os
import re
import tempfile

from datetime import datetime, timezone
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.routers.provider_excerpts import get_id

router = APIRouter(tags=["research-review"])

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "data/research-results"
EVIDENCE = FOLDER / "tsmc_provider_evidence.json"
REVIEWS = FOLDER / "tsmc_evidence_reviews.csv"

FIELDS = [
    "evidence_id", "status", "reviewer",
    "reviewed_at", "notes"
]

def esc(value):
    return escape(str(value), quote=True)

def load_data():
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    return {get_id(x): x for x in data["evidence"]}

def load_reviews():
    with REVIEWS.open(encoding="utf-8-sig", newline="") as f:
        return {x["evidence_id"]: x for x in csv.DictReader(f)}

def save_reviews(records):
    fd, temp = tempfile.mkstemp(dir=FOLDER, suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig",
                       newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records.values())
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, REVIEWS)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def layout(content):
    return HTMLResponse("""
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FinTrust 人工核對</title>
<style>
body{font-family:Arial,sans-serif;background:#f4f7fc;
     color:#20314b;max-width:900px;margin:35px auto;padding:18px}
section{background:white;padding:24px;border-radius:12px;
        margin:16px 0}
a{color:#245fc0}
input,select,textarea,button{display:block;margin:12px 0;
      padding:11px;box-sizing:border-box;max-width:100%;width:100%}
.excerpt{background:#f0f4fa;padding:15px;line-height:1.8;
         overflow-wrap:anywhere}
</style>
</head><body>
""" + content + "</body></html>")

@router.get("/research-review")
def review_list():
    items = load_data()
    reviews = load_reviews()

    pending = [
        key for key in items
        if reviews.get(key, {}).get("status", "PENDING")
        == "PENDING"
    ]

    confirmed = sum(
        r.get("status") == "CONFIRMED"
        for r in reviews.values()
    )
    rejected = sum(
        r.get("status") == "REJECTED"
        for r in reviews.values()
    )

    body = "<h1>FinTrust 人工審查</h1>"
    body += (
        f"<p>待確認：{len(pending)}"
        f"｜已確認：{confirmed}｜有誤：{rejected}</p>"
    )

    for key in pending[:20]:
        item = items[key]
        body += (
            "<section><p>"
            + esc(item["period"]) + "｜"
            + esc(item["term"]) + "｜第 "
            + esc(item["page"]) + " 頁</p>"
            + '<a href="/research-review/'
            + key + '">開啟人工核對</a></section>'
        )

    return layout(body)

@router.get("/research-review/{evidence_id}")
def review_form(evidence_id: str):
    items = load_data()
    if evidence_id not in items:
        raise HTTPException(404, "證據不存在")

    item = items[evidence_id]
    record = load_reviews().get(evidence_id, {})

    url = str(item.get("source_url", ""))
    # 僅允許已知的台積電官方來源
    from urllib.parse import urlparse
    parsed = urlparse(url)

    source_link = ""
    if parsed.scheme == "https" and parsed.hostname == "investor.tsmc.com":
        source_link = (
            '<p><a target="_blank" rel="noopener" href="'
            + esc(url) + '">開啟官方 PDF</a></p>'
        )

    body = (
        '<a href="/research-review">返回審查列表</a>'
        "<h1>人工核對</h1><section>"
        "<p>" + esc(item["period"]) + "｜"
        + esc(item["term"]) + "</p>"
        "<p>文字標記頁碼：" + esc(item["page"]) + "</p>"
        '<div class="excerpt">'
        + esc(item["snippet"]) + "</div>"
        + source_link
        + "<p>目前狀態："
        + esc(record.get("status", "PENDING")) + "</p>"
        '<form method="post">'
        '<label>核對人<input name="reviewer" required maxlength="100" value="'
        + esc(record.get("reviewer", "")) + '"></label>'
        '<label>核對結果<select name="status">'
        '<option value="PENDING">待確認</option>'
        '<option value="CONFIRMED">確認正確</option>'
        '<option value="REJECTED">標記有誤</option>'
        '</select></label>'
        '<label>備註<textarea name="notes" maxlength="3000">'
        + esc(record.get("notes", "")) + '</textarea></label>'
        '<p>標記有誤時必須填寫原因。</p>'
        '<button type="submit">儲存核對結果</button>'
        '</form></section>'
    )

    return layout(body)

@router.post("/research-review/{evidence_id}")
def submit_review(
    evidence_id: str,
    reviewer: str = Form(...),
    status: str = Form(...),
    notes: str = Form("")
):
    if evidence_id not in load_data():
        raise HTTPException(404, "證據不存在")

    reviewer = reviewer.strip()
    notes = notes.strip()

    if not reviewer or len(reviewer) > 100:
        raise HTTPException(400, "核對人格式錯誤")

    if status not in ("PENDING", "CONFIRMED", "REJECTED"):
        raise HTTPException(400, "審查狀態錯誤")

    if status == "REJECTED" and not notes:
        raise HTTPException(400, "請填寫錯誤原因")

    if len(notes) > 3000:
        raise HTTPException(400, "備註過長")

    records = load_reviews()
    records[evidence_id] = {
        "evidence_id": evidence_id,
        "status": status,
        "reviewer": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes
    }

    save_reviews(records)

    return RedirectResponse(
        "/research-review", status_code=303
    )
