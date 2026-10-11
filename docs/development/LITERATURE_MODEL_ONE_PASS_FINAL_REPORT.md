# FinTrust 文獻模型一次性整合最終報告：Beneish (1999) M-Score × Dechow et al. (2011) Model 1 F-Score

**起點**：已核准的 Phase 3–5 commit `db7ee699244244e0a5f6fa636a867e4390e7ec17`。

**分支**：`feature/literature-models-beneish-dechow`。只在本機 commit；沒有 push、merge、PR、部署，也沒有任何雲端寫入。

**Commit**：
- `cc45d99`：程式與測試；
- `f358ff5`：文件、證據與工具，完整驗證在此 commit 執行；
- 本報告 commit：只新增文件。

**規格**：`docs/development/FINTRUST_BENEISH_DECHOW_ONE_PASS_CLAUDE_PROMPT_2026-10-12.md`。指令中寫的 `…_PROMPT.md` 不存在，實際讀取的是這個帶日期的檔案，維持未追蹤、原樣保留。

**結論**：`IMPLEMENTATION_COMPLETE — READY_FOR_INDEPENDENT_REVIEW`。方法解讀仍為 DRAFT，待雨靚核准。

## 1. 原文方法鎖定

| 模型 | 核對的原文 | 係數與轉換 | 狀態 |
|---|---|---|---|
| Beneish (1999) 8 變數 | 作者 1999 年 6 月手稿，SHA `78b2f014…`；FAJ 正式版為會員限定，未取得 | Table 3 Panel A「Unweighted Probit」：−4.840、0.920、0.528、0.404、0.892、0.115、−0.172、4.679（TATA）、−0.327（LVGI）。原樣本參考點 −1.78（p.17） | `source_verified_author_manuscript`：已啟用並揭露，待審查者決定 |
| Dechow et al. (2011) Table 7 Model 1 | CAR 正式期刊版（CAQ 公開刊載），SHA `e1a6e49c…` | 截距 −7.893，係數 0.790、2.518、1.191、1.979、0.171、−0.932、1.029；F = 機率 ÷ 0.0037（p.61） | `source_verified_published` |

- 論文 PDF 不進 repo、不進 ZIP，也不再散布，只記錄 SHA-256 與出處。
- Dechow 引擎以論文自己的 Enron 範例驗證：論文為 PV −4.575／機率 0.01020／F 2.76，引擎為 −4.575458／0.010197／2.755822。
- 係數未經驗證、或被其他模型變體挪用時，一律 fail closed，不輸出分數。

## 2. 資料來源與 bounded 萃取

- **沒有新增任何下載，網路請求為 0。** 官方可取得的結構化報表都已在核准 archive 中：
  - 2011–2012 年 MOPS XBRL 先前已記錄為 `filing_not_found`；
  - MOPS 只提供目前版本的 XBRL；
  - 其餘 PDF 為掃描影像。我沒有使用 OCR，因為那等於以推測方式產生官方紀錄。
- **從已保存的原始檔逐行萃取**（每個檔案都重新驗證 SHA-256）：
  - 共 **4,393 筆官方原始文件觀測值**，來自 15 個檔案：13 份 XBRL（FY2013–2025），以及 2 份 FY2011–2012 原始 TW-GAAP 合併年報 PDF（140 筆）；
  - 年報 PDF 通過單位、民國年度、合併範圍與兩項恆等式檢查；
  - 重跑新增 0 筆，digest 一致。
- **2016 年公告的 pre 值**與原始 FY2011–2012 年報的 18 個重疊科目 **18／18 完全相同**。
- **儲存方式**：存入獨立、append-only 的 sidecar（`data/literature_models/literature_inputs.sqlite3`）。16 張核准表、12 個 ZIP／sidecar 與原始 archive 經比對 **完全相同（IDENTICAL）**。

## 3. 實際計算結果（皆為 hindsight=true，RETROSPECTIVE_FORENSIC）

**目前申報版本系列（latest_available）**：

| 項目 | 結果 |
|---|---|
| Beneish | 13 年已計算（FY2013–2025） |
| Dechow | 12 年已計算 |
| 可比較配對 | 12 組 |
| FY2011–2012 | `source_unavailable`（最新版本為重編版 A06，報表頁為影像） |
| FY2018 Dechow | 不可計算：無發行證據，視為未知，不當作 0 |

**原始申報系列（original_only）**：

| 項目 | 結果 |
|---|---|
| Beneish FY2011（TW-GAAP） | M = −1.730106 |
| Beneish FY2012（TW-GAAP） | M = −2.286269 |
| Dechow FY2012 | F = 0.892005 |
| Dechow FY2011 | `missing_t_minus_2`：沒有 FY2010 申報 |
| FY2013–2015 | 原始 TIFRS 年報為影像，不可用 |

**年度×模型配對總數**：

| 狀態 | 配對數 | 組成 |
|---|---:|---|
| 實際計算 | **28** | 目前版本 Beneish 13、Dechow 12；原始版本 Beneish 2、Dechow 1 |
| 不可計算 | **32** | 兩系列合計（共 60 格）；原因逐格列在涵蓋矩陣 |
| 嚴格時點（STRICT） | 30 格全為 null | 三個截點 × 2 模型 × FY2011–2015：2016-05-13、2016-11-13 21:26:22／23。可採納輸入為 0，不回填 2015 年分數 |

**比較與限制**：
- 無法在同一年同時計算原始與重編兩側，因此 **不報告重編前後的分數差**，也沒有拼接另一側的數值。
- 單一個案不能證明哪個模型較好，所以不報告 AUC、精確率、敏感度、信賴區間或顯著性。
- FY2025 的 1,721 千元差異不由任何文獻分數分類；RECON 模式呼叫文獻模型回傳 409。
- 完整逐年結果見 `docs/research/LITERATURE_COMPARATIVE_CASE_STUDY_1785.md`。

## 4. F05／F06 修正

- **F05**：同一個鍵若有多個版本，改為 fail closed，回報 `ambiguous_version`／`ambiguous_filed_fact_versions`。
  - 涵蓋情況：數值不同、金額相同但版本不同、同版本但雜湊衝突；
  - 輸入順序打亂後，結果與 digest 完全相同；
  - 原有 1785 研究基準結果維持不變（5 個既有 run 仍可重現）。
- **F06**：舊的 v1 來源比對 run 現在顯示 `method_version_changed`，並附 `legacy_method_not_reproducible=true` 與 `source_inputs_unchanged=true`，不再被誤判為「輸入已變更」。舊 run 不改寫；新方法會產生新的 run id。

## 5. API／Flask／UI

**FastAPI 新端點**：
- `GET /api/v1/research/literature/models`
- `GET /api/v1/research/cases/{ticker}/literature/coverage`
- `POST /api/v1/research/literature/compute`
- `POST /api/v1/research/literature/compare`

OpenAPI 見 `docs/data/openapi_research_v2.json`。

**行為規則**：
- `model_ids` 與 `version_policy` 必填，沒有預設值；
- 預設為 dry-run；
- 要儲存結果必須帶既有的 ingestion token；
- Flask 只做代理，瀏覽器端無法儲存。

**研究頁新增第 7 個視圖「文獻模型比較」**：
- 兩模型並列；
- 8 個與 7 個變數的缺漏熱圖；
- t／t−1／t−2 來源下鑽；
- 公式與原文出處；
- DRAFT 核准標示，這是資料來源屬性；
- hindsight 警告；
- 分數走勢只畫可比較年度；
- 不會出現「低風險」字樣。

## 6. 測試（分層；完整紀錄見 UTF-8 測試 TXT）

| 層級 | 結果 |
|---|---|
| 後端全套 | **665 通過、5 略過**（新增 33 項） |
| 根目錄 | **148 通過** |
| 研究子集 | 101 通過、2 略過 |
| pyarrow 23.0.1 隔離環境 | 根目錄 148 通過；後端 665 通過、5 略過 |
| 歷史資料 | 167 通過、2 略過 |
| 法說會／JSD | 151 通過、1 略過（JSD 檔案未改） |
| 2330／2454 | 7 通過 |
| 全新 worktree | 603 通過、67 略過 |
| **Firestore emulator** | 7 通過 |
| **E2E**（真實 FastAPI 與 Flask 程序、本機 HTTP、headless Chrome） | 9 個視圖、16 項 HTTP 全過 |
| preflight | 全過，沒有寫入 |
| pip-audit | 無漏洞 |
| 秘密掃描 | 0 |
| ruff | 33 項，皆已逐項記錄：B008 FastAPI 慣用法、E501 多為既有長行、S608／S105／S311 誤判 |

**略過原因**：emulator 專屬測試（另以 emulator 實跑）、live MOPS 測試需手動開啟、缺少 reportlab 套件。

**未執行**：GCS emulator；任何 live 或 staging 雲端操作。

## 7. 待雨靚決定事項

1. 是否接受以作者手稿驗證 Beneish 係數；若不接受，把登錄層級改為 `unverified` 即可停用 Beneish 分數。
2. COMPUSTAT→台灣科目對照（DRAFT）：
   - SG&A 是否含研發；
   - 應收是否含其他應收款；
   - IFRS 16 租賃負債與使用權資產折舊如何處理；
   - CHE／IVST 是否排除受限存款；
   - IB 採用合併總額還是歸屬母公司。
3. FY2013 的 t−2 以 IFRS 轉換日期初資產負債表代替上年底；報表中「未列示科目」以 0 計是否可接受。
4. 是否把 PIT 契約擴充到以檔案層級公開時間判定（FY2011–2012 原始年報的公開時間已驗證），進而讓 STRICT 模式可以評估。
5. 個案解讀，以及未來台灣多公司標註樣本的設計（見個案研究 §5，本輪未執行）。

**交付檔**：精確路徑、大小與 SHA-256 列在 `fintrust_backend/data/literature_models/LITERATURE_HANDOFF_INDEX.json` 與最終回覆中。
