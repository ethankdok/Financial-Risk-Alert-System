# FinTrust 文獻模型輸入強化最終報告（df0fc44 獨立審查 R01、R02）

**起點**：`df0fc444cc7b14205eb430da0d2439750b016bf7`。

**分支**：`feature/literature-models-beneish-dechow`。只在本機 commit；沒有 push、merge、PR、部署，也沒有任何雲端寫入。

**Commit**：
- `cd1ad0c`：程式、測試、文件與證據工具；完整驗證在此 commit 執行；
- 本報告 commit：只新增本報告。

**規格**：`docs/development/FINTRUST_R01_R02_NARROW_HARDENING_CLAUDE_PROMPT_2026-10-12.md`；審查報告為 `FinTrust_df0fc44_Final_Independent_Code_Review_2026-10-12.md`。兩者都維持未追蹤、原樣保留。

**結論**：`READY_FOR_INDEPENDENT_REVIEW`。方法仍為 `DRAFT_PENDING_METHOD_OWNER_REVIEW`，尚未宣稱最終驗收。

這是一次範圍很窄的輸入驗證強化：
- Beneish 與 Dechow 兩個計分引擎、係數、轉換、基準率、精度、API 端點與 UI 都 **未修改**；
- 只修改 `literature_inputs.py` 的兩個驗證點，並新增測試。

## 1. 兩項發現的修正

| 發現 | 修正前（df0fc44，已重現） | 修正後 |
|---|---|---|
| **R01** `sum` 的報表錨點（anchor）有多個候選科目時，只檢查第一個存在的候選 | 合成 TIFRS：`CashFlowsFromUsedInOperatingActivities=100`、`NetCashFlowsFromUsedInOperatingActivities=200`、`ProceedsFromIssuingShares=50` → `computed/50` | 每個存在的候選都經過同義科目規則：都要通過來源閘門、數值都要相同。不一致 → `mapping_conflict`，原因 `anchor_conflict:cash_flow_operating:...=100;...=200`，數值 null，候選列在 `alias_candidates` |
| **R02** 凍結的 `verified_zero` 證明在使用處沒有重驗 | 竄改 `operands=[]`、`section_total_twd`、`evidence_fingerprint` 仍得到 `computed/0/verified_zero`；刪除被引用的觀測值會拋出 `KeyError` | `check_zero_proof()` 在使用處以 `prove_zero()` 重新推導，逐欄位比對。失敗 → `not_presented`、數值 null、原因 `zero_evidence_invalid:<reason>`，不會拋出例外 |

**R01 細節**：
- 沒有任何候選 → 仍為 `anchor_missing`；
- 任一候選有衝突的重複觀測值 → `ambiguous_version`；
- 任一候選被來源閘門擋下 → 該閘門狀態，原因 `anchor:<科目>:<閘門原因>`（不只檢查第一個）；
- 單一候選，或多個同值候選都通過閘門 → 錨點可用。
- `_agreeing` 現在會檢查全部候選並排序原因，因此候選順序與觀測值順序都不影響結果。原本 `one_of` 的不一致拒絕（F03）保留不變。

**R02 細節**：一筆凍結證明只有在以下全部成立時才被接受：
1. 同一 (metric, period) 只有這一筆（重複 → `duplicate_proof_records:<n>`）；
2. `status` 為 `verified`（否則沿用 `zero_evidence_not_verified:<rule>:<status>`）；
3. `rule`、`rule_version`、`accounting_framework`、`filing_version_id`、`metric`、`period` 與目前的對照規則、政策版本、申報與日期相同（`<欄位>_differs`）；
4. `evidence_fingerprint` 等於記錄本身內容的 SHA-256（`evidence_fingerprint_mismatch`；無法序列化 → `malformed_record`）；
5. 以目前觀測值重新推導的證明為 `verified`（`recomputed_status:<status>`），且與凍結記錄逐欄位相同，包括每個運算元的觀測值 id、科目、數值、列印值與位置（`stale_or_altered:<欄位>`）。

**其他**：
- 被接受的證明，其運算元取自重新推導的記錄，因此不會再發生 `KeyError`；
- 沒有文字 metric／period 的記錄無法證明任何事，會被忽略；
- 印出的 0 仍為 `explicit_zero`；發行科目仍不得推論為 0。

## 2. 版本變更與 run 取代

| 元件 | df0fc44 | 現在 | 原因 |
|---|---|---|---|
| 來源閘門 | `literature_source_gate_v1` | `literature_source_gate_v2` | R01：錨點的全部候選都要通過閘門與數值檢查 |
| 零值證據政策 | `literature_zero_evidence_policy_v1` | `literature_zero_evidence_policy_v2` | R02：證明在使用處重驗；v1 證明會被拒絕（`rule_version_differs`） |

其他版本（mapping v2、panel v2、PDF extractor v2、XBRL extractor v1、registry、兩個模型）都不變。

**為何升版**：對同一份合成快照，新規則會產生不同結果，因此依規格只升兩個相關版本。證明記錄內含 `rule_version`，所以 4 筆真實證明的指紋改變、輸入 digest 改變，run id 也隨之改變。舊 run 不被覆寫。

| 系列 | df0fc44 run | 新 run（`supersedes_run_id` = df0fc44 run） | 新輸入 digest | 新輸出 digest |
|---|---|---|---|---|
| latest_available | `rrun1_1648246ccaca6ea204bcd347fc83d247` | `rrun1_3aee901dc66e02346710d41e9fd0bc02` | `0e9279de…f157d` | `88878163…c0c0` |
| original_only | `rrun1_fab682f2390383952588b6b0522503ab` | `rrun1_2120551b6b6763dd65b49439602a28f4` | `4c7b4940…fec3` | `2e88df13…fd0` |

**舊 run 驗證（D8）**：
- 在暫存的 df0fc44 worktree 用舊程式重建 latest run，得到與 df0fc44 證據相同的 `rrun1_1648246c…`；
- 用新程式 `verify_run` 驗證它 → `method_version_changed`，重算 run id 為 `rrun1_3aee901d…`；
- 用新程式建立的 run 再驗證 → `reproducible`。

**限制（未在本輪修改）**：對文獻 run，`verify_run` 回報 `source_inputs_unchanged=false`。原因是文獻輸入 digest 本身包含版本識別與零值證明記錄，所以這個欄位無法區分「方法改版」與「資料改變」。這是 F06 既有邏輯（原為財務 run 設計），本輪範圍窄，因此只揭露、不修改。來源資料未變另由 D2、D7、D8 的位元組比對證明。

## 3. 真實資料結果（1785，皆為 hindsight=true）

與 df0fc44 證據逐格、逐列比較：

| 項目 | 結果 |
|---|---|
| 年度×模型配對 | **26 已計算／34 不可計算**，60 格的狀態、分數、缺漏輸入全部與 df0fc44 相同 |
| 涵蓋矩陣 | 兩個系列各 1,395 列，readiness、輸入狀態、證據型別、數值、缺漏原因、申報、來源觀測值 **0 列改變** |
| STRICT 三個截點 | 與 df0fc44 相同：全為 null，可採納觀測值 0 筆 |
| original Dechow FY2012 | **0.892005**，以使用處重驗通過的 `verified_zero` 為依據 |
| latest Dechow FY2015、FY2023 | 仍為 null（`cross_filing_overlap_mismatch`：2014 應收帳款、2022 總資產） |
| 4 筆特別股零值證明 | 全部在使用處通過；運算元與 df0fc44 完全相同，只有 `rule_version` 與指紋改變 |
| R01 錨點稽核 | TW-GAAP FY2012 申報的兩個資產負債表日（2011-12-31、2012-12-31）各有兩個總資產候選（`code:1XXX`、`label:資產總計`），數值相同（19,943,634／21,593,232 千元）；其餘錨點都只有一個候選；與 df0fc44 規則相比 **0 個判斷改變** |

因此兩個合成漏洞在真實資料中都沒有發生，所有已發表分數都不變。

## 4. 測試（完整紀錄見 UTF-8 測試 TXT）

**執行方式**：2026-10-12 在 `cd1ad0c` 驗證，一次只跑一個重量級階段，真實 exit code 由 `subprocess` 擷取，shell 階段使用 `pipefail`。可用記憶體全程約 2.9–3.4 GB。

| 階段 | Exit | 結果 |
|---|---:|---|
| P0 新測試對未修改的 df0fc44 程式（修正前） | 1（預期） | 15 失敗、4 通過：重現兩個缺陷，含 `KeyError` |
| P1 審查者重現，暫存 df0fc44 worktree | 0 | `computed/50`；竄改證明仍 `verified_zero`；`KeyError` |
| P2 審查者重現，修正後程式 | 0 | `mapping_conflict`；兩個 `not_presented`；無例外 |
| A1 語法 | 0 | ok |
| A2 R01／R02 新測試 | 0 | **19 通過** |
| A3 LIT-F01～F04 測試（含 REAL tier） | 0 | **26 通過** |
| A4 文獻模型與 UI 串接 | 0 | **33 通過**（Enron、Beneish −2.243743 不變） |
| A5 研究單元測試 | 0 | 68 通過、2 略過（emulator 專屬，C1 實跑） |
| B1 後端全套（單一行程） | 0 | **710 通過、5 略過**（691＋19） |
| B2 根目錄全套 | 0 | **148 通過** |
| B3 2330／2454 子集；df0fc44 以來其他檔案未變 | 0 | 7 通過；文獻輸入模組、測試、文件之外 0 個檔案改變（JSD、法說會、引擎皆未動） |
| B4 全新 worktree（無本機資料） | 0 | 644 通過、71 略過（625＋19） |
| C1 Firestore emulator（demo-fintrust） | 0 | **7 通過** |
| C2 8085 埠釋放 | 0 | 第一次為 1：emulator 結束後其 Java 行程（PID 324，`--project_id demo-fintrust`，C1 期間建立）仍佔用埠；只依 PID 停止後重跑通過，第一次紀錄保留 |
| C3 瀏覽器 E2E（真實 FastAPI→Flask→headless Chrome） | 0 | HTTP 全過、9 個視圖全過；瀏覽器 run id `rrun1_3aee901d…` 與證據相同 |
| C4 埠檢查 | 0 | 無殘留 |
| D1 重新萃取 | 0 | dry-run 與 append 皆 4,643 筆觀測值；新增 0 筆 |
| D2 sidecar 與資料庫 | 0 | f83aa98 的 4,393／33／1 筆逐位相同（現為 4,789／66／2）；sidecar、結果庫、核准資料庫與本輪驗證前的 SHA-256 相同 |
| D3 證據重新產生 | 0 | OpenAPI 與 `docs/data/openapi_research_v2.json` 相同 |
| D4 結果獨立核對 | 0 | 見第 3 節，PROBLEMS: none |
| D5 既有 6 個 run | 0 | 5 個 `reproducible`、1 個 `method_version_changed`（與 df0fc44 相同）；結果庫各表相同；`research_literature_scores` 0 筆 |
| D6 先前交付檔 | 0 | f83aa98 與 df0fc44 的交付資料夾、ZIP、索引共 120 個檔案逐位相同 |
| D7 核准資料基準 | 0 | **IDENTICAL**（16 表、12 個 ZIP／sidecar、原始 274 檔、法說會 4,735 檔）；`after.json` 與 df0fc44 的逐位相同 |
| D8 舊 run 驗證 | 0 | 見第 2 節 |
| E1 ruff | 0 | 6 項（見下） |
| E2 bandit | 0 | 5 項，與 df0fc44 完全相同，皆為既有 |
| E3 pip-audit | 0 | requirements 未變；無已知漏洞 |
| E4 秘密樣式掃描 | 0 | 0 筆（僅樣式掃描） |

**ruff 6 項**：
- `literature_evidence.py:76` E501：既有長行，本輪未改；
- S311 共 5 項，都是測試中固定 seed 的洗牌（排列不變性測試，非密碼用途）：其中 2 項在 `test_literature_data_integrity.py`（既有），3 項在新測試檔。

**bandit 5 項**（皆既有、本輪未改）：
- `app.py:1337` B201 High：本機 `debug=True`（在 `__main__` 下、綁定 127.0.0.1），部署前必須停用；
- B105 誤判；
- 3 項 B608：常數表名。

**未執行**：
- pyarrow 23 隔離環境：本輪只改純 Python 驗證邏輯，與 pyarrow 無關；上一輪已通過；
- GCS emulator（環境中沒有）、live MOPS（需手動開啟）、staging／production（未獲授權）。

## 5. 資料不變與隔離

- 核准的歷史 SQLite、原始與法說會 archive、12 個 ZIP／sidecar 都未變動。
- 文獻 sidecar 本輪 **沒有新增任何記錄**，位元組與驗證前相同。
- 結果庫沒有寫入。
- f83aa98 與 df0fc44 的交付檔全部保留；本輪證據放在新資料夾 `handoff_r0102/`。
- 沒有 OCR、官方資料下載、雲端寫入或付費 API；Ethan 的 JSD 程式未修改；1785 仍不在正式風險評分範圍內。

## 6. 需雨靚核准的方法事項（未自行決定）

1. 「權益區段完整列舉」零值規則（撤回時，original Dechow FY2012 變成不可計算）。
2. 部分加總的「科目層級列示規則」。
3. 是否建立「跨申報重疊差異說明登錄」（FY2015、FY2023 才可能恢復）。
4. 列為負債的特別股是否需要另外對照。
5. 現金流量表科目只以頁面身分驗證是否可接受。
6. 本輪新增：錨點候選不一致時拒絕計算（R01）、零值證明在使用處重驗（R02）。這兩項是較保守的作法，若方法負責人要採用其他規則需另行決定。
7. 既有事項：Beneish 只以作者手稿驗證；COMPUSTAT→台灣科目對照（DRAFT）；FY2013 以 IFRS 轉換日期初數作為 t−2。

**交付檔**：精確路徑、大小與 SHA-256 列在 `fintrust_backend/data/literature_models/LITERATURE_R01_R02_HANDOFF_INDEX.json` 與最終回覆中。
