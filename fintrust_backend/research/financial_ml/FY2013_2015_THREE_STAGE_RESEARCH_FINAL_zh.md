# FinTrust｜FY2013–FY2015 僅三階段實驗與驗收

**執行條件：研究輸入只使用 FY2013、FY2014、FY2015。**
120 家公司固定名單沿用使用者提供的 `round10_user_confirmed_120_tickers.txt`；
1785 光洋科**只作獨立盲測案例**，絕不拿來訓練、選模型或調整門檻。

## 本次已做的資料查找結果

- 官方 MOPSFIN 明載上市、上櫃等採用 IFRS 的資料自 2013 年起，但
  若部分公司之後才上市／上櫃／興櫃，不能假設 FY2013–2015 都有
  可公開且相同格式的首份合併財報。
  官方來源：https://mopsfin.twse.com.tw/terms
- MOPS 有正式更(補)正查詢、歷史重大訊息及財報原件下載入口：
  https://mops.twse.com.tw/mops/web/t120sb02_q10
  https://mops.twse.com.tw/mops/web/t05st01
- 2330 台積電 2015 年報的 FY2014 比較年度**註明調整後**，
  屬台灣 IFRS 比較報表調整範例；不能單憑「調整後」三字
  判斷有舞弊，亦不等於已證明正常：
  https://investor.tsmc.com/static/annualReports/2015/chinese/c_6_1.html
- 更多可查閱來源整理於 `FY2013_2015_OFFICIAL_RESEARCH_FINDINGS.json`，
  全部均保留真正審核狀態：**正式 approved 0=0、1=0**。
  這不是 360 筆全量歷史公告驗證完成的假報告。

## Stage 1：重用已完成清洗與資料工程

檔案：`fy2013_2015_stage1_freeze.py`

- 讀取現有原始的
  `annual_12_amount_candidate_index.csv`，
  驗證「120 個公司、FY2013–2025 原歷史索引 1560 筆」，
  **只提取 FY2013、FY2014、FY2015，共 360 筆研究對象**；
  FY2016–2025 資料**不進特徵、標註輸出或模型**。
- 保留已經開發的 12 個財務金額欄位。FinMind 資料來源仍標示
  `PROVISIONAL`，**不可當作原始首次申報已驗證**。
  缺值不可偷補零、缺首次財報不可當正常公司。
- 追蹤原始 PDF/iXBRL、申報版本、合併／個體、會計準則、
  首次可得日和完整來源 SHA。

## Stage 2：每個公司年度真正建立審核標籤

檔案：`fy2013_2015_stage2_labels.py`

- 只允許**相同年度、相同原始合併財報**做對照。
- 正式研究主目標：
  `MATERIAL_ANNUAL_RESTATEMENT_WITHIN_5_YEARS_OF_FIRST_REPORT`。
  這是為比較同一組原始報表後續表現，選擇固定長度的
  五年**標籤觀察窗口**。例如 FY2013 原始財報在 2014 年公告，
  可使用之後的更正公告來判定事件，但其後 FY2016+ 的財務數值
  不可成為模型 feature。
- 正例 `1`：原始報表 SHA、首次公告時間、同一年度的正式合併財報
  核心數值重編官方公告 SHA、公告日期位於五年期限內、兩名不同
  審核者及方法負責人核准。
- 負例 `0`：同樣原始 SHA、完整五年 MOPS/TPEx 正式更正歷史
  檢索存證 SHA、沒有晚發現同份財報重編問題、兩名不同審核者
  及方法負責人核准。
- 來源不足、尚未上市發行義務、查核範圍不足，一律保留
  `UNKNOWN`，不以「沒有新聞」作為已確認正常。
- 司法／金管會真正認定的「重大財報不實」另留獨立欄位，
  不與所有會計更正或重編事件偷換概念。
- 源文件 SHA **僅保證本機歸檔內容未變更**；其官方真實性、
  首次公布版本及完整檢索仍須由兩位審核人確認，
  並非 Python 自動賦予法律判定。

## Stage 3：完整 0/1 監督式分類程式

檔案：`fy2013_2015_stage3_supervised.py`

- 必須讀取 Stage2 經審核的 immutable 0/1 CSV，並與 Gate
  報告的 SHA 完整一致。
- 18 個特徵 = **12 個同年度原始財務金額（signed-log）＋
  6 個由該年度原始數字計算的比率**；
  無 FY2016+ 特徵，無重編後數值，無泄漏到特徵的事件標籤。
- 不再使用舊版 FY2016–2025 的 train/val/test 方式；
  三份樣本 FY2013、2014、2015 都應出現在 train/val/test；
  **同公司不得跨這三個集合**。
- 模型：Dummy prior 基線、Logistic Regression、
  Random Forest；RobustScaler 只在 fit 上估計，
  PR-AUC、F1 以 Validation 比較和選閾值；
  Test 僅最後評估一次，輸出 Precision、Recall、
  F1、ROC-AUC、PR-AUC、Confusion Matrix，以及
  **逐年度**混淆矩陣與指標。
- 未經核准，或正負樣本不足、某年度沒有兩類標籤、
  同公司跨集合，必須輸出 **STOPPED**，
  所有真實 F1 等指標 = `null`。
- 自動 CI 的合成資料可以確認訓練程式會執行，
  **不得把合成模型指標當成真實舞弊／重編識別能力**。

## 唯一一個執行分支與腳本（無需再跑 Round 7–11）

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-fy2013-2015-three-stage-20261020
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_fy2013_2015_three_stages.ps1
```

此命令自動執行測試、Stage1 提取 FY2013–2015 360 筆、
Stage2 生成 360 筆人工標註表。之後需要研究人員對
**這三個財報年度**完成真實人工證據覆核。

- `-Stage Approve`：使用填好的 360 筆 A/B 雙人審核表，
  及真正保存的官方文書，產出證據核准 0/1。
- `-Stage Train`：僅限通過以上審核後訓練，
  正負不足則保留明確缺口報告與 null 指標。

所有結果儲存於：
`Financial-Risk-Alert-System/fintrust_backend/data/financial_ml/fy2013_2015_three_stage_research/`。
不覆蓋舊資料庫、不觸及 production、不更動前端。

## 誠實的最終狀態

**已有已驗證研究工程：** 完成 3 階段核心程式，
使用合成資料的 end-to-end 訓練／評估測試已通過，
並且真的對 FY2013–15 來源作過官方網站調查。

**缺口：** 未取得可在此工具環境中實際驗證的
120 家 × FY2013–15 原始首次申報 PDF/iXBRL 與
完整更正史的原始檔。完整來源審核仍是人工研究工作，
因此此刻**沒有**真正可宣稱的 approved-positive/negative
和 supervised precision/recall/F1。不能因為老師急著看結果，
就把 360 家年度全部標 0，或把法律判定不明的更正
硬判 1。用不實標籤即使跑出模型指標，也沒有研究意義。
