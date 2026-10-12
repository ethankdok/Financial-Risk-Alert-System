# Financial Integrity Workbench Phase 1 — 最終報告（待獨立 Code Review）

## 1. Git

- **分支**：`feature/integrity-evidence-workbench-phase1`，由 `872c85675424a41b45860b9f21381f08185350dd` 建立。只在本機，**沒有 push、merge、PR 或部署**。
- **Commits**：
  1. `d8be01f`：Phase 1 實作（程式、測試、Gate 0 文件、API 契約、文獻對照表）。
  2. `1b94103`：修正「無年度資料時出現 FY0」。所有驗證階段都在這個 commit 執行。
  3. 第三個 commit 只新增本報告與 Meeting 報告。
- **使用者未追蹤檔**：全部保留，未納入任何 commit。

## 2. 改動檔案（`872c856..1b94103`）

**新增：後端**
- `fintrust_backend/app/services/integrity/`：
  - `contracts.py`：Pydantic 型別、封閉 enum、Decimal 字串。
  - `alignment.py`：單位、期間、口徑、申報版本對齊，以及 PIT 判斷。
  - `financial_checks.py`：F1、F2、F4。
  - `adapters.py`：Facts、Literature、JSD、Claims、OfficialSources 五個 adapter。
  - `composer.py`
  - `service.py`
  - `issuer_statements.json`
- `fintrust_backend/app/routers/integrity.py`

**新增：前端與 Flask**
- `integrity_routes.py`
- `financial-integrity.html`、`financial-integrity.js`

**新增：腳本與測試**
- `fintrust_backend/scripts/integrity_phase1_smoke.py`
- 後端測試：`integrity_fixtures.py`、`test_integrity_phase1_{checks,composer,api,real}.py`
- 根目錄測試：`tests/test_integrity_phase1_proxy.py`、`tests/integrity_page_harness.js`

**新增：文件**
- `docs/development/INTEGRITY_PHASE1_BASELINE_AND_FEASIBILITY.md`
- `docs/data/INTEGRITY_WORKBENCH_API_CONTRACT.md`
- `docs/research/INTEGRITY_PHASE1_LITERATURE_TO_FEATURE_MATRIX.md`
- `docs/development/PHASE1_MEETING_REPORT.md`、本報告

**修改（最小幅度）**

| 檔案 | 改動 |
|---|---|
| `fintrust_backend/app/main.py` | 註冊 router（+2 行） |
| `app.py` | 註冊 Blueprint（+2 行） |
| `fintrust_client.py` | 3 個唯讀方法；`integrity_preview` 一律送出 `persist: false` |
| `index.html` | 導覽列新增**一個**入口 |
| `Dockerfile.flask` | 加入 `integrity_routes.py`，否則映像中的 `app.py` 啟動時會 import 失敗 |
| `fintrust_backend/app/services/verifier.py` | `MONEY_SCALES` 新增 `"新台幣元": 1.0`（理由見 §6） |

**未修改**
- Beneish／Dechow 引擎、係數、`literature_inputs.py`、方法對照。
- Ethan 的 `data_shift.py`、JSD 校準。
- 既有規則、Dashboard 版面與 CSS。
- 資料庫結構與雲端設定。

## 3. 完成與未完成

| 項目 | 狀態 | 佐證 |
|---|---|---|
| 證據整合服務、EvidenceRecord 全部欄位（缺值以型別標註） | ✅ | `contracts.py`；`test_integrity_phase1_api.py::ContractTests` |
| F1 營收 vs 應收、F2 淨利 vs 營業現金流（Decimal） | ✅ | `test_integrity_phase1_checks.py`（26 項）；REAL tier |
| F3 發行人主張：重用既有 ClaimVerificationService | ✅ | `ClaimsTests`、`RealVerifierClaimTests`；REAL tier 4 筆 `supported` |
| F4 Brazel NFM | ⚠️ readiness only | 沒有經驗證的 NFM 資料；計算路徑只用合成資料測試 |
| 文獻模型 adapter（引擎未修改） | ✅；正式公司 `not_computable` | `LiteratureTests` |
| JSD adapter（重新驗證可比性；未校準時不給等級） | ✅ | `JsdTests` |
| 官方證據（OfficialEvidenceService，live 強制關閉） | ✅ | 概況頁的規則訊號與重大訊息 |
| Composer：五家族、證據家族去重、佇列規則、B2B 清單 | ✅ | `ComposerTests` |
| FastAPI 端點 3 個；Flask 代理 3 個；新頁面（四區＋方法抽屜） | ✅ | API 與 chain 測試、根目錄測試、E2E |
| 真實瀏覽器 E2E 與截圖 | ✅ | C3（4 張 PNG） |
| STRICT_AS_OF | ❌ 刻意不支援（回 409） | 沒有公告時間；`strict_admissible` 已實作並測試，留給 Phase 2 |
| 完整 OfficialEvidenceCardBuilder 同步呼叫 | ❌ 刻意不呼叫 | 設定環境變數時可能呼叫 Gemini |
| GCS emulator、live MOPS、staging／production | 未執行 | 不可用或未授權 |

## 4. 真實資料示例

- **資料**：MOPS Inline XBRL 年度財報（合併）。
- **2454 FY2025 對 FY2024**：

  | 項目 | FY2024 | FY2025 | 成長 |
  |---|---:|---:|---:|
  | 營收 | 530,585,886,000 | 595,965,682,000 | +12.3222% |
  | 應收帳款 | 43,944,786,000 | 62,056,117,000 | +41.2138% |

  - 差距 **28.89 個百分點**，狀態 `descriptive_divergence`，查核佇列為「需要補件確認」。
  - 門檻 0.20 未經校準。敏感度：0.10 與 0.20 為「是」，0.30 為「否」。
- **F2**：2454 FY2025 的營業現金流比淨利多 56,675,297,000；2330 FY2024 多 653,745,309,000。兩者都未觸發。
- **F3（4 筆，皆在列印精度內）**：

  | 主張 | 來源 | 差額 | 容許 |
  |---|---|---:|---:|
  | 2454 Net Sales 530,586（NT$ millions） | `245420250207E001.pdf` 第 15 頁，SHA `c500c62f…` | 114,000 元 | ±500,000 元 |
  | 2454 Net income 107,141 | 同上 | 377,000 元 | ±500,000 元 |
  | 2330 Net Revenue 2,894.31（NT$ billions） | `233020250116E001.pdf` 第 11 頁，SHA `24240a79…` | 2,301,000 元 | ±5,000,000 元 |
  | 2330 Operating Cash Flow 1,826.18 | 同上 | 2,932,000 元 | ±5,000,000 元 |

  以上都是同一發行人自報，獨立佐證 0 件。
- **JSD**（2025Q2 → 2025Q3，英文簡報）：2454 為 0.078121／0.944793；2330 為 0.232142／0.676225。兩者都未校準，等級為 null。
- **文獻模型**：Beneish 與 Dechow 對 2330、2454 都是 null，缺漏分別為 47 項與 45 項。
- **3711（無快照）**：全部 fail closed，佇列為「資料不足」。

## 5. 測試證據

20 個階段依序執行、一次一個程序，exit code 為真實值，全部是 0。完整紀錄見 `INTEGRITY_PHASE1_TEST_RESULTS.txt`。

| 階段 | 結果 |
|---|---|
| A1 語法 | 20 個 .py 通過 py_compile；2 個 JS 通過 `node --check` |
| A2 新後端測試 | 59 passed |
| A3 新根目錄測試 | 8 passed |
| A4 R01／R02 + F01–F04 | 45 passed |
| A5 既有 claim／JSD／evidence | 149 passed |
| B1 後端全套 | **769 passed、5 skipped** |
| B2 根目錄全套 | **156 passed** |
| B3 全新 worktree | 697 passed、77 skipped，另加根目錄 8 passed |
| C1 Firestore emulator | 7 passed |
| C2 8085 埠 | 第一次失敗（emulator JVM 殘留），處理後重跑通過 |
| C3 E2E（真實資料，headless Chrome） | 4 個分區、17 項 HTTP 檢查、FastAPI↔Flask 一致 |
| C4 殘留埠 | 無 |
| D1／D4 受保護檔案 | 1,942 個逐位相同（前、後各驗一次） |
| D2 核准研究資料 | IDENTICAL |
| D3 1785 文獻 | 26／34，60／60 格相同 |
| E1 ruff | 見下 |
| E2 bandit | 見下 |
| E3 pip-audit | 0 個漏洞；requirements 未變 |
| E4 秘密掃描 | 0 筆 |

**略過與原因**
- B1 的 5 項：emulator 測試 3 項（在 C1 另外執行）、live MOPS 需手動開啟、reportlab 未安裝。
- B3 的 77 項：全新 worktree 沒有本機資料，REAL tier 依設計略過。

**C2 處理經過**：emulator 結束後，JVM 仍佔用 8085。確認是 `cloud-firestore-emulator … --project_id demo-fintrust`，且在 C1 期間建立，才只停止該 PID。兩次的初次紀錄都保留在測試紀錄中。

**以前一個 commit 跑過的紀錄**：在 `d8be01f` 跑過的各階段紀錄（全部 exit 0）也保留，檔名後綴 `_at_d8be01f`。

**ruff（41 筆）**
- 新增、生產程式：5 筆 B008，都是 FastAPI `Depends()` 標準寫法，既有 router 相同。
- 新增、測試程式：2 筆 S106，是刻意傳入的假 token，用來證明 token 不會被轉送；其餘為測試的長行（E501）。
- 既有：`fintrust_client.py` 3 筆 E501。

**bandit（4 筆）**：全部是既有問題，本輪沒有新增。
- `app.py` 的 `debug=True`（High）：行號因新增 import 由 1337 移到 1339。
- `verifier.py` 的 2 個 assert。
- `fintrust_client.py` 的 `urlopen`。

## 6. 唯讀與舊資料保存

- **沒有任何寫入**：沒有雲端寫入、Firestore／GCS 正式環境變更、MOPS 下載、LLM 呼叫，也沒有 persist。
- **既有缺陷（未修改）**：`SqliteAnalysisRepository` 開檔時會 commit schema script，即使只讀也會改寫 SQLite 檔頭。因此 E2E、REAL 測試與 smoke 都使用「SHA 驗證完全相同的副本」。
  - 正式 DB SHA 前後皆為 `5526d2ad…`。
  - Gate 0 期間的試跑也只動到副本，原檔雜湊未變。
- **`verifier.py` 為何要改**：MOPS XBRL 事實的單位是「新台幣元」，但它不在 `MONEY_SCALES` 中，所以任何金額主張與 XBRL 事實比對時一律回 `insufficient_evidence`。
  - 新增這一行後，既有 claim 測試 149 項仍全部通過。
  - 這會改變既有 `/claims/verify` 的行為：原本「證據不足」的金額主張，現在可得到 supported 或 conflicting。**請審查確認。**
- **既有缺陷（未修改，以防護處理）**：`claim_parser` 會把「新台幣5,305.86億元」解析成 305.86，可能誤判為 conflicting。
  - Workbench 的主張登錄檔去除千分位逗號。
  - 解析結果與預期值不符時改判 `inconclusive`，有測試。
  - 修正 parser 本身建議另開一輪處理。
- **既有 verifier 容許度偏寬**：金額主張容許約 2% 相對誤差。Workbench 另外要求官方值必須落在主張「列印精度」的半單位內，否則改判 `inconclusive`。

## 7. 文獻方法分層

| 文獻 | 分層 |
|---|---|
| Beneish、Dechow | 引擎已實作；正式公司 readiness only |
| Brazel | readiness only |
| Larcker、Bao | future |
| Loughran、Barrot | design inspiration |

除 Beneish 與 Dechow 外，其餘五篇本專案沒有依原文核對。

## 8. Demo 啟動步驟（本機）

1. 先複製資料庫，因為開檔會改寫檔頭：
   ```
   cd fintrust_backend
   copy data\financial_pipeline.sqlite3 %TEMP%\fi_demo.sqlite3
   ```
2. 啟動 FastAPI：
   ```
   set FINANCIAL_DATABASE_PATH=%TEMP%\fi_demo.sqlite3
   set CONFERENCE_PDF_ARCHIVE_ROOT=data\official-ir-pdfs-live-test
   set JSD_CALIBRATION_BACKEND=json
   ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
3. 在 repo 根目錄另開視窗，啟動 Flask：
   ```
   set FINTRUST_API_BASE_URL=http://127.0.0.1:8000
   .venv\Scripts\python.exe -c "import app; app.app.run(host='127.0.0.1', port=5001, debug=False)"
   ```
4. 開啟 `http://127.0.0.1:5001/financial-integrity.html?ticker=2454`，或從首頁導覽列進入「財務可信度健檢」。
5. 一鍵自動驗證：在 `fintrust_backend` 執行 `python -m scripts.integrity_phase1_smoke --out <dir>`。

## 9. 待方法負責人（雨靚）決定

1. F1 的未校準門檻 0.20 與 F2 的佇列規則是否可用？是否改為產業別或排名方式？
2. 以 MOPS report_id=C 推定合併口徑，以及「申報當年 Q4／年報」申報政策，是否可接受？
3. 發行人主張登錄檔的正規化方式（去除千分位；NT$ billions × 10 = 億）。
4. 正式公司文獻模型凍結輸入的建立方式（套用與 1785 相同的來源閘門）。
5. NFM 資料來源（年報員工數或產能揭露）與 Brazel 指標的選擇。
6. JSD 是否為 MOPS 英文簡報建立校準檔（目前 2330 校準檔適用於不同文件類型）。
7. 既有事項：Beneish 只以作者手稿驗證；COMPUSTAT→台灣科目對照為 DRAFT。

本報告不代表已通過驗收。等待獨立 Code Review。
