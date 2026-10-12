# Phase 1.1 事件紀錄：受保護資料庫在測試中被改寫（2026-10-12）

> 狀態：**未解決，等待使用者決定**。這是 Gate C「受保護資料不得變更」的失敗，不以測試通過掩蓋。

## 1. 發生了什麼

| 項目 | 內容 |
|---|---|
| 檔案 | `fintrust_backend/data/financial_pipeline.sqlite3`（本機正式管線資料庫，2330／2454） |
| 原始 SHA-256（Phase 1.1 開工前基線，14:11:11 UTC） | `5526d2adc20fee9253b39cafaa9bb967fb45521af20d114a003442ae840ea181` |
| 目前 SHA-256 | `8734fb68bca0e6e4a741226764d03de1684a56b2fa0fad90150fb193c50f2b9f` |
| 變更時間（檔案 mtime） | 2026-10-12 14:35:20 UTC，即 Gate B 開發中第一次手動執行 `tests/test_integrity_case_1785.py` |
| 其他受保護檔案 | 2,027 個基線檔案中**只有這一個**不同；核准研究資料比對（tables、ZIP／sidecar、原始與法說會封存）為 IDENTICAL |

## 2. 原因（本人的測試缺陷）

- `CaseApiChainTests.test_api_contract_and_errors` 為了證明 CURRENT_REVIEW 對 1785 回 404，送出 `/api/v1/integrity/assessments/preview`。
- 但測試只覆寫了研究服務的依賴，沒有覆寫 Workbench 依賴。於是 FastAPI 建立了預設的 `get_analysis_repository()` → `SqliteAnalysisRepository("./data/financial_pipeline.sqlite3")`。
- 既有的 repository 建構子會執行 schema script 並 commit（Phase 1 Gate 0 已記錄此既有行為）。
- 這次它在原檔中建立了一張原本不存在的**空表** `official_event_sync_status` 與其自動索引（第 327、328 頁），並更新了檔頭計數器與 schema cookie。

## 3. 影響範圍（唯讀鑑識，只在暫存副本上進行）

- 原有 11 張資料表的列數與 Phase 1 Gate 0 唯讀紀錄完全相同：facts 148、filings 7、runs 5、metrics 395、rule_results 100、snapshots 2＋1、official_events 7、text_model_runs 1、text_evidence 150、companies 0。
- 新增表為空（0 列）。
- 2330／2454／3711 的 Workbench 結果與已驗收的 0c51a74 輸出逐欄位相同（G1）。
- 同一路徑後續又被開啟數次（14:38–14:41），位元組與 mtime 都沒有再改變；確實只有一次寫入。

## 4. 為何無法自行還原成原始位元組

- 本機沒有任何 `5526d2ad…` 的副本。Phase 1 的暫存副本也曾被同一建構子開啟過一次，所以同樣是 `8734fb68…`。
- 我以已知的原始雜湊檢驗 288 種重建假設：回收兩個新頁、還原儲存格數、content start、free block 大小、檔頭計數器，並將被覆寫的區域試為原值或零。**沒有任何一種相符。**
- 原因是新的 schema 列覆寫了頁內原有的殘留位元組；SQLite 不會清零這些位元組，舊內容無法從檔案本身推回。
- 我**沒有**執行 `DROP TABLE` 或其他「修補」：那只會再改一次檔案，也不會得到原始位元組。

## 5. 已完成的防範

1. 測試隔離：`test_integrity_case_1785.py` 的 API 測試同時覆寫 Workbench 依賴（改用合成資料）。
2. 新增 `fintrust_backend/tests/conftest.py` 的 session 防護：每次測試開始與結束時雜湊 4 個核准資料庫。任何變更都會使整次測試以失敗結束並列出檔名。
   - 已在暫存專案中證實：測試本身通過，session 仍以 exit 1 結束並指出被改的檔案。

## 6. 需要使用者決定

- **A**：從你自己的備份（其他電腦、雲端或部署來源）還原 `5526d2ad…` 原檔。還原後我會在 Gate C 重跑全部驗證。
- **B**：接受目前狀態（原有資料不變，只多一張空表與檔頭變更），以 `8734fb68…` 作為新基線，並把此事件列入審查紀錄。

在你決定之前，Gate C 維持 **FAIL（受保護資料變更）**，不產生「全部通過」的交付。

## 7. 狀態更新（2026-10-13，以上原文保留）

- Stage 0 唯讀鑑識已完成：`INTEGRITY_PHASE1_1_INCIDENT_FORENSIC_ASSESSMENT.md`，結論為 `no_exact_backup_found`。
- 使用者明確核准 **Option B**，以 `8734fb68…` 作為新的本機核准基線；此檔仍屬「已修改」，不得描述為未修改。
- 結案與防範措施：`INTEGRITY_PHASE1_1_INCIDENT_CLOSURE.md`。
