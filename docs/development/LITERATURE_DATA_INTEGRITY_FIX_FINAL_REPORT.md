# FinTrust 文獻模型資料完整性修正最終報告（f83aa98 獨立審查 LIT-F01～F04）

**起點**：`f83aa98d04c37e34e7480349c33b85cb12933218`。

**分支**：`feature/literature-models-beneish-dechow`。只在本機 commit；沒有 push、merge、PR、部署，也沒有任何雲端寫入。

**Commit**：
- `1eeee88`：程式與測試；
- `d441805`：文件與證據工具，完整驗證在此 commit 執行；
- 本報告 commit：只新增文件。

**規格**：`docs/development/FinTrust_Beneish_Dechow_Consolidated_Review_Fixes_Claude_Prompt_2026-10-12.md`；審查報告為 `…_Independent_Code_Audit_f83aa98_2026-10-12.md`。兩者都維持未追蹤、原樣保留。

**結論**：`CORRECTION_COMPLETE — READY_FOR_INDEPENDENT_REVIEW`。方法仍為 `DRAFT_PENDING_METHOD_OWNER_REVIEW`，尚未宣稱最終驗收。

這是一次有範圍的資料完整性修正，不是重寫模型：
- Beneish 與 Dechow 兩個計分引擎、係數、轉換與 API 端點都 **未修改**；
- 修正的是送進引擎的輸入證據。

## 1. 四項發現的修正

| 發現 | 修正內容 |
|---|---|
| **LIT-F01（P1）零值與缺漏** | `sum` 規則沒有任何列示科目時，改回傳 `not_presented`，**不再是 `computed/0`**。每個已計算輸入都標示證據型別：`explicit_line`、`explicit_zero`、`presented_lines_sum`、`derived_difference` 或 `verified_zero`。零值證據政策 `literature_zero_evidence_policy_v1` 只有一條已記錄、已測試的規則，詳見表下說明。發行科目（長期借款、現金增資）**不得推論為 0**。 |
| **LIT-F02（P2）原始 PDF 恆等式閘門** | TW-GAAP PDF 萃取器 v2 保留資產負債表全部科目列，每欄計算 10 個恆等式，各自標示 `verified`／`mismatch`／`incomplete`。診斷資料記錄頁次、期間、單位、合併範圍、規則版本、原始檔 SHA、運算元與差額。恆等式不符或不完整時，**只阻擋該恆等式涵蓋的科目與該欄**。XBRL 時點值必須通過「資產＝負債＋權益」。 |
| **LIT-F03（P2）同義科目衝突** | 候選科目數值不同時，改為 `mapping_conflict`，列出全部候選與數值，**不再選清單第一筆**。數值一致的候選全部記入來源與 digest。輸入順序打亂後結果不變。 |
| **LIT-F04（P2）t−2 跨申報一致性** | t−2 取自前一年申報之前，先驗證重疊年度 t−1：兩份申報的同一科目必須相等。不一致時為 `cross_filing_overlap_mismatch`，記錄科目、期間、版本與數值；無法驗證時為 `cross_filing_overlap_unverifiable`。IFRS 轉換日期初數只用於該會計制度的第一年（FY2013），會加註並通過恆等式。 |

**特別股的零值證明規則（F01）**：

規則名稱為 `twgaap_equity_section_exhaustive_enumeration`。它在以下條件全部成立時，判定特別股為 0：
- 權益區段全部列示科目加總等於 3XXX（區段已完整列舉）；
- 加總在組裝時能重算吻合；
- 沒有 3120 或「特別股」科目。

規則版本與證據指紋都凍結進輸入 digest。

**新方法版本**：mapping v2、panel v2、zero policy v1、source gate v1、PDF extractor v2，因此產生新的 run id；XBRL 萃取器 v1 不變。

## 2. 真實資料結果（1785，皆為 hindsight=true）

**審查點名的 12 筆項目**：

| 系列 | 項目 | f83aa98 | 修正後 |
|---|---|---|---|
| latest_available | stock_issued：FY2013、14、15、16、23、24、25 | `computed/0`，無來源 | **8 筆全部 `not_presented`** |
| latest_available | long_term_debt_issued：FY2018 | `computed/0`，無來源 | （與上列合計 8 筆） |
| original_only | preferred_stock：FY2011／FY2012 的 t 與 t−1 | `computed/0`，無來源 | **4 筆 `verified_zero`** |

- `verified_zero` 的依據：權益合計 8,795,797／9,345,296／9,788,003 千元，皆已完整列舉，且沒有特別股科目。
- 8 筆 `not_presented` 中，Dechow 的 issue 指標原本就只用正向證據，因此分數不受影響。

**原始報表恆等式**：FY2011、FY2012 原始年報各 20 項恆等式（每欄 10 項 × 2 欄），**20／20 全部 `verified`**。

**同義科目**：沒有衝突；28 個輸入有兩個數值一致的候選科目。

**t−2 重疊期檢核**：
- latest_available：22 項 verified、**2 項 mismatch**；
- original_only：2 項 verified。

**修正前後分數差異**（完整表見 `literature_data_integrity_correction_evidence.json`）：

| 系列 | 模型 | 年度 | f83aa98 | 修正後 | 原因 |
|---|---|---|---:|---:|---|
| latest_available | Dechow | FY2015 | 0.890320 | **null** | 應收帳款 2014 重疊期不符：FY2015 申報 1,969,784 千元 vs FY2014 申報 1,961,884 千元 |
| latest_available | Dechow | FY2023 | 0.867745 | **null** | 總資產 2022 重疊期不符：26,569,543 千元 vs 26,600,628 千元 |
| 其他 58 格 | — | — | — | 完全相同 | 其餘 26 個分數逐位相同 |

**整體變化**：

| 項目 | f83aa98 | 修正後 |
|---|---:|---:|
| 已計算的年度×模型配對 | 28 | **26** |
| 不可計算的年度×模型配對 | 32 | **34** |
| latest_available 可比較配對 | 12（同側 7） | 10（同側 5） |

- **FY2023 的差異**：資產與負債同額減少、權益不變，型態符合追溯適用的表達變更。但目前沒有核准的「差異說明登錄」，所以 **不自動視為已解釋**。
- **原始申報系列**：Beneish FY2011 −1.730106、FY2012 −2.286269、Dechow FY2012 0.892005 都不變。Dechow FY2012 現在以有文件依據的 `verified_zero` 為基礎；若雨靚撤回該零值規則，這個分數就會變成不可計算。
- **STRICT 模式**：三個截點仍全為 null，可採納觀測值 0 筆。

**取代關係**：f83aa98 的文獻 run 只是證據檔，從未寫入結果庫。新 run 記錄了 `supersedes_run_id`：

| 系列 | 新 run | 取代 |
|---|---|---|
| latest_available | `rrun1_1648246ccaca6ea204bcd347fc83d247` | `rrun1_94c4ffe2…` |
| original_only | `rrun1_fab682f2390383952588b6b0522503ab` | `rrun1_8d74e4bb…` |

## 3. 測試（完整紀錄見 UTF-8 測試 TXT）

**執行方式**：2026-10-12 在 `d441805` 進行最終驗證，一次只跑一個重量級階段。每個階段的真實 exit code 都經 `subprocess` 擷取，shell 階段使用 `pipefail`，管線無法掩蓋失敗。

**前次中斷**：前一次全部一起背景執行的驗證，因記憶體壓力被系統中止。那份部分紀錄保留為 `previous_interrupted_run_log.txt`，**不作為驗收證據**；先前的過渡數字（後端 690／5）由下表取代。

| 階段 | Exit | 結果 |
|---|---:|---|
| A2 資料完整性測試（F01–F04） | 0 | **26 通過** |
| A3 文獻模型與 UI 串接 | 0 | **33 通過**（Enron F=2.76、Beneish −2.243743 不變） |
| A4 Phase 3–5 研究測試 | 0 | 68 通過、2 略過 |
| A5 證偽檢查 | 0 | 4 項修正撤回後皆被測試抓到；追蹤檔案未變 |
| B1 後端全套（單一行程） | 0 | **691 通過、5 略過** |
| B2 根目錄全套 | 0 | **148 通過** |
| B3／B4／B5 子集（屬 B1 的一部分） | 0 | 歷史 167／2；法說會與 JSD 151／1（JSD 檔案未變）；2330／2454 共 7 |
| B6／B7 pyarrow 23.0.1 隔離環境 | 0 | 後端 691／5；根目錄 148 |
| B8 全新 worktree（無本機資料） | 0 | 625 通過、71 略過；暫存 worktree 已移除 |
| C1 Firestore emulator（demo-fintrust） | 0 | **7 通過** |
| C3 瀏覽器 E2E（真實 FastAPI→Flask→headless Chrome） | 0 | 16 項 HTTP、9 個視圖全過；截圖重新產生 |
| C5 唯讀 preflight | 0 | 無任何寫入 |
| D1–D7 研究結果與資料不變 | 0 | 見第 4 節 |
| E1–E4 靜態與安全檢查 | 0 | ruff 7 項、bandit 5 項（皆逐項記錄，見驗證文件 §6）；pip-audit 無已知漏洞；秘密樣式掃描 0 |

**三個首次嘗試的失敗**（都已保留紀錄並重跑通過）：
- C2：emulator 結束後，其 Java 行程仍佔用 8085 埠。我只依 PID 28048 停止它，沒有使用廣泛的 kill。
- C5、D1：驗證程式本身尚未建立輸出資料夾。重跑前已確認 sidecar 數量不變。

**模擬與 emulator 分開計算**：模擬雲端測試 5 項在 B1；emulator 測試 7 項在 C1。

**未執行**：GCS emulator（環境中沒有）、live MOPS（需手動開啟）、staging／production（未獲授權）。

## 4. 資料不變與隔離

- **核准資料**：歷史 SQLite（唯讀開啟）、原始與法說會 archive、12 個 ZIP／sidecar 都未變動。與文獻模型階段前的基準比對結果為 **IDENTICAL**。
- **基礎事實數量**：234 筆事實、158 筆重編比較、67 筆 PIT 事實，皆不變。
- **文獻 sidecar**：僅新增資料。f83aa98 的 4,393 筆觀測值、33 筆診斷、1 筆萃取 run 逐位相同；新增 396 筆 v2 PDF 觀測值、33 筆診斷與 1 筆 run。舊的 PDF 觀測值保留，但新方法不讀取。
- **結果庫**：本輪 **沒有寫入**；`research_literature_scores` 仍為 0 筆。
- **f83aa98 交付檔**：43 個檔案逐位相同，包含審查 ZIP `58b2a3aa…` 與索引 `1e10762b…`。最終證據放在新資料夾 `handoff_fix_final/`。前次中斷時留下的 `handoff_fix/` 保留不動，其中的證據與最終重新產生的結果逐位相同。
- **其他邊界**：沒有 OCR、網路請求、雲端寫入或付費 API；Ethan 的 JSD 程式未修改；1785 仍不在正式半導體研究範圍內。

## 5. 需雨靚核准的方法事項（未自行決定）

1. 是否核准「權益區段完整列舉」零值規則。撤回時，特別股回到 `not_presented`，Dechow FY2012（原始申報）變成不可計算。
2. 部分加總的「科目層級列示規則」：有列示的科目相加，未列示的科目逐筆記錄。
3. 是否建立「跨申報重疊差異說明登錄」，以及需要哪些證據（例如年報的重編附註）。屆時 FY2015、FY2023 才可能恢復計算。
4. 列為負債的特別股是否需要另外對照。
5. 現金流量表科目沒有可用的恆等式，是否接受只以頁面身分驗證（單位、年度、合併）。
6. 既有事項仍待決定：Beneish 只以作者手稿驗證；COMPUSTAT→台灣科目對照（DRAFT）；IFRS 轉換日期初數。

**交付檔**：精確路徑、大小與 SHA-256 列在 `fintrust_backend/data/literature_models/LITERATURE_FIX_HANDOFF_INDEX.json` 與最終回覆中。
