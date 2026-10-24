# FinTrust Round 2B — FinLab 重大訊息證據分析、公司年度案件及審核閘門

## 研究範圍與資料誠實性

FY2013–2023 台灣上市櫃公司合併年度財報首次公開後 24 個月內的重編／核心金額更正。這是一個 audit warning 研究任務，不能把財報更正等同詐欺或舞弊。

- 已取得 FinLab important_info_announcement 原始公告 1,260,494 則。
- 寬鬆中文關鍵字初選後，本機候選 7,540 則、2,161 家公司。
- 本機輸入 SHA-256: 488c1c55c4d4853b090215ac46c2369923e34b38f4f00a15caae793f1adbdd2d。
- 除程式、合成測試和匯總統計外，**不要將 FinLab 原始內容、CSV 或認證 token 公開提交到 GitHub**。

## 2026-10-24 實測結果

| 分類 | 不重複公司年度 |
|---|---:|
| P0 公告聲稱已重編完成＋核心金額比較線索 | 30 |
| P1 其他公告聲稱完成／描述重編 | 15 |
| P2 核心科目與金額前後比較線索 | 142 |
| P3 複數年度／跨期範圍不明 | 93 |
| P4 其他年度財報更正待查 | 891 |
| 合計 FY2013–2023 候選公司年度 | **1,171** |
| 不重複公司 | **791** |
| 保留光洋科 1785 全部候選公告 | **21** |

P0/P1/P2 是審核優先順序，**不是訓練 Y=1**。本輪經獨立驗證的 MOPS 真實 0/1 標籤：**0 件正例、0 件負例**。原本研究中的其他 silver label 仍是另一份資料，沒有直接改成 verified。光洋科 1785 保留作獨立測試，禁止進訓練。

與前期 1,190 個公司年度相比，新版 1,171 刻意排除部分月度自結、非年度期別的錯配，保留多公告證據關聯。

## 修正範圍與原則

- 使用 FinLab date 作公告時間；key_date 很多是 2026 年資料整理日。
- 擬重編、要求評估、展延期限不等於完成重編。
- 重編某一季度與更正其他年度不能當成「其他年度已重編」。
- 同公司同 FY 多公告以 case ID 彙整，保留來源 notice ID 與 hash。
- 每月自結財務數、純 Q1/Q2/Q3 不能視為年度財報。
- 年度跨期範圍的中間年度不擅自擴充；核心數額關鍵字是 clue，不是 numeric delta proof。
- FinLab 免費權限顯示 2023-12-31，但實際本機檔案還有部分 2024–2026 公告；不可推論後面年度覆蓋完整。
- 沒有公告不等於沒有重編，**不能自動貼 Y=0**。

## 本機操作

在 Financial-Risk-Alert-System/fintrust_backend 目錄執行：

    python -m research.financial_ml.round2_finlab_evidence --input-csv data/financial_ml/finlab_restatement_candidates.csv --out data/financial_ml/round2_finlab_evidence

輸出：
- finlab_notice_evidence_private.csv — 7,540 則標題、年度候選、公告全文證據線索、公司、公告來源欄位；
- finlab_issuer_fy_review_private.csv — 1,171 筆已合併同公司 FY 案件，P0→P4、官方來源／時間窗審核欄；
- finlab_evidence_summary.json — 版本 SHA 和匯總結果，不含授權公告全文。

輸出 immutable，若同一路徑舊檔內容不同便停止，保留可重現性；更新資料請用新資料夾。

## 核准嚴格正例閘門

在本機**複製**案件 CSV 成 private reviewed CSV，新增以下欄位：

- reviewer_evidence_checked = yes
- verified_event_kind = RESTATEMENT 或 CORE_AMOUNT_CORRECTION
- core_line_item, verified_old_value, verified_new_value = 核心金額更正類型必填

填寫原本的審核欄：

- mops_notice_url 與 original_financial_filing_url 必須指向可查核之官方 MOPS 財報與公告；
- first_report_public_date 和 verified_correction_date 用 ISO YYYY-MM-DD；
- scope_verified = consolidated；
- 核心金額更正須 line_items_old_new_verified = true，且前後數值不同；
- 核准案件的 adjudication 設為 APPROVE_SOURCE_REVIEW。

執行：

    python -m research.financial_ml.round2_finlab_review_gate --reviewed-csv data/financial_ml/round2_finlab_evidence/finlab_issuer_fy_reviewed_private.csv --out data/financial_ml/round2_finlab_adjudicated

審核會檢查：官方 URL hostname 格式、原始財報日期、重編／更正日期不超過 24 個日曆月、合併報表、事件類別、必要核心科目數額、未來日期及 1785 holdout；通過才在 reviewer_attested_positives_private.csv 輸出 reviewer-attested 1。程式無法自動瀏覽並核對 MOPS 原文，故**這不等於獨立證實 gold label**；審核程式完全不產生負例 0。

不合格核准案件寫到 review_gate_rejected_private.csv；匯總寫到 review_gate_summary.json。未人工審查時，兩者皆不含真正通過的案例。

## 程式、測試與後續資料關卡

程式：
- round2_finlab_events.py: 第一階段寬鬆標題篩選與候選年度
- round2_finlab_evidence.py: 本輪公告全文證據、期間範圍、月報排除及公司年度事件簿
- round2_finlab_review_gate.py: 人工核准的正例閘門、24 月觀察期驗證

CI: .github/workflows/financial-ml-round2-finlab-events.yml，使用 Python 3.11 離線**合成資料**測試，不執行 FinLab token 或上傳私人公告。

真正的 ML-ready X+Y 仍需：
1. 核對 P0 30 案，逐家查 MOPS 公告＋首次原始財報＋重編後財報及版本差額；
2. 核對 P1 15、P2 142 案，確認有無變動核心年度合併財務金額；
3. 另外建立 FY2013–2023 完整公司年度財報母體、24 個月官方更正事件查詢可覆蓋的證據，才有資格產 Y=0；
4. 僅能用原本預測時點可得的 X，不能用事後更正數額洩漏資料。

官方 MOPS 入口：https://mops.twse.com.tw/mops/web/index

本檔僅保留公開程式與匯總統計，不包含 FinLab 授權公告全文。
