# FinTrust Phase 3–5 集中除錯最終報告（供最終獨立驗收）

**審查對象 commit**：`e4fb1e7943dc59680f087b6e6b3f3abd8590566a`
**分支**：`feature/phase3-5-research-integration`（僅本機；未 push、merge、PR、部署）
**除錯 commit**：
- `612c517`：程式修正與測試
- `ed2d5c2`：文件與驗收矩陣
- 本報告 commit

**最終 HEAD 與所有交付檔的路徑、大小、SHA-256**：見 `fintrust_backend/data/phase3_5/DEBUG_HANDOFF_INDEX.json`，以及 review ZIP 內的 `PROVENANCE.json`。

**規格輸入**：`docs/development/FinTrust_Phase3-5_Consolidated_Debug_Prompt_2026-10-11.md`（未追蹤，原樣保留）。指令中寫的路徑 `PHASE3_5_CONSOLIDATED_DEBUG_PROMPT.md` 並不存在，實際讀取的是上述檔案。

**結論**：`DEBUG_PASS_COMPLETE — READY_FOR_FINAL_INDEPENDENT_ACCEPTANCE`

## 1. 四項發現：修正前後重現

由 `docs/development/evidence/phase3_5_debug_repro.py` 重現：「修正前」在 `e4fb1e7` 的臨時 worktree 中執行，「修正後」在目前工作樹執行，兩者各用獨立 interpreter 載入各自未經修改的模組。

| 發現 | 審查者案例 | 修正前 | 修正後 |
|---|---|---|---|
| P1-F01 | TPEx 摘要 100 → 200 | input digest 不變，但 output 改變（寫入時觸發確定性衝突） | input digest 與 run_id 都改變；相同輸入得到相同 run_id 與 output digest |
| P1-F02 | 公告 TIFRS vs XBRL `WRONG_FRAMEWORK`，金額相同 | `match`，無原因 | `not_comparable`（`framework_mismatch`） |
| P2-F03 | PDF 單位未驗證，100 vs 100,000 元 | `equals_*=True` | `not_comparable`（`unit:unit_unverified`），相等欄位為 null |
| P2-F04 | config prefix `historical_research_staging_abc` | `historical_research_results` | `historical_research_staging_abc_results` |

**修正方式：**
- **F01**：
  - 比對開始前先凍結所有依賴（`freeze_dependencies`）：TPEx 摘要的唯讀視圖（不含擷取時間），以及 PDF 證據。PDF 證據若可取得，記錄版本、重新驗證過的 SHA-256、頁碼、擷取到的行與身分檢查；若不可取得，則明確記為 unavailable 並附原因。
  - 這些依賴與 parser 版本都納入 `input_digest`／`run_id`，並逐項提供 `dependency_digests`；`reconcile()` 只讀取凍結後的輸入。
  - 獨立的來源比對 run，以及 RECON 模式下的 `financial_signals` run 都適用。STRICT／RETRO 的 digest 不變，既有三個 run 驗證仍為 `reproducible`。
- **F02**：任何不確定都 fail closed，回傳 `not_comparable` 並附原因。檢查項目：
  - 完整年度期間；
  - 準則已知，且與該年度適用的準則一致；
  - 版本：重編比對要求 restated；董事會公告比對要求非 restated，且為年度決議公告類型；
  - 單位可換算；
  - 正負號為 ±1；
  - 重編後一側的標籤與值都存在；
  - 公告可得時間已驗證。
- **F03**：
  - PDF 只選取版本類型與 XBRL 相同、且唯一的合併年度 PDF；不再依排序挑選，有歧義或無相符版本時回報 unavailable。
  - 重新計算 SHA-256；檢查單位（新台幣千元）、年度（民國 114 年 = FY2025）與合併範圍。
  - 三項檢查都驗證通過才比較相等。
- **F04**：結果命名空間改為由 config 推導：`<collection_prefix>_results`；只允許 emulator 與 isolated-test，其他環境一律拒絕。

## 2. 同輪加固

1. **既有端點**：路由、模式、狀態碼都不變；API → Flask → UI 鏈結測試通過。
2. **Flask 靜態路由**：保留 `0427418` 的修正，另外拒絕以下檔名：
   - 含 `backup`、`_before_`、`.bak`、`.orig`、`.tmp`、`~` 的備份或暫存檔；
   - 含 `:`、`%` 或 NUL 的路徑。

   新增測試涵蓋：編碼路徑跳脫、雙重編碼、反斜線、`::$DATA`、NUL、備份檔。另驗證根目錄的 html／js／css 全部是 git 追蹤的網站檔，且都能正常存取。
3. **一致性狀態**：所有項目都不可比較時，回報 `INCONCLUSIVE_NOT_COMPARABLE`（UI：「無可比較項目（不判定一致）」），不再顯示 CONSISTENT。
4. **pyarrow（PYSEC-2026-113）**：
   - 宣告範圍改為 `pyarrow>=23.0.1,<24.0`。
   - 在隔離 venv（pyarrow 23.0.1、pandas 2.3.3）中，根目錄 148 項、後端 632 通過／5 略過，含 Ethan 使用 parquet 的路徑。
   - 本機既有 `.venv` 仍是 22.0.0，未變更；依 requirements 重裝即會升級。
5. **lint**：沒有宣稱零警告。測試紀錄中的 ruff 為 49 項（若加入重現腳本則為 51 項：行長、FastAPI `Depends` 慣用法、固定表名），bandit 2 項（既有 `debug=True`、一項誤報），都逐項列在 `PHASE3_5_DEBUG_PASS_VALIDATION.md`。
6. **研究方法與 JSD**：方法仍為 DRAFT（待雨靚核准）；Ethan 的 JSD 演算法與就緒規則未改。

## 3. 真實資料基準（全部保留）

| 項目 | 結果 |
|---|---|
| 財務事實 | 234 |
| 重編對照 | 158 |
| 嚴格 PIT 事實 | 67 |
| 董事會公告 vs XBRL | 40 一致 / 2 差異待查證 / 18 不可比較 |
| 重編公告（重編後）vs 重編 XBRL | 27 一致 / 0 差異 / 67 不可比較（無對應申報事實；修正前是靜默略過，現在明確列出原因） |
| TPEx 摘要 | 0 / 0 / 45 |

**FY2025**：
- 總資產與總負債各差 1,721 千元；
- PDF 為版本 `hfv1_8fa5f75c…`、SHA `fc715140…`、第 8 頁、民國 114 年，三項身分檢查都通過；
- 原因未證實，沒有舞弊標籤，也不轉入風險分數。

**舊 run 的處理**：修正前的 RECON run（`rrun1_9caed…`）保留不改，驗證結果顯示 `inputs_changed_since_run`；已另存 v2 run `rrun1_07df8c75…`（來源比對）與 `rrun1_23dec6da…`（RECON 訊號），只附加、不覆寫。

**資料不變性**：`research_baseline --compare` 結果為 **IDENTICAL**：16 張核准表、12 個既有 ZIP／sidecar、raw archive 274 檔、法說會 archive 4,735 檔都未變。1785 仍不在正式公司清單與 refresh 範圍內。

## 4. 測試（分層，於 `ed2d5c2` 執行；本報告 commit 只新增文件）

| 層級 | 結果 |
|---|---|
| 後端全套（unit／fixture／mock／real） | **632 通過、5 略過** |
| 根目錄（Flask／前端） | **148 通過** |
| Phase 3–5 研究與除錯測試 | 68 通過、2 略過（emulator 專屬） |
| 歷史資料子集 | 167 通過、2 略過 |
| 法說會／JSD | 151 通過、1 略過 |
| 2330／2454 | 7 通過 |
| pyarrow 23.0.1 隔離 venv | 根目錄 148 通過；後端 632 通過、5 略過 |
| 全新 worktree（無本機資料） | 578 通過、59 略過（真實資料層照預期略過） |
| **Firestore emulator**（firebase-tools 13 / emulator v1.19.8，`demo-fintrust`） | 7 通過（3 項 emulator 層 + 4 項 mock） |
| **E2E**（真實 FastAPI 與 Flask 程序、本機 HTTP、headless Chrome） | 六個視圖截圖與 DOM 檢查全部通過；瀏覽器端無法儲存結果；FastAPI 與 Flask 回應一致 |
| 唯讀 preflight | 全部通過，沒有任何寫入 |
| pip-audit | 兩份 requirements 都沒有已知漏洞 |
| 秘密掃描（diff） | 0 |

**略過原因**：
- emulator 專屬測試在一般執行中略過，已另以 emulator 實跑；
- live MOPS 測試需手動開啟；
- reportlab fixture 缺少套件。

**未執行**：GCS emulator（沒有可用工具）；任何 live／staging 雲端操作。

## 5. 交付檔

完整絕對路徑、大小與 SHA-256 見 `DEBUG_HANDOFF_INDEX.json`，最終回覆也會一併列出：
- review ZIP
- 本報告
- UTF-8 測試紀錄
- validation 文件
- 驗收矩陣 v2
- API 契約與 OpenAPI
- 研究 fixture
- 瀏覽器截圖與 DOM

## 6. 剩餘事項（需另行決定）

- 方法核准：雨靚。
- staging 研究資料來源，以及任何雲端或正式環境操作的授權。
- 本機 `.venv` 可依 requirements 重裝，把 pyarrow 升到 23.0.1。
- 既有資料限制延續：XBRL 公開時間未驗證、FY2025 差異原因未明、FY2016 EPS 比較數差異。
