# Phase 2｜MOPS 原始財報特徵 X × TEJ Proxy Y2 × 正式 Y1 批次標註

日期：2026-10-25。Branch: feature/financial-ml-round2-binary-labels-20261024。

## 已驗證的真實資料與限制

使用者提供的 Y2 代理標籤（TEJ Information Transparency）包含 17,948 公司×曆年：
2016–2020 train 11,003（448 positive）、2021–2022 validation 4,587（65 positive）、
2023 test 2,358（42 positive），總計 Y2=1 555、Y2=0 17,393。
Y2 是 TEJ「某曆年重編次數非零」的代理目標，**不是** 24 個月內某年度合併財報重編的 Y1。
正式 Y1 仍沒有可獨立核准的大規模正負樣本。

此回合所附的資料沒有 17,948 標籤對應的完整歷史 MOPS 原始報表 XBRL 和逐版首度公開日期證據；
因此這份 session 產出的 Phase2 覆蓋 CSV 對 15 項特徵皆留白，
**不等於**使用者 Windows 本地原本不存在歷史資料。

## GitHub 三項可執行成果

1. phase2_mops_canonical_export.py：
    使用現有 research.financial_ml.literature_dataset 的 manifest/RawEvidenceArchive，
    重用文獻 XBRL 行抽取與 FilingLines source identity gate，
    在財報合併年度（TIFRS）抽取 9 項 canonical 科目。
    避免 FinMind 季資料未確認語義，或將空白科目當零。

2. phase2_pit_x_y_bridge.py：
    從既有 literature_dataset 的真正 Beneish8
    （DSRI/GMI/AQI/SGI/DEPI/SGAI/LVGI/TATA）取得 8 項；
    由標準年報科目計算額外 7 項：
    ROA、流動比率、負債資產比、CFO/資產、應收帳款成長、存貨成長、營業現金流/淨利。
    每筆 TEJ Y2 CY=t 的預測基準是 t-1 年 12 月 31 日，
    X 使用最晚 FY=t-2 與 FY=t-3 的原始合併財報。
    要通過需要原始首次公開來源、官方 MOPS 來源 URL、發布時間、原始版驗證，
    current/prior artifact SHA/filing_version_id 匹配，15/15 特徵可計算。
    不可用 retrospective XBRL 或法定期限代替來源實際發布日。
    未通過則訓練旗標為 false，缺值保留空白。

3. phase2_official_bulk_y_gate.py：
    能批次讀取 official annual filings + 全量 24 月 correction coverage + verified amendment events
    三個原始 MOPS 驗證來源。符合原始年報與變動文件版本才核准 reviewer-attested Y1=1；
    有完整官方查核窗口與全部候選事件已解決時，才核准 reviewer-attested Y1=0；
    其他全部 UNKNOWN。光洋科 1785 保留，不可進訓練。
    本程式不連到 MOPS 核對內容，欄位通過仍僅「人工證據確認」，不是獨立 gold。

## 執行順序（在 repo/fintrust_backend，PowerShell）

第一步，從現有 MOPS 合併年報 XBRL 提取文獻特徵：

    python -m research.financial_ml.literature_dataset --acquisition-results data/financial_ml/official_batch/acquisition_results.json --output data/financial_ml/literature_phase2

第二步，從同一份官方 archive 提取 9 個年報 canonical 科目：

    python -m research.financial_ml.phase2_mops_canonical_export --acquisition-manifest data/financial_ml/official_batch/acquisition_results.json --out data/financial_ml/phase2_mops_facts

第三步，做原始版本／時間截止 X+Y2 join：

    python -m research.financial_ml.phase2_pit_x_y_bridge --proxy-labels data/financial_ml/round2_label_cohorts_20261025/tej_calendar_proxy_cohort_private.csv --acquisition-manifest data/financial_ml/official_batch/acquisition_results.json --literature data/financial_ml/literature_phase2/literature_15_features.csv --annual-facts data/financial_ml/phase2_mops_facts/phase2_mops_annual_facts_private.csv --out data/financial_ml/phase2_pit_join

若原始年報檔尚不可用，直接跑 label-only coverage receipt：

    python -m research.financial_ml.phase2_pit_x_y_bridge --proxy-labels data/financial_ml/round2_label_cohorts_20261025/tej_calendar_proxy_cohort_private.csv --out data/financial_ml/phase2_missing_x_report

證據 manifest 需另有已驗證：
original_first_public_at、original_publication_evidence_url、
original_version_verified=true、first_publication_verified=true、
point_in_time_eligible=true；舊 manifest 若沒有，結果應被擋下，不是程式失敗。

正式 Y1 批次標註（僅可使用已查核之官方 CSV，145 件候選 review 表不直接算證據）：

    python -m research.financial_ml.phase2_official_bulk_y_gate --annual data/financial_ml/official/annual_filing.csv --coverage data/financial_ml/official/full_24m_coverage.csv --events data/financial_ml/official/verified_events.csv --out data/financial_ml/phase2_official_y1_bulk

## 完成驗收

- 不能以 TEJ 重編次數=0 或沒有 FinLab 訊息直接推論正式 Y1=0。
- 程式已建立 XBRL sources → 8 Beneish + 7 ratios → X+Y2 join；
  **本回合 X 真實大規模覆蓋=0（未提供相應原始文件），不是計算出零財務數值。**
- 真正正式 Y1 未批次完成，待官方 MOPS first-public-date 與修改版次/24月查詢完整憑證。
- Missingness、PIT leakage、duplicate company-year、跨版本混用、holdout contamination 都有獨立測試。
- 只允許原始財報已公開的數值進入 X；不把回溯重編後更改的歷史財報直接當 ex-ante 預測資料。
- 前端、prod DB、GCP secrets、主分支皆未修改。
