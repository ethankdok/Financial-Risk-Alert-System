# Round 11｜同一財報年度 FY2022 / FY2023、同一 24 個月觀察期：財報更正與舞弊標註不得混淆

## 研究設計（2026-10-20）

**本次使用者已取得 Round10 成功驗證**：120 家、1560 個公司年度、
6240 個公司季度、12 筆公開更正公告線索、11 家公司；
原本的人工 **Fraud 正式標籤 1=0、0=0**；不能報告 Fraud F1。
Round10 CI 8/8 PASS，意思只有「程式核對成功」，不是 120 家已完成官方事件驗證。

新 Round11 沒有自行產生「有問題=1、其餘=0」去硬跑模型；
這會把全部未調查公司都當成正常樣本，形成嚴重的 label noise，
誤導老師認為分類能力已受驗證。

### 先做可比較的兩組單一年份

- FY2022：同一年度的原始**合併年報**，120 家公司分別尋找
  FY2022 原始首次申報文書；FY2023、FY2024 後續更正歷史
  需覆蓋「首次公布後 24 個日曆月」的精確截止點。
- FY2023：同一年度的原始合併年報；往後 24 個日曆月
  追蹤至約 2026 年春季（具體依每家首次公布日，不能假設）。
- FY2024–2025 若截至 2026/10 原始年報的 24 個月追蹤尚未成熟，
  不得作已完成追蹤的陰性年度。
- 同一年同口徑的 0 與 1 才做對照；跨年使用不同時間段需要
  fit-only preprocessing + year-specific stratum，
  公司亦須 issuer-disjoint，不可偷用 holdout 選模型。
- 1785 光洋科是最終 independent blind replay，不放入 fit，
  不從事模型門檻調整。

### 三種互不等同的標籤

1. `ANNUAL_STATEMENT_CORE_AMOUNT_CORRECTION_WITHIN_24_CALENDAR_MONTHS`
   **公司年度合併原始報告**的核心金額，在其*首次發表後*
   24 個月內有正式更補正；本輪預計先以此為研究 target。
2. `ANY_RESTATEMENT_EVER` 該份報表日後任何時候曾正式更正；
   不能把超過 24 個月才被發現的問題塞進「24 個月內」結果，
   或誤標其為已確認乾淨。
3. `ADJUDICATED_FINANCIAL_MISSTATEMENT` 司法／主管機關判斷
   具財報重大不實、欺詐性或其他獨立確認之案件。
   **不能將 1 或 2 直接稱為詐欺／造假。**

### 這次有實際找到的來源（證據層級明列）

| 股票 | 財報 FY | 公司公告／來源 | 核對事項 | 對 24m 年度 target 的狀態 |
|---|---|---|---|---|
| 6485 點序 | 2023/2024 | 2025-05-27 MOPS 公告轉載： https://news.cnyes.com/news/id/5995322 | 存貨、毛利、淨利等；需核對首次原始合併年度財報和官方公告 SHA | FY2023 具核心數字更正候選 1；未正式核准 |
| 6272 驊陞 | 2022/2023 | 2025-05-15 公司公告轉載：https://news.cnyes.com/news/id/5981441 | FY2022 原始年報何時正式發表？可能已超過 24 月，不得直接當 24m 正例 | 截止時間查核中 |
| 7723 築間 | 2022/2023 | 2024-09-10 MOPS 公告轉載：https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=5d6f8f52-1110-46d4-9ff6-ef18cec2720d | 關係人交易附註更正，不應冒充年度核心金額更正 | 附註研究目標候選，不入核心金額 1 |
| 8487 愛爾達 | 2018/2019/2022 | 2023-04-27 MOPS 公告轉載：https://news.cnyes.com/news/id/5157953 | 2018Q2、2019Q2、2022Q3 重編；各年度報表 vs 季報必須分開 | 2022Q3是季度重編，不能把 FY2022 年報直接標1；2018重編多於24月 |
| 2330 台積電 | 2022 | 官方合併財報：https://investor.tsmc.com/chinese/financial-reports | 2022 原始年度表及2023/2024續報可取得，但尚未確認該公司全部更正／重編歷史公告無缺 | 潛在人工 0 候選，**未核准** |
| 1301 台塑 | 2022 | 公司年報：https://www.fpc.com.tw/fpcw/index.php?c=22&id=13&op=res | 2022/2023/2024 官方表可核對；仍須完整更正事件歷史及首次公布時點 | 0 候選未核准 |
| 6488 環球晶 | 2022 | 官方網站：https://www.sas-globalwafers.com/investor-jp/financial-information-jp/ | 原始季度/年度 PDF 入口有，但仍需原始 SHA 與公告全集覆蓋 | 0 候選未核准 |

**重要：** 除非拿到官方首次申報、公司公告原始保存、期後
24月有效範圍與雙審證據，以上來源都只是正/負*調查候選*。

### 正式 0 / 1 要怎麼才有證據？

- **1**：同公司、同年度**原始合併年報**首次公告日、
  原始 PDF/iXBRL SHA、財務核心金額後來被更正的官方公告
  原文 SHA、官方公告日期落在首次公告後 24 月內；
  年度文件本身受影響（季度限定不得冒充年度）。
- **0**：同公司、同年度原始 PDF/iXBRL SHA 和首次公告日；
  MOPS/TPEx 官方「歷史重大訊息、財報更(補)正、
  財報版本」在首次公布至 +24 月**整段有效的查詢/下載證據**；
  必須雙人核對確認沒有符合既定範圍的年度核心金額更正，
  並排除已知在24月後才被發現有同份報表重編的情況。
  「年報無保留意見」、「沒在網路搜尋到」均不能直接當作 0。
- **UNKNOWN**：資料查找尚未完成、資料版本不對、
  原報時間沒核對、追蹤尚未成熟、公司後期才發現問題、
  正負來源證據有衝突、沒有獨立審核。

目前沒有完成上述條件的 0／1 樣本，故 Round 11 程式
拒絕傳入 Round8 `study()` 進行正式資料訓練。

### 新增程式與執行

- `research/financial_ml/round11_year_matched_evidence_gate.py`
  做 FY2022 / FY2023 同年度審核佇列與 24 月嚴格准入。
- `tests/test_financial_ml_round11_same_year_evidence.py`
  使用**合成測試檔案**（非真實公司驗證），測試
  正例24月、負例完整涵蓋、原始 SHA 雙審、超過24月不挪作正例、
  近期財報追蹤不足不得標0及同年正負成對核對。
- `verify_round11_same_fiscal_year.ps1` 一鍵生成 review queue；
  人工完成獨立證據後 `-Train` 才執行正式分類器，
  不可覆寫舊模型與評估結果。

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-round11-yearmatched-label-evidence-20261020
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round11_same_fiscal_year.ps1
```

注意：若 `round11_approved_year_matched_labels.csv` 不存在，
`-Train` 直接中止。存在但沒有合格正負樣本也中止訓練並輸出缺口，
**不會顯示虛構 Accuracy、Precision、Recall、F1**。

同年度 Excel 研究底稿由 ChatGPT 完成並放在對話產出：
`FinTrust_Round11_同年度財報24月觀察_0-1來源審核工作簿.xlsx`。
