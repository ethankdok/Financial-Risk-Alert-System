# Phase 1.1 Data Incident — Stage 0 Forensic Assessment（唯讀鑑識報告）

- **日期**：2026-10-12（Stage 0 執行於 23:2x–23:5x，台北時間）
- **分支**：`feature/integrity-workbench-phase1-1-case-1785`
- **HEAD**：`3a06e8aafa0fd5fc0a18a4986cf1ccca4454e0ed`
- **狀態**：**Stage 0 完成，等待使用者決定（A／B／C）**。Gate C 維持 BLOCKED_CONSENT。
- **本次 Stage 0 的操作範圍**：
  - 沒有修改、還原、重建任何受保護資料庫，也沒有變更其 schema（無 DROP、VACUUM、改變 schema 的 PRAGMA）。
  - 沒有接受新基線，沒有雲端存取。
  - 所有 SQLite 檢查都在隔離副本上以 `mode=ro` 與 `PRAGMA query_only=ON` 執行。

## 1. 雜湊與檔案證據（全部以 `sha256sum` 唯讀計算）

| 項目 | 路徑（repo 相對） | SHA-256 | 位元組 | 時間 |
|---|---|---|---:|---|
| **核准原始檔（Phase 1 與 Phase 1.1 基線）** | `fintrust_backend/data/financial_pipeline.sqlite3` | `5526d2adc20fee9253b39cafaa9bb967fb45521af20d114a003442ae840ea181` | 1,335,296（由頁數推得：326 頁 × 4096） | 基線紀錄：2026-10-12 12:24:31 UTC 與 14:11:11 UTC |
| **目前（事件後）** | `fintrust_backend/data/financial_pipeline.sqlite3` | `8734fb68bca0e6e4a741226764d03de1684a56b2fa0fad90150fb193c50f2b9f` | 1,343,488 | 修改：2026-10-12 22:35:20.0019 +0800；建立：2026-09-01 01:00:30 +0800 |
| 根目錄舊檔（非本事件） | `data/financial_pipeline.sqlite3` | `57b0e3a83c008af761a0fb896c6e5553904143219d2f68a70166c3f085eee8d4` | 102,400 | 修改與建立：2026-09-15 11:46:58 +0800 |

- 已證實使用者的對應正確：`8734fb68…` 是 `fintrust_backend/data/…`；`57b0e3a8…` 是 repo 根目錄 `data/…`。兩者都不是 `5526d2ad…`。
- 兩個檔案都沒有 `-wal`、`-shm`、`-journal`；Git 沒有追蹤任何 `.sqlite3` 或 `.db`（被 `.gitignore` 排除），因此 Git 物件中沒有備份。
- **受保護檔案全面重算**：

  | 基線 | 檔案數 | 清單 SHA-256 | 不符 |
  |---|---:|---|---|
  | Phase 1 | 1,942 | `798242b8…` | 只有上述檔案 |
  | Phase 1.1 | 2,027 | `39507a69…` | 只有上述檔案 |

- **核准研究資料**（`scripts.research_baseline --compare`，以 `mode=ro` 開啟）：**IDENTICAL**。涵蓋 16 張表的逐列 digest、12 個 ZIP／sidecar、274 個原始檔、4,735 個法說會檔。文獻輸入庫、研究結果庫、歷史稽核庫、法說會 PDF 封存、JSD 校準檔、先前交付 ZIP 都未變更。
- **執行中程序**：唯一的 `python.exe`（PID 11288）是 `pip install esptool`，與本 repo 無關，未予停止。

## 2. 鑑識保全

- 以檔案系統複製（不經任何應用程式 repository）保全到 repo 外的隔離目錄（scratchpad `stage0/quarantine/`），並設為唯讀：

  | 副本 | SHA-256 | 與來源一致 |
  |---|---|---|
  | `financial_pipeline.incident_8734fb68.sqlite3` | `8734fb68…` | 是 |
  | `root_data_financial_pipeline.57b0e3a8.sqlite3` | `57b0e3a8…` | 是 |

- 所有 SQLite 檢查都在另一份工作副本上進行；檢查前後雜湊都是 `8734fb68…`，原檔也維持 `8734fb68…`。

## 3. 原始檔備份搜尋（只比對完整 SHA-256）

| 搜尋範圍 | 方法 | 結果 |
|---|---|---|
| Git 物件 | `git ls-files` | 沒有追蹤任何 SQLite → 無 |
| 同 repo 資料夾 | 2,027 檔基線重算 | 只有事件檔 |
| 第二份 clone `C:\Users\samue\Financial-Risk-Alert-System` | 直接檢查 | 舊 `main`（`34eb1ef`），沒有任何 `.sqlite3` |
| 所有 ZIP（Documents、Downloads、Desktop、第二份 clone、Claude 暫存，共 339 個） | 只列出成員，不解壓 | 338 個可讀，**沒有 SQLite 成員**（只有檔名含 `financial_pipeline` 的 `.py` 腳本）；1 個 Downloads 檔不是有效 ZIP（BadZipFile） |
| 整個使用者目錄與資源回收筒 | 只讀 metadata，搜尋大小 1,335,296／1,343,488 或檔名 `*financial_pipeline*`、`*pipeline*.sqlite3*`；候選檔再算完整 SHA-256（OneDrive 雲端預留位置不讀取） | 見 §3.1 |
| Windows 陰影複製 | `Win32_ShadowCopy` | 無系統管理員權限無法查詢；**未提權** |
| 檔案歷程記錄 | 登錄機碼 | 此使用者未設定 |
| 雲端備份（OneDrive／GCS／部署） | — | **未存取**（需你明確授權） |

### 3.1 搜尋結果：`no_exact_backup_found`

- **針對性 metadata 搜尋**（PowerShell `Get-ChildItem`，只讀 metadata，排除 node_modules／.venv／site-packages）：
  - 範圍：OneDrive（本機檔案）、Documents、Desktop、Downloads、第二份 clone、資源回收筒。
  - 找到 18 個候選，**沒有任何 pipeline 資料庫的其他副本**。其餘都是不同的資料庫：smoke／member／validation、歷史稽核庫與其 4 個 phase 備份、研究結果庫、文獻輸入庫；另有同名的 `.py` 腳本。
- **完整 SHA-256 比對**：對 repo `data/` 與所有 Claude 暫存區（含其他 session）中的每一個 `.sqlite3`／`.db`／`.sqlite`，以及大小為 1,335,296 或 1,343,488 的檔案，共計算 **28 個檔案**的完整 SHA-256。**與 `5526d2ad…` 完全相符：0 個。**
  - `scratchpad/phase1_db_backup.sqlite3`（212,992 B，`67ee938a…`）是早期歷史稽核庫，不是 pipeline 資料庫。
  - Phase 1 的暫存副本 `p1/pipeline_copy.sqlite3` 為 `8734fb68…`：它在 Phase 1 由同一建構子開啟過一次，這也證實「原檔開啟一次」會產生完全相同的結果。
  - 另一個 session 的 `e2e/pipeline.sqlite3`（196,608 B，`588fc43c…`）是 E2E 用的空庫，不相符。
- **完整使用者目錄 `find` 掃描（含 AppData）**：執行約 45 分鐘仍未結束，**已由我停止**，以免遺留背景程序（只停止我自己的 find.exe，PID 4176）。因此 AppData 中**非 Claude 暫存**的區域只完成部分掃描，屬**未完全涵蓋**。若你要求，可以在你指定的範圍內重新執行。
- **未涵蓋、需你提供或授權**：其他電腦、外接磁碟、雲端（OneDrive 線上、GCS、部署機）、系統管理員層級的陰影複製。

## 4. 唯讀 SQLite 檢查（隔離工作副本）

| 檢查 | 結果 |
|---|---|
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | 無違反（12 張表都沒有宣告外鍵） |
| 物件 | 12 張表、15 個索引、0 個 trigger、0 個 view |
| 原 11 張表的列數 | 與 Phase 1 Gate 0 唯讀紀錄**全部相同**（facts 148、filings 7、runs 5、metrics 395、rule_results 100、latest snapshots 2、official_events 7、snapshots 1、text_model_runs 1、text_evidence 150、companies 0） |
| 欄位定義 | Gate 0 有紀錄的 4 張表（facts、filings、official_events、analysis_runs）**完全相同** |
| 多出的物件 | `official_event_sync_status`（0 列，PRIMARY KEY (ticker, event_type, coverage)）＋ `sqlite_autoindex_official_event_sync_status_1`，位於第 327–328 頁；**未刪除** |
| 檔頭 | 4096 B／頁；328 頁；change counter 36；schema cookie 22；freelist 0；SQLite 3.50.4 |
| **與事件前資料逐列比對** | 參考檔：`integrity_phase1_real_outputs.json`（SHA-256 `0f54de61…`），於 13:19:41 UTC 由「已驗證等於 `5526d2ad…`」的副本產生。<br>**77／148 筆 facts 每個欄位都相同**（數值、單位、期間、科目、來源 URL、擷取時間、XBRL 概念），**0 筆不符**。<br>2330／2454 快照的 22 張規則卡與 `data_updated_at` 也相同。 |
| 無法證明的部分 | 其餘 71 筆 facts（主要是季度與 Workbench 未使用的科目）、`calculated_metrics`、`rule_results`、`analysis_runs`、`official_events` 內容、`text_*`、snapshot 歷史：**事件前沒有逐列指紋，無法證明未變**。列數相同不等於內容相同。 |

### 四個面向的結論分開陳述

1. **位元組一致**：**失敗**（`8734fb68…` ≠ `5526d2ad…`），且無法還原（§6）。
2. **邏輯內容**：部分已證明（77 筆 facts、22 張規則卡逐欄位相同）；其餘無法證明。
3. **Schema 差異**：多一張空表與一個自動索引；原有表的欄位與列數相同。
4. **測試輸出**：2330／2454／3711 的 Workbench 輸出與已驗收的 `0c51a74` 逐欄位相同（Gate A G1，於事件後執行）。

### 目前內容的逐列指紋（若選 B，可作為新基線；不能證明事件前內容）

| 表 | 列數 | 排序後逐列 SHA-256 |
|---|---:|---|
| `analysis_runs` | 5 | `2096a89f9c75cc33a8731a887804d783c5899de7417e8ab7682f0fd7dd9298bd` |
| `analysis_snapshots` | 1 | `65934e16eceb7abcefdfac94d4fc174c15d713d554b49ad76d565ef5da83f284` |
| `calculated_metrics` | 395 | `aa22f9b851957514254d0aed05ec001c48ff32abd627d7ec9a591953ccef238a` |
| `companies` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `financial_filings` | 7 | `538ced294674c005adfdf31fb2f2606f6ba9a72694dddb87acde26cf34ee4bcb` |
| `latest_analysis_snapshots` | 2 | `ead933a8d17e49d8381c03a065d2cd5c1c5c14aaee3a34504b6116488364a6b2` |
| `normalized_financial_facts` | 148 | `5c23a2e78ce2f7206cfb2c60747a64234b07621b20854feea94df098a2bed47c` |
| `official_event_sync_status` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `official_events` | 7 | `c1fe8df9657a359a1b9b791e8cb0fde56a63530c0b17cf6bd10d71cda5e533cd` |
| `rule_results` | 100 | `a233a919cda45da27a843468d8e3f72d8087e292722c17581a60e058c21423ad` |
| `text_evidence` | 150 | `e0c9254fd723747692314027eaadefed4ecae891de9b7890e15cdbc7d5460f11` |
| `text_model_runs` | 1 | `7ef6148a3dc2d7a13868fd5771d73bbf7a200d1b2685824ca45a26420fdc600d` |

## 5. 根本原因（已在隔離環境重現並驗證）

- **寫入機制**：
  - `app/dependencies.get_analysis_repository()` → `build_analysis_repository()` → `SqliteAnalysisRepository(os.getenv("FINANCIAL_DATABASE_PATH", "./data/financial_pipeline.sqlite3"))`。
  - 建構子執行 `mkdir` 與 `_init_schema()`：`CREATE TABLE IF NOT EXISTS …` 加上欄位遷移，然後 commit。
  - 原檔沒有 `official_event_sync_status`，因此被建立。
- **觸發的測試**：`tests/test_integrity_case_1785.py::CaseApiChainTests::test_api_contract_and_errors`（commit `a2ec6ef`）。它對 1785 呼叫 CURRENT_REVIEW 預覽以證明回 404，但只覆寫了 `get_research_service`，沒有覆寫 `get_integrity_workbench`。
- **時間**：檔案 mtime 22:35:20（台北）＝ 14:35:20 UTC，是 Gate B 開發中第一次手動執行該測試；早於所有分階段執行（14:38 起）。之後同一路徑再被開啟，位元組與 mtime 都沒有再改變。
- **重現**：在暫存 worktree 中只執行該測試節點，真實資料庫前後都是 `8734fb68…`。

  | commit | 測試結果 | 是否建立預設資料庫 |
  |---|---|---|
  | `a2ec6ef` | **通過** | 在 worktree 的 `./data/` 建立了預設資料庫（110,592 B，含 `official_event_sync_status`）——測試通過卻寫入了資料 |
  | `3a06e8a`（已修正） | 通過 | **沒有建立**任何資料庫 |

- **其他潛在寫入者**（本次未觸發，但風險相同）：
  - `company_master_repository` 與 `ingestion_run_repository` 預設同一路徑，建構時也會執行 schema；
  - 預設建立 repository 的服務：`ingestion_pipeline`、`official_event_ingestion`、`official_event_batch_ingestion`、`unified_analysis_orchestrator`；
  - 7 個預設寫入此路徑的腳本，其中包括 Phase 1 的 `integrity_phase1_smoke.py`（它刻意改用 SHA 驗證的副本）。
- **其他使用 FastAPI 的測試**：沒有隔離標記的 4 個檔案中，`test_phase15_release_readiness` 只呼叫 `/ai/health` 與 `/ai/rules`（不建立 repository），其餘 3 個覆寫了相關服務。Phase 1 的完整後端測試前後，此檔雜湊未變（Phase 1 D1／D4 通過）。

## 6. 為何無法還原（`no_exact_backup_found`，完整搜尋結果見 §3.1）

- 第 76 頁（`sqlite_master` 的葉頁）中兩筆新的 schema 列覆寫了頁內原有的殘留位元組（gap 區與 free block 尾端），SQLite 不會清零這些區域。
- Phase 1.1 執行期間，我在暫存副本上以原始雜湊檢驗了 288 種重建假設，**沒有任何一種相符**。依本規格不再嘗試重建或修補位元組。

## 7. 現有防護與建議（Stage 1 才實作）

- **`tests/conftest.py`（3a06e8a）的實際能力**：
  - 只比較**同一次測試 session 前後**的雜湊，**不比對核准的絕對基線**。目前檔案已是 `8734fb68…`，它會照常通過；它無法偵測已經發生的事件。
  - 它是事後偵測，不是事前阻止：寫入發生後才讓整次 session 失敗。
  - 已在暫存專案證實它會在 session 結束時以 exit 1 標出變更。
- **建議 Stage 1 實作**：
  1. 在 import app 之前，以 session 範圍、自動套用的 fixture 把 `FINANCIAL_DATABASE_PATH` 設為暫存檔，並清除相關 `lru_cache`。
  2. 在測試中包裝 `SqliteAnalysisRepository`／`CompanyMasterRepository`／`IngestionRunRepository` 的建構子：解析後的路徑若位於 `fintrust_backend/data/` 之下，**在任何寫入前就拋出例外**（fail-fast）。並加入「刻意建立預設資料庫必須被擋下」的負向測試。
  3. 讓 session 防護同時比對本次 session 前後的雜湊與**明確核准的基線檔**（你選 A 或 B 後才寫入）。
  4. Demo 與 smoke 一律使用「SHA 驗證的副本」並明確設定 `FINANCIAL_DATABASE_PATH`；需要真正唯讀時，改用不跑 schema 的唯讀 repository（`mode=ro`＋`query_only`）。不在有 WAL 時使用 `immutable=1`。

## 8. 待決定

見回覆中的 A／B／C。在明確授權前：不還原、不覆寫、不修改 schema、不更新基線清單；Gate C 維持 BLOCKED_CONSENT。

## 9. 決定紀錄（2026-10-13 附記，以上內容未改動）

- 使用者明確核准 **Option B**：接受 `8734fb68bca0e6e4a741226764d03de1684a56b2fa0fad90150fb193c50f2b9f` 作為新的本機核准基線。核准前已再次驗證這個雜湊。
- 結案、防範措施與無法驗證的範圍見 `INTEGRITY_PHASE1_1_INCIDENT_CLOSURE.md`。
