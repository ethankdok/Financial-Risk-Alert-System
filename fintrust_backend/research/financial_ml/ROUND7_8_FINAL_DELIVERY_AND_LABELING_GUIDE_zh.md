# FinTrust Financial ML — Round 7 + Round 8 交付與研究標註規範

2026-10-20 | 專用開發分支：
`feature/financial-ml-round8-human-supervised-20261020`
（完整包含前一分支 Round7 的程式和測試，不需回跑 Round1–6）。

## 需求與責任邊界

- Round7：處理已封存 **光洋科 1785 FY2013–2015 重編前原始合併財報**
  `201304_1785_AI1.pdf`、`201404_1785_AI1.pdf`、
  `201504_1785_AI1.pdf`。檔案主要財務表為**影像頁**，
  不可把既有 2016 重編公告的 `PRE` 代填成原始 PDF 實際值。
- Round8：在「公司 × 財報年度」層級建立人工 0/1 分類標籤；
  模型預測的事件為有獨立文件證實的**財報重大不實／重編事件**
  vs 有進行正式追蹤且期間內未發現此類事件的對照。
  「數值偏離／novelty」和「確有問題」是不同任務。
- 保留 1785 為**獨立最終案例**，永遠不進入分類器
  fit / validation / threshold search；後來可以對 AI1
  雙重人工核對後的原始金額執行獨立 blind scoring。
- 不修改原有的財報頁面配置或 production SQLite/Cloud SQL/Firestore，
  不覆寫 Round1–4 封存研究資料或現有模型。

## Round7 已完成程式

`research/financial_ml/round7_original_pdf_review.py`

1. 從本機既有
   `historical_audit/packages/fintrust_1785_2011_2016_full.zip`
   讀取三份完整 AI1 PDF。整包 SHA-256 鎖定
   `693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826`，
   使用獨立 `package_verify` 對 manifest 和封存位元組完整驗證。
   PDF 各自原始 SHA 前綴為：
   2013 `44c777c18128a59d`、
   2014 `320b3dc81a7671c8`、
   2015 `0ca2d7e5636c0f6e`。
2. 使用 PyMuPDF 渲染每份前 13 頁
   `round7_original_1785_pdf_review/pages/{year}/page_NNN.png`；
   另保存頁碼及文字可擷取性清單。**不以英文字元 OCR 猜測中文掃描財務數字。**
3. 自動產生兩份 **36 欄位（3 年 × 12 財務欄位）**
   A/B 原始 PDF 核對表。填入：原始 PDF 所看到的仟元數值、
   PDF 頁數、審核者 ID。原始 PDF 雙份覆核一致才正式收錄。
   空白、頁數缺漏、來源 SHA 不同、兩人金額不同、同人重覆核對，
   全部拒絕入正式原始金額表。
4. 將通過的欄位以完整新臺幣金額匯入
   `round7_original_1785_verified_db/original_1785_research.sqlite3`
   （額外資料庫，不是生產資料庫）。儲存年度、科目、數值、
   來源 PDF SHA、頁碼、original/TIFRS/consolidated、審核狀態。
5. 使用 2016/11 官方封存包
   `fintrust_1785_asof_2016-11-14.zip` 的
   `restatement_comparisons.csv` **PRE side**
   執行逐欄對照，但只在外部 audit 表中顯示
   MATCH / DIFFERENCE，不用官方重編公告替代原始 PDF 的輸入。
6. 光洋科原始數值可由獨立 read-only service 讀取。
   新增後端 API
   `GET /api/v1/research/cases/1785/original-ai1-reviewed?analysis_mode=RETROSPECTIVE_FORENSIC`
   預設關閉，只有管理者明確設定
   `FINTRUST_1785_ORIGINAL_REVIEW_API_ENABLED=1`
   與 `FINTRUST_1785_ORIGINAL_REVIEW_DB=.../original_1785_research.sqlite3`
   才會讀取；絕不回傳來源 PDF 檔案內容，不影響既有 UI。

### Round7 使用

在專用 `Financial-Risk-Alert-System-ML/fintrust_backend`，
啟用原本 `ml-env`：

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-round8-human-supervised-20261020
python -m pip install pymupdf
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round7_original_pdf.ps1
```

`original_review_A.csv`／`original_review_B.csv` 需獨立人工抄錄；
請保留缺失值空白並附真實 PDF 頁碼。完成人工審核後：

```powershell
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round7_original_pdf.ps1 -Finalize
```

如 `full.zip` 不存在，必須從原始檔案下載封存處取得相同 SHA
或由使用者提供該 3 份原始 PDF；不能拿 2016 重編公告摘要
當作原始 PDF。

## Round8 已完成程式

`research/financial_ml/round8_human_supervised_classifier.py`

### 人工標註的正確分類

| 類型 | 標籤 | 核對責任 |
|---|---|---|
| Regulator / court confirmed misstatement affecting this SAME firm-year | 1 | 官方原文、受影響財報年度、最初申報 PDF/發表時點、兩位核對者/方法核准 |
| Official followup screened no *identified* misstatement for >= 2 years | 0 | 有證據的否定追蹤期間、同公司年度原始 PDF、兩位核對者/方法核准；這不等於可證明公司「絕對沒有問題」 |
| 未追蹤、未知、新聞僅有猜測或只看到最新 FinMind 總表 | UNKNOWN | 只進入人工 review queue，**不能**直接標 0 或當作監督式模型負例 |
| 光洋科 1785 | final blind case | 不進 train/validation/test，保留日後 independent case score |

使用 `annual_12_amount_candidate_index.csv` 的 120 公司研究候選樣本
建立人工審核佇列。該批 FinMind 金額是「可以挑候選事件的起點」，
**不是已驗證原始申報資料**，所以機器學習訓練表只接受另外提供的
原始財報和法規/事件證據、加上核准的 12 個金額特徵。

### 模型與方法

- 樣本單位：**issuer-fiscal-year**，不是單一 XBRL 欄位或單則公告。
- 特徵：12 個原始財務金額取 signed-log，加上
  Gross margin、Net margin、Liabilities/Assets、
  Inventory/Assets、Current ratio、CFO/Assets 6 個同份原始財報比率。
- 模型：帶 `class_weight=balanced` 的 Logistic Regression
  與 Random Forest；使用 fit-only RobustScaler，不對 1785 fit。
- 固定切分：FY<=2019 訓練、FY2020–2022 驗證、
  FY2023–2025 測試；**三個切分的公司也需互不重疊**。
- 最低門檻：fit **>=5 positive / >=10 negative**；
  validation 和 test 各 **>=2 positive / >=2 negative**；
  不達標時必須 `PENDING`，Accuracy/F1/PR-AUC 不得填數字。
- 以 Validation PR-AUC 選模型，用 Validation F1 另選決策閾值，
  固定後對 untouched Test 輸出 Accuracy、Precision、
  Recall、F1、ROC-AUC、PR-AUC、TN/FP/FN/TP。
- 輸出所選分類器的 18 個 predictive importance diagnostic，
  **不是已驗證的財報造假因果原因或不會過度擬合的保證**。
- 如果真正完成合格 supervised fit，`score-case`
  使用 Round7 經雙份人工核對的 1785 原始 12 欄位，
  針對 FY2013–2015 產出盲測研究分數；若某年缺一欄，
  留空並解釋缺少項目。**不宣稱當年即已發出警示**，
  因原始公布時點仍需額外證據。

### Round8 使用

```powershell
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round8_human_labels.ps1
```

查看：
`data/financial_ml/round8_human_review_packet/round8_human_label_review_queue.csv`。
其中候選資料全部預設 `UNKNOWN`。

由審核人員根據實際原始財報及事件證據，
參照同資料夾的
`round8_approved_original_supervised_panel_TEMPLATE.csv`
建立
`round8_approved_original_supervised_panel.csv`，
將源文件位元組放入
`data/financial_ml/round8_independent_evidence/`，
對每筆訓練樣本標示**已核准**、原始 PDF SHA、
首次公布紀錄 SHA、case 事件證據 SHA、正／負標籤原因。
沒達到核准條件的候選標籤不可用於正式模型 fit。

之後（僅資料足夠才會得到合法指標）：

```powershell
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round8_human_labels.ps1 -Train
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round8_human_labels.ps1 -ScoreCase
```

若沒有已核准來源、同一公司跨時段、正負樣本不足，
必須保留 `real_supervised_f1=null`，不可人工補值。

## 工程驗收與資料操作邊界

- Round7 synthetic regression: **8/8 PASS**，
  https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39364349291
- Round8 synthetic regression:
  CI 資料均為**人工測試產生**，不能當真實公司的分類測試；
  需查看分支最新 GitHub Actions 執行紀錄。
- 真實 FY2013–2015 PDF raw bytes 是 gitignored 的使用者本機
  研究資產；在此雲端工具中**尚未取得**。
  這代表目前是「程式與自動測試完成」，
  不是「原始 PDF 三份已逐頁核驗入庫」。
- 此時確定已被雙重審核核准的正、負人工標籤仍是 0/0；
  **不存在可信的真實 Fraud F1、Precision、Recall、ROC-AUC**。
  一旦 A/B 人工逐欄覆核、原始時點證據及 0/1 事件審核完成，
  以上程式即可完成實際資料庫寫入、監督式模型訓練和 1785 盲測。
