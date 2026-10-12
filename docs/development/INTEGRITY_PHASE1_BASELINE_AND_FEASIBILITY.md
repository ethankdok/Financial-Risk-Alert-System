# Financial Integrity Workbench Phase 1 — Gate 0 基線與可行性（2026-10-12）

> 唯讀盤點紀錄。所有「可用」都已用本機實際資料或既有服務在程序內試跑確認；沒有 live MOPS、沒有雲端、沒有 LLM。

## 1. Git 與安全前提

| 項目 | 值 |
|---|---|
| 起點 | `feature/literature-models-beneish-dechow` @ `872c85675424a41b45860b9f21381f08185350dd`（與規格預期相同） |
| 新分支 | `feature/integrity-evidence-workbench-phase1`（`git switch -c`，未 checkout／clean／reset；未覆蓋任何既有分支） |
| 上游 | `origin` = GitHub；**未 push／merge／PR** |
| 使用者未追蹤檔 | 10 個 `docs/development/*` 指令與審查檔、`phase3_5_handoff/`：保留未動、未納入 commit |

## 2. 受保護資料雜湊基線（實作前，2026-10-12 12:24:31 UTC）

- 共 **1,942 個檔案**：`data/official-ir-pdfs-live-test/`（全部 PDF／txt／pages／analysis／semantic／manifest）、`data/literature_models/`（含 f83aa98／df0fc44／872c856 交付檔與 ZIP）、`data/phase3_5/`、`data/jsd-corpus/`、`app/calibration_profiles/`、`data/*.sqlite3`、`data/historical_audit/*.sqlite3`、`data_shift.py`、`financial_risk.db`。
- 清單檔 SHA-256：`798242b8dcbd6e5f5b367320fd9f12d6db7eaaff2cbd29c204b8966e6faf556`（逐檔雜湊存於交付 ZIP 的 `baseline/protected_before.sha256`）。

| 關鍵檔 | SHA-256 |
|---|---|
| `data/financial_pipeline.sqlite3`（正式管線，本機） | `5526d2adc20fee9253b39cafaa9bb967fb45521af20d114a003442ae840ea181` |
| `data/literature_models/literature_inputs.sqlite3` | `b8bc1424b1c97dac53fca5656fe36082bdaca3d6a00be6af5feff6bd8207cf0c` |
| `data/historical_audit/research_results.sqlite3` | `b4cd8d438944dd41ecb995b2a66b5843e17346335e7ea47bde258eff6deb2ff9` |
| `data/historical_audit/historical_audit.sqlite3` | `43dbd37716c056ea324784e03441ff84b04e3192ba338d547825f86723b740f9` |
| `data_shift.py`（Ethan JSD 計算器，未修改） | `cfefb0dd2ff29b090dcd05e262bcecaa85464c8c759fd34d0b088775eabdf36c` |
| `app/calibration_profiles/jsdcal-2330-…json` | `233114d483689cd49173685c9dd140f42eff5666ccf79621c8c20b8257c789cf` |
| `official-ir-pdfs-live-test/2454/2025/manifest.json` | `a7b173d850fcbfb2ff68f9eef4382e6a4cec900e360b7d92630badc3148197ff` |
| `official-ir-pdfs-live-test/2330/2025/manifest.json` | `bf577cd86efe57713b618b3e9df92926706dd7fd5333632ff989c7a464d49c43` |
| R01/R02 審查 ZIP（872c856） | `933ef79269a0423834424e63a7f48a1b04cf30edff66694406661104eda56958` |

**Gate 0 發現（既有行為，未修改）**：`SqliteAnalysisRepository.__init__` 每次開啟都執行 schema script 並 commit，即使只讀也會改寫 SQLite 檔頭的 change counter（第 28 位元組）。因此所有 smoke／E2E／REAL 測試都改用「SHA 驗證完全相同的暫存副本」，原檔在物理上不可能被改；原檔雜湊於前後比對。

## 3. 介面盤點（只讀、是否有副作用）

| 介面 | 結論 | Phase 1 用法 |
|---|---|---|
| `AnalysisRepository.list_facts / get_latest_snapshot / list_material_events` | 讀取（sqlite 開檔會 commit schema，見上） | `FactsAdapter`、`OfficialSourcesAdapter` |
| `/companies/{t}/facts`、`/metrics`、`/rule-results`、`/analysis/latest` | 讀取 persisted 資料 | 不經 HTTP，改以 DI 重用同一 repository |
| `OfficialEvidenceService.build(fetch_conference_live=False)` | 只讀 | 規則訊號、重大訊息、官方來源（live 強制關閉） |
| `OfficialEvidenceCardBuilder` | 若設定 `TEXT_EMBEDDING_PROVIDER`／`CONFERENCE_DIGEST_LLM_PROVIDER` 會呼叫 Gemini；`extract_documents=True` 會抓文件 | **不在同步請求中呼叫**；改用上列唯讀服務 |
| `ClaimVerificationService` + `ClaimEvidenceAdapter` | 決定性比對；LLM 僅在設定 Gemini 時啟用 | 以 `llm=None` 重用 |
| `verifier.MONEY_SCALES` | **缺 `新台幣元`**：MOPS XBRL 事實（單位 新台幣元）與任何金額主張都無法比較 → 永遠 `insufficient_evidence` | 最小修正：加一行 `"新台幣元": 1.0`（見最終報告） |
| `claim_parser` | 既有缺陷：`新台幣5,305.86億元` 被解析為 305.86（千分位逗號）→ 可能誤判 `conflicting` | **未修改**；主張登錄檔去除千分位，且 adapter 比對解析結果與預期值，不一致即 `inconclusive` |
| `JsdBridgeService.analyze` | 只讀；Ethan 計算器 SHA 驗證後載入；未校準時回 raw JSD/Cosine | `JsdAdapter` 重用，並獨立重驗配對相容性 |
| 文獻：`beneish_1999.evaluate`、`dechow_2011.evaluate`、`literature_inputs.Panel` | 純函式 | 以空面板（無凍結輸入）呼叫未修改引擎 → `not_computable` + 完整缺漏清單 |
| `/official-documents/extract`、`/facts/ingest`、`refresh`、`narrative/persist` | 寫入路徑 | **完全不呼叫** |

## 4. 公司 × 模組可行性

| 公司 | 模組 | 來源 | 期間 | 口徑 | 來源識別 | PIT metadata | 可用 | 原因 | Demo |
|---|---|---|---|---|---|---|---|---|---|
| 2454 聯發科 | F1 營收／應收 | MOPS Inline XBRL（t164sb01, report_id=C） | FY2022–FY2025 | 合併（由 report_id=C 推得） | `mops_t164sb01:<年>:S4:C:as_retrieved` | 發布時間**未記錄**（`filed_at` 空） | ✅ | 4 年同口徑 | **主 Demo** |
| 2454 | F2 淨利／營業現金流 | 同上 | FY2022–FY2025 | 合併 | 同上 | 未記錄 | ✅ | | 主 Demo |
| 2454 | F3 主張 | 4Q24 法說會簡報 `245420250207E001.pdf` 第 15 頁（SHA `c500c62f…`） | FY2024 | 簡報表頭 Consolidated（未查核） | 檔案 SHA + 頁碼 + 原文 | 日期精度（2025-02-07） | ✅ | 原文與頁碼每次請求重驗 | 主 Demo |
| 2454 | JSD | 2025Q2→2025Q3 英文 earnings_presentation | 相鄰季 | — | 文件 SHA | — | ✅ raw；**未校準** | 無 2454 校準檔 | 主 Demo |
| 2454 | 文獻模型 | 文獻輸入庫 | — | — | — | — | ❌ `not_computable` | 無凍結文獻輸入（只有 1785 研究案例） | 顯示缺漏 |
| 2454 | F4 Brazel NFM | — | — | — | — | — | ❌ | 無經驗證之員工數／產能序列 | readiness only |
| 2330 台積電 | F1／F2 | MOPS Inline XBRL | FY2022–FY2024 | 合併 | 同上 | 未記錄 | ✅ | | 輔助 |
| 2330 | F3 主張 | 4Q24 簡報 `233020250116E001.pdf` 第 11 頁（SHA `24240a79…`） | FY2024 | 簡報摘要 | 同上 | 日期精度（2025-01-16） | ✅ | | 輔助 |
| 2330 | JSD | 2025Q2→2025Q3 英文簡報 | 相鄰季 | — | — | — | ✅ raw；未校準 | 現有 2330 校準檔為不同文件類型／語言／方法（transcript calibration ≠ MOPS 簡報） | 輔助 |
| 2303、3711 | 全部 | — | — | — | — | — | ❌ | 無已歸檔快照 | 示範 fail-closed（`insufficient_evidence`） |
| 1785 | — | 歷史研究案例 | — | — | — | — | 不在 Workbench | 非正式公司；回 404，文獻研究結果不被引用 | 不使用 |

季度資料（`2026Q2`，單位 新台幣仟元，TWSE OpenAPI）不與年度值混算，列入 `excluded_fact_records`（`period_type_quarter_not_used`）。

## 5. PIT 決定

管線事實沒有可靠的公告時間，因此 Phase 1 **只支援 `CURRENT_REVIEW`**（目前已歸檔資訊，`point_in_time_supported=false`）；`STRICT_AS_OF` 回 **409**，不以擷取時間冒充公告時間。`alignment.strict_admissible` 已實作並測試（時區、exclusive cutoff、日期精度＝台北當日結束、後期版本無時間即拒絕），供 Phase 2 有公告時間後使用。

## 6. 依賴限制

- 未新增任何套件（requirements 未變）；未導入 Neo4j、向量資料庫、OCR、訓練模型。
- 法說會封存為本機開發用檔案庫（manifest `storage_contract`：非 durable）；Phase 1 以 `CONFERENCE_PDF_ARCHIVE_ROOT` 指向它。
- 無 GCS emulator；live MOPS／staging／production 未授權。
