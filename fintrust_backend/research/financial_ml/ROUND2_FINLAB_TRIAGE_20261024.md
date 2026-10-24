# Round 2 — FinLab 重大訊息資料篩選（2026-10-24）

## 實際讀到的研究輸入（本機，不公開授權資料）

使用者依其 FinLab 帳號從 `important_info_announcement` 取出 **1,260,494** 筆原始公告，
再以廣泛關鍵字產生 **7,540** 筆本機候選。
提供的 `finlab_restatement_candidates.csv` 是 13.08 MB、10 欄，
本次本機樣本 SHA-256：
`488c1c55c4d4853b090215ac46c2369923e34b38f4f00a15caae793f1adbdd2d`。

7,540 筆內 `stock_id` 有 2,161 家、明確 `重編/重行編製/重新編製` 標題 **745** 則。
檢查欄位 `symbol,date,name,title,info,key_date,source_market,source_clause,source_sequence,stock_id`：
沒有完全重複行、沒有 `stock_id/date/title` 複合鍵重複；
`key_date` 大多為 2026 年的資料整理時間，**不是公告日期**。
目前研究應以 `date` 作公告時間。

輸入實際包含 2006–2026 年公告，而 `data.search(details=True)`
顯示免費截止 `2023-12-31`。以實際檔案為準描述**觀察到的內容**，
不可宣稱 2024–2026 公告對免費帳號「完整且持續可用」或
該資料集涵蓋所有 MOPS 正式財報更正紀錄。FinLab 官網：
https://finlab.finance/data/important-announcements

### 初步真實檔案篩選結果（不是正式的 Y）

依本輪 Python 分類條件得：

| Tier | Notice rows | Meaning |
|---|---:|---|
| A_RESTATEMENT_ANNUAL_REVIEW | 228 | 明確標題年度重編、非明顯程序延後/子公司代公告/「重編後附註更正」 |
| B_RESTATEMENT_CONTEXT_REVIEW | 502 | 重編相關，但為季度、程序、年份不清、補充或特殊情境 |
| C_ANNUAL_CORRECTION_REVIEW | 1,998 | 年度財報更正，必須釐清核心金額是否受影響 |
| D_QUARTER_OR_YEAR_UNCLEAR | 3,547 | 季度與其他更正；年度不確定 |
| E_ADMIN_OR_NONFINANCIAL_REVIEW | 1,265 | 多屬一般申報日期、人事、行政等 |
| **Total** | **7,540** | |

針對 A + C 類：
- 2,226 則優先／次優先年度公告；
- 其中 99 則有明確提及合併報表且不是純個體公告的 HIGH priority；
- FY2013–2023 形成 1,383 個公告與年度的連結，
  去重後 **1,190 個公司年度候選組合，807 家公司**；
- A 類 FY2013–2023 只有 **95 個不同公司年度、59 家公司**，
  仍非核准之 Y=1；
- 多年份範圍如 `108Q4~111Q4` 必須人工檢查中間 FY，
  正規表示式只標示已明確匹配的端點，
  絕不把上下文年份自動當成真正受影響年度。

## 已提交程式與測試

- `round2_finlab_events.py`：讀取本機合法匯出 CSV、SHA、UTC/本地日期查核、
  民國／部分中文數字年度辨識、公告分類與年度候選連結。
  **不能**自動推論 0/1，不把原始內文塞入 GitHub。
- `test_financial_ml_round2_finlab_events.py`：離線合成資料測試，
  包括年度／季度區別、程序延後、行政事件及 `重編後附註更正`。
- GitHub Actions `financial-ml-round2-finlab-events.yml`：
  在公開 repo 僅執行程式碼/合成測試，
  不登入 FinLab，也不下載、發布使用者授權資料。

使用者的 FinLab 登入狀態與 Token 保留在自己的電腦；
沒有將 1,260,494 筆、7,540 筆或私人摘要公告內容推送至公開 GitHub。

## 使用者本機執行（專案 fintrust_backend 路徑）

```powershell
cd C:\Users\samue\Documents\GitHub\Financial-Risk-Alert-System\fintrust_backend
python -m research.financial_ml.round2_finlab_events --input-csv data/financial_ml/finlab_restatement_candidates.csv --out data/financial_ml/round2_finlab_review
```

輸出：
- `round2_finlab_review_notices.csv` — 公告級完整待查隊列；
- `round2_finlab_annual_year_review_links.csv` — 年度公告候選連結；
- `round2_finlab_triage_report.json` — 可稽核的統計、輸入／輸出 SHA、
  0/1 尚未核准的警示。

**原本其他來源的 26 筆 silver 標籤仍獨立存在**，尚未直接合併到新的 FinLab 候選。
光洋科 1785 仍是 reserved holdout，不能讓其歷史重編事件進入 train/test selection。

## Round2 目前資料關卡

程式化 triage 完成；真正的 supervisable issuer-year 0/1 標籤**仍未大量取得**。
要完成 Round2，應由 95 個 A 組不同年度起做去重與原始官方公告查核，
以及在 C 類抽取重大**核心金額變動**的更正；
並以完整歷史公司年度財報母體加上可證明**全年期公告查詢覆蓋率**
建 Y=0。不能將沒有命中 broad regex 的所有公司年度自動記為 0。
下一階段不是盲目增加 ML 模型種類，而是完成帶公司年度 + 原始申報時點 +
事件觀察窗口的研究用 label ledger。
