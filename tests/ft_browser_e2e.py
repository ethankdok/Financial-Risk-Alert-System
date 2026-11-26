"""Real Chromium E2E against disposable Flask/FastAPI containers.

No production accounts, Firestore, or external news submissions.
The numerical claim test uses an explicitly synthetic fixture in isolated SQLite.
"""
import io
import json
import os
import re
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
import fitz
from openpyxl import Workbook
from docx import Document
from PIL import Image, ImageDraw, ImageFont

WEB = "http://127.0.0.1:18080"
API = "http://127.0.0.1:18081"
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = "FinTrust browser validation 2025"
def passed(label):
    print("PASS browser: " + label, flush=True)

def attach(page, name, mime, data, expected, timeout=60000):
    page.locator("#ft-query").fill("")
    page.locator("#ft-attach").set_input_files({"name":name,"mimeType":mime,"buffer":data})
    expect(page.locator("#ft-query")).to_have_value(re.compile(re.escape(expected), re.I), timeout=timeout)
    passed("file extraction " + name)

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(accept_downloads=True)
    page = ctx.new_page()
    page.set_default_timeout(25000)
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(WEB + "/")
    expect(page.locator("#ft-home-query")).to_be_visible()
    expect(page.locator("#ft-top-nav a")).to_have_count(4)
    assert "gradient" in page.locator("body").evaluate("(el)=>getComputedStyle(el).backgroundImage")
    assert page.locator(".ft-chat").evaluate("(el)=>getComputedStyle(el).backgroundColor") == "rgba(255, 255, 255, 0.82)"
    page.locator("#ft-home-query").fill("2330")
    page.locator("#ft-home-submit").click()
    expect(page).to_have_url(re.compile(r"financial-audit\.html\?ticker=2330"))
    expect(page.locator(".ft-snapshot-message")).to_be_visible()
    passed("homepage navigation and no invented snapshot for 2330")

    page.goto(WEB + "/financial-audit.html?ticker=6505")
    expect(page.locator(".ft-sheet-summary")).to_be_visible()
    snapshot = json.loads((ROOT/"ft-mops-data.json").read_text(encoding="utf-8"))
    company = next(group["6505"] for group in snapshot["industries"].values() if "6505" in group)
    for year in sorted(company["years"]):
        page.locator("#ft-year").select_option(year)
        for index, (model, key) in enumerate((("beneish","M_score"),("dechow","F_score"))):
            expected = company["years"][year][model].get(key)
            value = page.locator(".ft-sheet-stat strong").nth(index)
            expect(value).to_have_text("—" if expected is None else f"{expected:,.4f}")
    page.get_by_role("button", name="Beneish", exact=True).click()
    expect(page.locator(".ft-sheet-selectable")).to_have_count(8)
    page.locator(".ft-sheet-selectable").first.click()
    expect(page.locator("#ft-formula-details")).to_be_visible()
    page.get_by_role("button", name="Dechow", exact=True).click()
    expect(page.locator(".ft-sheet-selectable")).to_have_count(7)
    with page.expect_download() as download:
        page.get_by_role("button", name="下載目前表格 CSV").click()
    assert download.value.suggested_filename.endswith("_dechow.csv")
    page.get_by_role("button", name="官方來源", exact=True).click()
    expect(page.locator("#ft-sheet-body")).to_contain_text("原始檔名")
    passed("five-year snapshot scores, 8+7 formulas, CSV download and source panel")
    response=ctx.request.get(WEB+"/api/research/annual-model-results/6505/2025")
    assert response.ok and response.json()["data"]["record"]["beneish"]["M_score"]==company["years"]["2025"]["beneish"]["M_score"]
    assert ctx.request.get(WEB+"/api/research/annual-model-results/2330/2025").status==404
    passed("archived annual financial model backend output matches source snapshot")

    # Renderer-only JSD fixture: does not assert live official archive completeness.
    page.evaluate("""() => FTNarrative.renderFromCard(document.querySelector('#ft-narrative-health'),
      {company_name:'CI fixture', narrative_shift:{period_1:'2025Q1',period_2:'2025Q2',
      metrics:{relevant_text_word_jsd:0.123456,topic_distribution_jsd:0.045678},data_quality:{passed:true}}},'6505')""")
    expect(page.locator("#ft-narrative-health")).to_contain_text("0.123456")
    expect(page.locator("#ft-narrative-health")).to_contain_text("通過文字品質檢查")
    page.route("**/api/financial/companies/2330/**", lambda route: route.fulfill(status=503,content_type="application/json",body='{"success":false}'))
    page.locator("#ft-company-search").fill("2330")
    page.locator("#ft-company-suggestions [role=option]").first.click()
    expect(page.locator(".ft-snapshot-message")).to_be_visible()
    expect(page.locator("#ft-narrative-health")).to_contain_text("目前無法取得這家公司的文字比較結果")
    expect(page.locator("#ft-narrative-health")).not_to_contain_text("0.123456")
    page.unroute("**/api/financial/companies/2330/**")
    passed("JSD display and no stale previous-company values after a failed request")

    page.locator("#ft-language-toggle").click()
    expect(page.locator("h1")).to_have_text("Company health")
    page.locator("#ft-language-toggle").click()
    expect(page.locator("h1")).to_have_text("企業健檢")
    page.set_viewport_size({"width":390,"height":844})
    page.locator("#ft-menu-toggle").click()
    expect(page.locator("#ft-menu-toggle")).to_have_attribute("aria-expanded","true")
    page.keyboard.press("Escape")
    expect(page.locator("#ft-menu-toggle")).to_have_attribute("aria-expanded","false")
    page.set_viewport_size({"width":1280,"height":800})
    passed("Chinese/English and mobile menu")

    page.goto(WEB + "/analysis.html")
    page.locator("#ft-ticker").fill("2330")
    page.locator("#ft-mode").select_option("claim")
    def claim(text, expected):
        page.locator("#ft-query").fill(text)
        with page.expect_response(lambda r: r.url.endswith("/api/financial/claims/verify") and r.request.method=="POST") as response:
            page.locator("#ft-run").click()
        payload = response.value.json()
        assert response.value.status == 200 and payload["data"]["verdict"] == expected, payload
        expect(page.locator("#ft-result")).to_be_visible()
        expect(page.locator("#ft-run")).to_be_enabled()
        expect(page.locator("#ft-result")).to_contain_text({"supported":"資料支持","conflicting":"資料不一致","insufficient_evidence":"證據不足"}[expected])
    claim("台積電 2025 年第三季毛利率為 59.5%", "insufficient_evidence")
    ingest = ctx.request.post(API+"/api/v1/financial/facts/ingest",headers={"X-Ingestion-Token":"ci-test-only-token"},data={"facts":[{
        "ticker":"2330","company_name":"CI fixture only","semiconductor_subindustry":"晶圓代工",
        "metric":"gross_margin","period":"2025Q3","value":59.5,"unit":"%",
        "statement_type":"income_statement","source_kind":"mops_xbrl","source_url":"https://example.invalid/ci-fixture",
        "statement_scope":"consolidated","is_demo":False
    }]})
    assert ingest.ok, ingest.text()
    claim("台積電 2025 年第三季毛利率為 59.5%", "supported")
    claim("台積電 2025 年第三季毛利率為 10%", "conflicting")
    passed("actual browser-to-API claim insufficient/support/conflict with isolated synthetic fixture")
    page.locator("#ft-mode").select_option("text")
    page.locator("#ft-query").fill("CI test text")
    with page.expect_response(lambda r:r.url.endswith("/api/analyze")) as risk:
        page.locator("#ft-run").click()
    expect(page.locator("#ft-result")).to_contain_text(str(risk.value.json()["score"])+"/100")
    expect(page.locator("#ft-result")).to_contain_text("後端模型輸出與執行依據")
    passed("actual news risk API score is visible in the result page")
    page.locator("#ft-mode").select_option("claim")

    attach(page,"claim.txt","text/plain",FIXTURE.encode(),FIXTURE)
    attach(page,"claim.csv","text/csv",b"metric,value\nRevenue,12345","Revenue,12345")
    attach(page,"claim.json","application/json",b'{"metric":"Revenue","value":12345}',"Revenue")
    if os.getenv("FINTRUST_TEST_CDN") == "1":
        pdf = fitz.open()
        pdf.new_page().insert_text((72,72),FIXTURE,fontsize=16)
        attach(page,"claim.pdf","application/pdf",pdf.tobytes(),FIXTURE)
        pdf.close()
        wb=Workbook(); wb.active.append([FIXTURE,12345]); out=io.BytesIO(); wb.save(out)
        attach(page,"claim.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",out.getvalue(),FIXTURE)
        doc=Document(); doc.add_paragraph(FIXTURE); out=io.BytesIO(); doc.save(out)
        attach(page,"claim.docx","application/vnd.openxmlformats-officedocument.wordprocessingml.document",out.getvalue(),FIXTURE)
        img=Image.new("RGB",(1100,220),"white")
        ImageDraw.Draw(img).text((35,50),"FINTRUST TEST 2025",fill="black",font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",70))
        out=io.BytesIO(); img.save(out,format="PNG")
        attach(page,"claim.png","image/png",out.getvalue(),"FINTRUST",timeout=180000)
    else:
        print("PENDING external PDF/XLSX/DOCX/OCR CDN parser tests",flush=True)

    page.goto(WEB+"/member.html")
    expect(page).to_have_url(re.compile("login.html"))
    assert page.locator("#ft-google-signin svg path").count()==4
    assert page.locator("#ft-auth-email").evaluate("(el)=>getComputedStyle(el).backgroundColor")=="rgb(255, 255, 255)"
    assert page.locator(".auth-card").evaluate("(el)=>getComputedStyle(el).backgroundColor")=="rgba(255, 255, 255, 0.82)"
    passed("shared gradient surfaces, opaque input fields and multicolor Google identity mark")
    page.goto(WEB+"/register.html")
    email="ci-"+uuid.uuid4().hex+"@example.invalid"
    password="ci-test-password-2026"
    page.locator("[name=display_name]").fill("CI Test")
    page.locator("[name=email]").fill(email)
    page.locator("[name=password]").fill(password)
    page.locator("#memberRegisterForm button[type=submit]").click()
    expect(page).to_have_url(re.compile("member.html"))
    expect(page.locator("#profileForm [name=display_name]")).to_have_value("CI Test")
    page.locator("#profileForm [name=display_name]").fill("CI Updated")
    page.locator("#profileForm button[type=submit]").click()
    expect(page.locator("#profileStatus")).to_have_text("已儲存")
    page.locator("#preferenceForm [name=digest_frequency]").select_option("weekly")
    page.locator("#preferenceForm button[type=submit]").click()
    expect(page.locator("#preferenceStatus")).to_contain_text("已儲存")
    expect(page.locator("#watchlistTicker option[value='2330']")).to_have_count(1)
    page.locator("#watchlistTicker").select_option("2330")
    page.locator("#watchlistForm button[type=submit]").click()
    expect(page.locator("#watchlistItems")).to_contain_text("2330")
    page.reload()
    expect(page.locator("#profileForm [name=display_name]")).to_have_value("CI Updated")
    expect(page.locator("#preferenceForm [name=digest_frequency]")).to_have_value("weekly")
    expect(page.locator("#watchlistItems")).to_contain_text("2330")
    page.locator("#watchlistItems [data-remove='2330']").click()
    expect(page.locator("#watchlistItems")).not_to_contain_text("2330")
    page.locator("[data-member-logout]").click()
    expect(page).to_have_url(re.compile("login.html"))
    assert ctx.request.get(WEB+"/api/member/me").status == 401
    page.locator("[name=email]").fill(email)
    page.locator("[name=password]").fill(password)
    page.locator("#memberLoginForm button[type=submit]").click()
    expect(page).to_have_url(re.compile("member.html"))
    expect(page.locator("#profileForm [name=display_name]")).to_have_value("CI Updated")
    passed("development-only account registration, login/logout, persistent profile, preferences and watchlist")
    assert not errors, errors
    browser.close()
    print("CORE BROWSER E2E PASSED",flush=True)
