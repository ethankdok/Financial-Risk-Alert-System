# Phase 1.1 資料事件結案報告（Option B）

- **決定**：使用者於 2026-10-13 明確核准 **Option B**，接受修改後的 `fintrust_backend/data/financial_pipeline.sqlite3` 作為新的本機核准基線。
- **相關紀錄（全部保留，未改寫原文）**：
  - 事件紀錄：`INTEGRITY_PHASE1_1_DATA_INCIDENT.md`
  - Stage 0 鑑識：`INTEGRITY_PHASE1_1_INCIDENT_FORENSIC_ASSESSMENT.md`
  - 本結案報告

## 1. 核准的基線

| 項目 | 值 |
|---|---|
| 新核准 SHA-256（核准前再次以 `sha256sum` 驗證） | `8734fb68bca0e6e4a741226764d03de1684a56b2fa0fad90150fb193c50f2b9f`（1,343,488 B） |
| 被取代的原始 SHA-256 | `5526d2adc20fee9253b39cafaa9bb967fb45521af20d114a003442ae840ea181` |
| 狀態 | `accepted_modified_baseline_option_B`；**不得描述為「未修改」** |
| 與事件前位元組一致 | **否**（無完全相同的備份；`no_exact_backup_found`） |
| 已逐欄位比對事件前資料 | `normalized_financial_facts` 77／148 筆完全相同；快照規則卡 22／22 相同 |
| **無法獨立驗證** | **71 筆財務事實**（主要是季度與 Workbench 未使用的科目），以及 `calculated_metrics`、`rule_results`、`analysis_runs`、`official_events`、`text_model_runs`、`text_evidence`、`analysis_snapshots` 的**內容**。事件前沒有逐列指紋，只有列數與 Phase 1 Gate 0 紀錄相同；列數相同不等於內容相同。 |
| 新增的空結構 | `official_event_sync_status`（0 列）＋自動索引；**保留，未刪除** |
| 機器可讀基線 | `fintrust_backend/tests/approved_data_baseline.json`：只更新此一檔案的 SHA-256，另記錄 12 張表的列數與逐列指紋、原雜湊、核准說明與無法驗證範圍。其他 4 個核准資料庫維持原雜湊。 |

## 2. 鑑識保全

- **位元組一致的鑑識副本**：
  - 主要：scratchpad `stage0/quarantine/`（repo 外，唯讀）。
  - 本機另一份：`fintrust_backend/data/integrity_phase1_1/incident_forensics/`（被 git 忽略，唯讀，附 `SHA256SUMS.txt`）。
  - 內容：
    - `financial_pipeline.incident_8734fb68.sqlite3`（`8734fb68…`）
    - repo 根目錄舊檔 `root_data_financial_pipeline.57b0e3a8.sqlite3`
    - 唯讀檢查結果 `sqlite_forensics.json`
    - 研究基線比對 `research_baseline_after.json`
    - 檢查程式 `forensic_sqlite.py`
- **不放入審查 ZIP**：依規定不含任何 SQLite 檔；ZIP 只包含報告與雜湊。

## 3. 防範措施（fail-before-write）

| 層級 | 內容 | 驗證 |
|---|---|---|
| 建構子防護 | `tests/protected_stores.py` 在任何測試模組載入前，包裝 `SqliteAnalysisRepository`、`SqliteCompanyMasterRepository`、`SqliteIngestionRunRepository` 的建構子：路徑在 `fintrust_backend/data` 之下就直接拋出 `ProtectedStoreWriteBlocked`，原本的建構子（mkdir、連線、schema script）**完全不執行**。 | `test_protected_store_guard.py`（10 項）。直接建構、預設 builder、FastAPI 依賴、匯入後的 router 請求、新程序都會被擋下；approved 檔的 SHA-256、mtime、`data/` 檔案清單前後不變；暫存資料庫仍可正常使用。 |
| 預設路徑隔離 | 測試 session 中 `FINANCIAL_DATABASE_PATH`、`FINANCIAL_FACT_DATABASE_PATH` 一律指向暫存目錄（測試自行設定時仍優先） | 同上 |
| 絕對基線檢查 | 後端與根目錄的 `conftest.py`：開始前任何現存的核准資料庫與 `approved_data_baseline.json` 不符時**不執行任何測試**（exit 4）；結束時檢查與開始時相同，且仍符合核准基線。 | 已在暫存 worktree 以假檔證實：後端與根目錄都以 exit 4 拒絕執行，並列出路徑與預期／實際雜湊；真實資料庫不受影響。 |
| 案例測試隔離 | `test_integrity_case_1785.py` 同時覆寫 Workbench 依賴（3a06e8a） | 已在暫存 worktree 中重現：修正前會建立預設資料庫，修正後不會 |
| E2E | Smoke 腳本一律使用 SHA 驗證的暫存副本，並明確設定 `FINANCIAL_DATABASE_PATH`；啟動前後記錄所有核准資料庫的雜湊 | Gate C 的 C3 階段 |
| 驗證流程 | 每個驗證階段前後都比對核准資料庫雜湊；一有變更立即停止 | Gate C 測試紀錄 |

## 4. 仍存在的風險（已揭露，本輪不改）

- 正式程式中，3 個 repository 與 4 個服務（`ingestion_pipeline`、`official_event_ingestion`、`official_event_batch_ingestion`、`unified_analysis_orchestrator`）在未設定環境變數時，仍會以 `./data/financial_pipeline.sqlite3` 為預設並執行 schema script。
- 7 個既有腳本也有相同預設。
- 這是既有正式行為，可能影響部署設定，所以只在**測試**加上防護；是否改成唯讀 repository 或強制明確路徑，留待後續另行授權。
