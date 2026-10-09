"""SYNTHETIC Phase 1B evidence fixtures mirroring the real official page formats.

Numbers, dates and file names are invented for tests. They prove parser,
linking and point-in-time behaviour only, never that real evidence exists.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.historical_audit.sources import _OLE2_MAGIC


TICKER = "1785"
MOPS_DETAIL_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"
EBOOK_URL = "https://doc.twse.com.tw/server-java/t57sb01"


def tpex_announcement(no: str, roc_date: str, body: str) -> bytes:
    html = (f"<html><body><div class='title'>財團法人中華民國證券櫃檯買賣中心 公告</div>"
            f"<p>發文日期：中華民國{roc_date}</p><p>發文字號：證櫃監字第{no}號</p><p>附件：無</p>"
            f"<p>主旨：光洋應用材料科技股份有限公司（股票代號：1785）相關事宜。</p><p>依據：業務規則。</p>"
            f"<p>公告事項：{body}</p></body></html>")
    return html.encode("cp950")


def mops_listing(rows: list[tuple[str, str, str, str]]) -> bytes:
    """rows: (yyyymmdd, hhmmss, seq_no, title)."""
    body = []
    for day, time, seq, title in rows:
        roc = f"{int(day[:4]) - 1911}/{day[4:6]}/{day[6:]}"
        body.append(
            f"<tr class='odd'><td>&nbsp;1785</td><td>&nbsp;光洋科</td><td>&nbsp;{roc}</td>"
            f"<td>&nbsp;{time[:2]}:{time[2:4]}:{time[4:]}</td><td><pre>&nbsp;{title}</pre></td>"
            f"<td><input type='button' value='詳細資料' onclick=\"document.t05st01_fm.action='ajax_t05st01';"
            f"document.t05st01_fm.seq_no.value='{seq}';document.t05st01_fm.spoke_time.value='{time}';"
            f"document.t05st01_fm.spoke_date.value='{day}';document.t05st01_fm.co_id.value='1785';"
            f"document.t05st01_fm.TYPEK.value='otc';openWindow(this.form ,'');\"></td></tr>")
    html = ("<html><body><form name='t05st01_fm'></form><table><tr><th>公司代號</th><th>公司名稱</th>"
            "<th>發言日期</th><th>發言時間</th><th>主旨</th></tr>" + "".join(body) + "</table></body></html>")
    return html.encode("utf-8")


def mops_detail(day: str, time: str, seq: str, subject: str, explanation: str) -> bytes:
    roc = f"{int(day[:4]) - 1911}/{day[4:6]}/{day[6:]}"
    html = (f"<html><body><center>公開資訊觀測站</center><table>"
            f"<tr><td>本資料由 (上櫃公司) 1785 光洋科 公司提供</td></tr>"
            f"<tr><td>序號</td><td>{seq}</td><td>發言日期</td><td>{roc}</td><td>發言時間</td><td>{time[:2]}:{time[2:4]}:{time[4:]}</td></tr>"
            f"<tr><td>主旨</td><td>{subject}</td></tr><tr><td>符合條款</td><td>第30款</td></tr>"
            f"<tr><td>事實發生日</td><td>{roc}</td></tr>"
            f"<tr><td>說明</td><td><pre>\n{explanation}</pre></td></tr></table>"
            f"<p>以上資料均由各公司依發言當時所屬市場別之規定申報後，由本系統對外公佈</p></body></html>")
    return html.encode("utf-8")


COMPARISON_EXPLANATION = """1.事實發生日:105/11/11
2.更正且重編之財務報告年季:100年至104年各期合併財報
5.與前次公告財務報告之主要差異:
重編前-合併資產負債簡表： 單位:仟元
 102.12.31 103.12.31
 ------------ ------------
資產總計 1,000,000 2,000,000
權益總計 600,000 900,000
重編後-合併資產負債簡表： 單位:仟元
 102.12.31 103.12.31
 ------------ ------------
資產總計 990,000 1,950,000
權益總計 550,000 800,000
重編前-合併損益/綜合損益簡表： 單位:仟元
 102年 103年
 ------------ ------------
營業收入 1,000,000 1,100,000
營業成本 (800,000) (850,000)
本期淨利 40,000 45,000
重編後-合併損益/綜合損益簡表： 單位:仟元
 102年 103年
 ------------ ------------
營業收入 1,000,000 1,100,000
營業成本 (810,000) (900,000)
本期淨利 30,000 (5,000)
6.因應措施:於公開資訊觀測站公告重編後之各期合併財務報告
7.其他應敘明事項:無"""


def ebook_listing(rows: list[dict[str, Any]]) -> bytes:
    header = ("<tr><th>證券代號</th><th>資料年度</th><th>資料類型</th><th>結案類型</th><th>性質</th><th>資料細節說明</th>"
              "<th>備註</th><th>電子檔案</th><th>檔案大小</th><th>上傳日期</th><th>財務報告更(補)正</th></tr>")
    cells = "".join(
        f"<tr><td>1785</td><td>{r['year']}</td><td>財務報告書</td><td></td><td></td><td>{r['detail']}</td>"
        f"<td>{r['remark']}</td><td><a href='javascript:readfile2(\"A\",\"1785\",\"{r['filename']}\");'>{r['filename']}</a></td>"
        f"<td>{r['size']:,}</td><td>{r['uploaded']}</td><td>{r['correction']}</td></tr>"
        for r in rows)
    return f"<html><body><form name='fm2'></form><table>{header}{cells}</table></body></html>".encode("cp950")


def ebook_step9_page(pdf_path: str) -> bytes:
    return f"<html><body><a href='{pdf_path}'>下載</a></body></html>".encode("cp950")


def synthetic_pdf(size: int) -> bytes:
    head = b"%PDF-1.4\n% synthetic test report\n"
    return head + b"0" * (size - len(head))


def fake_xls(report_year: int, rows: list[list[Any]]) -> bytes:
    """OLE2-magic bytes carrying a JSON sheet; tests patch xlrd.open_workbook to read it."""
    roc = report_year - 1911
    header = ["公司名稱\r\nSecurity's\r\nCode & Name", "", "營業收入\r\nOperating Revenues", "", "",
              "營業利益\r\nIncome(Lose) from Operation", "", "營業外收支淨額\r\nTotal Non-Operating Income", "",
              "稅後純益\r\nNet Income after Tax", "", "", "本期末股本\r\nCapital Stock", "每股稅後純益\r\nEPS", "",
              "每股\r\n淨值\r\n(元)\r\n(A)", "淨值佔\r\n總資產\r\n(%)\r\n(B)", "流動\r\n比率\r\n(C)"]
    cur, prior = f"{roc}年1-12月\r\nJan.-Dec.", f"{roc - 1}年1-12月\r\nJan.-Dec."
    subs = ["", "", cur, prior, "增減\r\n(%)", cur, prior, cur, prior, cur, prior, "增減\r\n(%)", "", cur, prior, "", "", ""]
    sheet = [["證券櫃檯買賣中心上櫃公司財務資料簡報"] + [""] * 17, ["FINANCIAL INFORMATION"] + [""] * 17,
             [""] * 8 + [f"民國{roc}年1-12月"] + [""] * 7 + ["單位:新臺幣千元", ""], [""] * 18,
             header, [""] * 18, subs, [""] * 18, ["02", "食品工業"] + [1.0] * 16, *rows]
    return _OLE2_MAGIC + json.dumps({"name": "synthetic", "rows": sheet}, ensure_ascii=False).encode("utf-8")


class FakeSheet:
    def __init__(self, name: str, rows: list[list[Any]]) -> None:
        self.name, self._rows = name, rows
        self.nrows, self.ncols = len(rows), max(len(row) for row in rows)

    def row_values(self, index: int) -> list[Any]:
        return self._rows[index]


class FakeBook:
    def __init__(self, file_contents: bytes) -> None:
        payload = json.loads(file_contents[len(_OLE2_MAGIC):].decode("utf-8"))
        self._sheets = [FakeSheet(payload["name"], payload["rows"])]

    def sheets(self) -> list[FakeSheet]:
        return self._sheets


def fake_open_workbook(*, file_contents: bytes, **_: Any) -> FakeBook:
    return FakeBook(file_contents)
