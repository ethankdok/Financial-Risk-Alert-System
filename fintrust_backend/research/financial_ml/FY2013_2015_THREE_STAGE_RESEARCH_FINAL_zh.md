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


## 2026-10-20：承接 Stage1 的實際官方 XBRL 資料回收與 4,320 格逐科目比對

已新增 `fy2013_2015_official_archive_reconcile.py`，**不是另開研究年度或改模型**。
源資料為本機已成功產出的
`stage1_data/fy2013_2015_exact_360_financial_source_audit.csv`，
包含 120 家 × 3 年，114 筆完整 FinMind **候選**及 246 筆不完整候選。

- 預定從 TWSE 官方 MOPS（不是新聞）批次取得 FY2013–2015 年度 XBRL，
  直接重用原有 `official_batch.acquire()`、
  `mops_annual_url()`、`normalize_annual_filing()`、
  `RawEvidenceArchive` 的現成程式。
- 360 個公司年度分成 30 批、每批最多 12 件，先抓 FinMind
  缺少完整12個金額的公司年度；可指定批次從中斷處恢復。
- 逐件保留 TWSE URL、raw SHA-256、合併/個體辨識、
  TIFRS 判定、XBRL 正規化品質及原始下載位元組。
- 報表 `fy1315_360_official_archive_status.csv` 表示每個公司年度
  是否**真正下載與完成正規化**；
  `fy1315_4320_metric_reconciliation.csv` 比對 12 項同年度
  財務數值與 FinMind 候選的缺值、差異。**只有取得成功的原始
  位元組經 SHA 核對，才能視為有實際 XBRL 資料。**
- 官方當前下載的「歷史 XBRL」仍可能已被重編/更正，
  因此每筆 `current_archive_is_original_first_filing=false`，
  `source_eligible_for_0_1_training=false`。
  如此可實際推進資料清洗及核對，卻不偽稱已完成先驗時點驗證。
- 全面維持 **FY2013/2014/2015**，不導入 FY2016+ 財務特徵；
  FY2016+ 公告僅可在 Stage2 對原始 2013–2015 報表做後續事件標註。

### 使用者已完成 Prepare，所以直接執行下一個 Stage

在原先 ML worktree 的 `fintrust_backend`：

```powershell
git pull --ff-only
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_fy2013_2015_three_stages.ps1 -Stage AcquireArchive -BatchStart 1 -BatchCount 2
```

確認第一輪取得成功及是否有來源存取限制後，
可使用 `-Stage AcquireArchive -BatchStart 3 -BatchCount 28`
取得餘下批次。每批最多12次外部請求，請勿高頻輪詢 TWSE。
僅重新整理已存在的來源與 4,320 格比較而不新增下載，使用
`-Stage ReviewArchive`。

**停止條件：** 來源若回 403、驗證碼、非 XBRL 或要求身份認證，
保留來源失敗證據並停止；不能人工猜測 XBRL 或改抓目前數據
然後當作2013–15首份公告。有效原始首次申報仍須另外版本審核。

新增合成測試已檢驗批次計畫 360、只採三年、SHA 篡改拒絕、
分批續抓、比較 4,320 格與不當升級標籤禁止；
這不是 360 筆 MOPS 實際下載成功的宣稱。

### 目前真實人工 Label 與模型實證進度

正式 0=0、1=0。沒有任何受監督、資料驗證通過之真實訓練分數。
必須在 Stage2 取得原始首次申報及官方重編查詢完整紀錄、
由不同審核者核准正負樣本，再跑 Stage3 的受監督分類器。
模型源程式已能在合成審核資料上 E2E 訓練、測試，
但**絕不把合成成績當作 FinTrust 財報重編的 Precision/Recall/F1**。
