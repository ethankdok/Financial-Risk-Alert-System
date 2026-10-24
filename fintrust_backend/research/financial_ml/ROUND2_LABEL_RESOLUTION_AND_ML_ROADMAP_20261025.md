# FinTrust | Round 2D 標籤解套、正式驗證與後續 ML 開發流程 (2026-10-25)

Branch: feature/financial-ml-round2-binary-labels-20261024
CI: .github/workflows/financial-ml-round2-finlab-events.yml
研究範圍: 2013–2023 年台灣上市櫃公司合併年度財報異常／重編早期預警。

## 重大研究判斷：原正式 Y1 與可用代理 Y2 必須拆開

| 定義 | 單位 (grain) | 標籤來源 | 目前 |
|---|---|---|---|
| Y1（最終正式） | ticker + affected FINANCIAL FY | 原始首次公開年報 + MOPS 在之後24日曆月的重編/核心金額更正申報 | 大規模 1/0 皆尚未核准 |
| Y2（探索性 proxy） | ticker + CALENDAR YEAR when TEJ report count is nonzero | TEJ Information Transparency 月份「當年度財報重編次數」 | 可以建立 proxy 0/1；不是 Y1、不是違法或舞弊標籤 |

不可將 Y2=1 判定為 Y1=1，也不可用 Y2=0 判定 Y1=0。TEJ 的月度 restatement count 不能表達受影響財報年度、原始首度公開日、真正事件日或核心金額差額。

### 關鍵來源錯配證據

- TEJ 2013–2026 資料為 388,993 筆公司月份、3,346 不同公司代碼。
- 2013–2023 年，1,417 個公司+曆年有 TEJ nonzero（沒有核准為 Y1）。
- 2014 全公司 positive 異常偏高；四碼代碼且完整 12 月樣本有 **422/2,077** positive，台積電 2330 於 2014 出現 5 的數值，而 FinLab 年度更正初選未命中該公司。對其方法學解釋未完成前不能將 2014 併入主訓練集。
- 光洋科 1785 是 2016 年發生財報重編的歷史案例，但 TEJ 2016 年 calendar-count=0。這表明正式 Y1 的正負例不可直接依 TEJ calendar-count。
- TEJ 官方將「資訊透明度」與含重編事件日、原因及調整科目金額的「重編彙總」視為不同模組：
  https://www.tejwin.com/news/公司治理資料庫/
- TWSE 提供 IFRS 版本升級的背景，但不可無證據斷言 2014 尖峰全由準則變更造成：
  https://wwwc.twse.com.tw/rwd/IFRS/update

## 本輪已建立可重現探索性 Y2 代理資料

新程式: research/financial_ml/round2_label_cohorts.py

範圍：
- TEJ 資訊透明度來源各公司曆年，**2016–2023**
- 有完整 01–12 月 12 個觀測月份，四位數公司代碼
- 光洋科 1785 排除，2013–2015 留作敏感度分析（尤其 2014）
- TEJ 曆年 count>0 => **Y2=1**；其餘完整月份且每月 count=0 => **Y2=0**
- 一律 **Y1 = blank**，源標籤寫清楚 TEJ_INFORMATION_TRANSPARENCY_PROXY_NOT_TT2
- 僅完成 Y2 研究母體與切分；**沒有 joined point-in-time 特徵 X，也尚未訓練模型**

實際本地數字：

| Split | Calendar years | Proxy 1 | Proxy 0 | Total |
|---|---|---:|---:|---:|
| Train | 2016–2020 | 448 | 10,555 | 11,003 |
| Validation | 2021–2022 | 65 | 4,522 | 4,587 |
| Test | 2023 | 42 | 2,316 | 2,358 |
| **Total** | 2016–2023 | **555** | **17,393** | **17,948** |

這是類別不平衡樣本、且有明顯跨年 base-rate drift。不能以 accuracy 當主要指標，亦不能把隨機 80/20 split 當時間序列外推能力。

從 fintrust_backend 在 **本機授權資料** 位置執行：

    python -m research.financial_ml.round2_label_cohorts --tej-year-csv data/financial_ml/round2_tej_transparency/tej_calendar_year_evidence_private.csv --out data/financial_ml/round2_label_cohorts_20261025

輸出 CSV: tej_calendar_proxy_cohort_private.csv、tej_calendar_proxy_excluded_private.csv
彙整 JSON: tej_proxy_outcome_report.json。檔案不放進公開 Git。

## 正式 Y1 先從證據批次做起

新程式: research/financial_ml/round2_official_review_sprint.py

由 1,171 個 FinLab 公司 FY 候選與 TEJ calendar-year evidence 建立：
- **45** 件 P0/P1 正例待查：15 件同曆年 TEJ 非零佐證；30 件僅 FinLab 文本 cue；
- **100** 件候選對照組（FY2016–2020 各20件）：具有後續 3 曆年各完整 12月 TEJ 0、且未落入 FinLab FY 候選池，**全部仍是 UNKNOWN**。
- 保留 MOPS 原始首次公開日、更補正公告、影響年報、實際核心金額差異及 24 個月窗口的審核欄位。
- 不核准任何正式 Y1。將通過原有 round2_finlab_review_gate.py 的 reviewer-attested positives 再進一步獨立核對。後者不會上網驗證 URL 內容，因此不得自動聲稱 gold。

運行：

    python -m research.financial_ml.round2_official_review_sprint --finlab-tej-cases data/financial_ml/round2_tej_transparency/finlab_tej_join_review_private.csv --tej-year-csv data/financial_ml/round2_tej_transparency/tej_calendar_year_evidence_private.csv --out data/financial_ml/round2_official_sprint_20261025

必要的官方查詢源：MOPS 財務報告公告、財務報告更(補)正及歷史重大訊息，分別核實「本公司/合併/年度、受影響 FY、申報版次、第一次公開日期、24個月內事件及影響金額」。
https://mops.twse.com.tw/mops/web/index

**核准 Y1=0 的前置條件尤其嚴格**：
- 公司 FY 原始合併年度財報存在，且首次公開日核實；
- 該公司自首次公開日至加 24 個日曆月的**完整官方修正紀錄/公告查詢覆蓋**有可稽核依據，而非用 FinLab 標題沒命中/TEJ=0；
- 排除撤銷/下市、資料缺漏、分期和合併/個體錯配；
- 同一 FY 若有任何仍待判定之候選事件，就必須留 UNKNOWN；
- 不得把 sample selection 中的 100 「候選對照組」直接寫成 Y1=0。

## 接下來機器學習工程（順序與交付 Gate）

**G1 / Gold Y1 核對：** 先對 P0/P1 45 件逐一查 MOPS，完成正例證據表；並試做候選控制 100 件的完整官方否定窗口檢查。記錄成功核實的數目，未知保留。若發現 MOPS 早期歷史覆蓋不足，回報狀態並使用來源分層，不填補不存在的官方負例。

**G2 / 建立可回放的 X：** 建立 ticker+FY+file version+first-public-at 的 historical annual XBRL 財報，清洗合併/個體、IFRS科目、缺值、比率；**禁止取重編後更新的歷史財務數值當事前可見的原始 X**。首版約15項財務特徵：Beneish M-score 的 DSRI、GMI、AQI、SGI、DEPI、SGAI、LVGI、TATA，加上 CFO/assets、ROA、current ratio、debt/assets、receivables growth、inventory growth、operating cash conversion。對不同產業及年度檢查可算性。

**G3 / Y2 探索性 baseline（只宣稱 proxy）：** 先把 Y2 cohort 17,948 rows 接到 as-of X。對 calendar-year t=2016…2023，預測時間為 t-1 年 12 月 31 日；若用年報，保守限制原始已公開 annual FY<=t-2，除非來源時間戳證明已公開。禁止使用 TEJ restatement count、同年 CPA 動態變數或事後改編表 X 來預測 Y2。跑 dummy majority / Logistic Regression / Decision Tree / Random Forest / SVM / Naive Bayes / KNN，先傳統分類、不要先上 Transformer。

**G4 / 評估與防洩漏：** 嚴格年度切分 2016–2020 train, 2021–2022 validation, 2023 final holdout；訓練資料中建立 imputation/scaler/SMOTE（若嘗試）等，在驗證/測試不能 fit。正例率約3%，主要 PR-AUC、precision@K、recall@K、class-specific recall、calibration、false alert cost；ROC-AUC 和 F1 為輔，accuracy 不代表效果。觀察 2021/2023 proxy base-rate drift。回報含排除 2014 與納入 2015 的敏感度分析。

**G5 / 正式 Y1 supervised：** 真正核實的 MOPS 0/1 足夠時，用 Gold Y1 的不同定義（任何有事件的重編，以及核心金額更正）各訓練/回測。樣本不足時維持 Positive-Unlabeled / small-label study，不把 unknown 當真負例。光洋科 1785 維持跨公司獨立示範，不能混入訓練。

**G6 / 系統整合與研究呈現：** 輸出模型版本、使用的資料截止點、top contributing features、官方證據與可信度，後端 FastAPI route、前端另開分頁（保留現有版型）、API regression、E2E、smoke test 和部署前 secrets gate。金融預警而非詐欺確定判斷。

## 完成定義

- 此次已完成：Y2 17,948 筆**代理** 0/1 + deterministic temporal split；45+100 正式 Y1 審核工作佇列；GitHub code+synthetic CI。
- 尚未完成：任何大量經獨立驗證的 Y1、point-in-time X join、模型訓練/指標、雲端部署。
- 下一輪的硬性驗收是 Y1 中有實際核准的 positive/negative（或用明確原始查核覆蓋失敗解釋阻礙），並產出首個 X+Y2 匯合完整性報表，而不是再增加「7,540 筆公告」這類無法當標籤的數字。

_PRIVATE DATA NOTICE_: No source TEJ XLSX, raw FinLab announcements or row-level derived records uploaded to GitHub. Local data/ ignored. GitHub CI only tests synthetic fixtures.
