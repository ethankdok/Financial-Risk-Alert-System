# Round10｜120 公司 × 13 年度 × 4 季度：公開更正與財報不實標註研究

截至 2026-10-20，已取得使用者**明確提供**的 120 個不重複股票代碼，
並鎖定研究母體；不得以全上市櫃清單或舊有開發案例取代。

## 研究單位與完成程度

- 母體：120 家，不含 1785、3027、8299、6452。
- 待審年度格數：120 × FY2013–2025 = **1,560 格**。
- 待審季度格數：120 × 13 × Q1–Q4 = **6,240 格**。
  這只是格數，不保證每個季度都有正式首次申報，上市前/上櫃前或格式
  改制可能缺少合格資料，不可把「沒有申報」或「搜尋不到」當作正常。
- 目前明確蒐集公開事件來源的公司 **11 家**，**12 筆公司公告**；
  完整 120 家所有期間的官方資料逐筆對照**尚未完成**。
- 核准 fraud=1：**0**；核准 reviewed negative=0：**0**；
  **不允許**正式監督式舞弊模型 fit 或填寫 Fraud accuracy/F1/PR-AUC。
- 前述 3027、8299、6452 是其他開發案例，並**不在本次 120 名單**，
  不能算到正例分母；1785 仍保留盲測。

## 本次來源：公告本身仍須返回 MOPS 原件核對

來源彙整：
`round10_user_cohort_20261020_disclosure_leads.json`。
12 筆都有公開公告轉載網址、公告日、對應年度與季度、事件類型。
下列是依公告內容**可以進入人工事件審查的線索**，
不代表認定造假：

| 公司 | 已知事件期間 | 類別 | 為何不能直接等同 Fraud=1 |
|---|---|---|---|
| 6485 點序 | FY2023/2024 及各季 | 實質財務金額更補正（存貨、毛利、淨利等） | 有更正，不等於已認定主觀造假 |
| 8487 愛爾達 | 2018Q2、2019Q2、2022Q3，另 FY2018–FY2021及其他季更補正 | 正式季度重編與補正 | 應逐期辨認影響年份、原始公告及證據 |
| 7723 築間 | FY2022/2023、2023Q2 | 關係人交易附註更正 | 與主要報表虛報為不同標籤 |
| 1301 台塑 | FY2025，公告 2026/3/16 | 中國投資資訊附註誤植 | 附註更正非已認定造假 |
| 6272 驊陞 | FY2022/2023，公告 2025/5/15 | BS / CFS / 附註更補正 | 公司明示不影響總資產、權益、營業利益及稅後淨利 |
| 6902 GOGOLOOK | 2025Q2 | 前期比較欄附註更正 | 當期與 2024 比較欄不能混 |
| 8462 柏文 | FY2023 | iXBRL 股數欄位更正 | iXBRL欄位改正與舞弊屬不同事件 |
| 6697 東捷資訊 | 2024Q4 月營收公告 | 公司明示2024FY年度合併/個體財報不受影響 | 非年度財報數值更正 |
| 1104 環泥 | FY2025 | 關係企業營業報告董事資料 | 非財務報表數字更正 |
| 8411 福貞-KY | 2025Q1 | 董事會核准報告公告的更正 | 不足以證實財報數值改變 |
| 8271 宇瞻 | 2024Q2 | 董事會日期更正 | 非財務數值更正 |

## 為什麼「每家公司每個年度未發現重編」仍不可直接標 0

金融資訊可信度系統目標為識別**獨立證實的報表重大不實**。
沒有被媒體、法院或MOPS搜尋抓到的問題，不等於帳簿、交易
和所有財報都真正正確。正式負例須定義保留的追蹤時窗、
查核範圍、原始發表證據、公開修正史、會計師報告及期後資訊，
並完成至少兩人審核。2024–2025 較近期樣本尚不足兩年完整期後追蹤，
不能在 2026 年直接批准正常。

### 建議研究標籤拆成三個目標

1. `correction_event_label`：官方已確認某原始申報版本在某年／季
   更補正；同時儲存金額是否影響核心財務報表。
2. `material_restatement_label`：有正式重編或重大財務金額變更；
   先核對「更正」與「重編」性質和受影響期間。
3. `adjudicated_misstatement_label`：法院／主管機關等獨立資料
   審核確認的財報不實，只有這個可以用來研究「已確認不實」的
   Precision / Recall / F1；不能把 `correction_event_label` 直接視為此欄 1。

此外保存 `filing_version_type`、`original_document_sha256`、
`original_publication_at`、`outcome_source_sha256`、
`outcome_known_at`、`negative_followup_end_at`。
每一格可為 1、0、UNKNOWN、NOT_APPLICABLE（無該年申報），
但 UNKNOWN/NOT_APPLICABLE 不可當成 0 訓練。

## 在使用者專用 ML worktree 逐期準備與驗證

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-round10-120-period-disclosure-audit-20261020
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round10_120_company_disclosures.ps1
```

本機使用 immutable Round1
`final_round1_integrated_ml_dataset/annual_12_amount_candidate_index.csv`
核對是否**剛好符合使用者提供的 120 家完整名單**。
通過後會輸出：

- `round10_1560_annual_manual_review.csv`
- `round10_6240_quarter_manual_review.csv`
- `round10_official_event_candidate_human_review.csv`
- `round10_label_gate_report.json`

前 3 個是查核工作底稿／候選事件清單，不是認定查核完成或批准為訓練標籤。

Round8 原本的
`round8_human_supervised_classifier.py` 已支援審核後的
Logistic Regression、Random Forest、Precision、Recall、F1、PR-AUC、
不同公司/不同時間留置以及 1785 independent inference。
只有正式核准的原始財報、正負事件證據足夠，
且有同公司／同日期資料切分的驗證門檻通過後才運行。
目前應保持 `supervised_classifier_fit_allowed=false`。
