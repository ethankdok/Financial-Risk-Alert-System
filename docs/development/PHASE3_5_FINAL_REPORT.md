# FinTrust Phase 3–5 整合開發最終報告（供獨立審查）

**基準 commit**：`506b64cb62f9a31353d87444f0080fa6540cf759`（Phase 2C，已確認為祖先）
**整合分支**：`feature/phase3-5-research-integration`（本機；未 push、未 merge、未建立 PR）
**最終 HEAD、交付檔路徑、大小與 SHA-256**：見交付目錄的 `HANDOFF_INDEX.json`，以及 review ZIP 內的 `PROVENANCE.json`／`MANIFEST.json`
**結論**：`INTEGRATION_READY_FOR_INDEPENDENT_REVIEW`。本機部署就緒不等於已上線：沒有部署，也沒有任何雲端寫入。

## 1. 摘要

- **Phase 3**：在既有 `ResearchBackend` 之上完成純 Decimal 的研究層 `app/services/financial_research/`，強制三種分析模式（沒有預設值，也不會隱性回退）。
  - **重編橋接（主實驗）**：158 列逐列重現，資料一致性 READY。
  - **嚴格截點**：2016-05-13 之前回報 `insufficient_point_in_time_evidence`；2016-11-13 21:26:22 為逐秒邊界。
  - **財務特徵**：12 個特徵已登錄，附可解釋性與缺值原因。
  - **文獻模型**：Beneish／Dechow 僅有就緒檢查，結果為不可計算。
  - **來源比對**：FY2025 有 2 項各 1,721 千元的差異未解，已對到 PDF 第 8 頁。
  - **JSD**：0 筆可用，顯示 NOT_APPLICABLE，不輸出數值。
  - 衍生結果寫入另一個只能附加的資料庫，並可重算驗證。
- **Phase 4**：FastAPI 新增 11 個研究端點；Flask 只做代理；新增六個視圖的研究頁面。repo 實際是原生 HTML/JS，沒有 React、Vite 或 Tailwind。已用真實本機程序和 headless Chrome 截圖驗證。
- **Phase 5**：
  - 研究結果匯出：有界、有日誌、有鎖、冪等；
  - Firestore emulator 實跑 3 項通過；
  - 唯讀 preflight 10 項通過；
  - 完成資料責任歸屬，以及 staging、部署、回滾 runbook。
- **未完成或不適用**：
  - Beneish／Dechow 完整分數，以及 Jones 類 panel 模型（缺可信輸入）；
  - 1785 的 JSD 數值；
  - 事前預測指標；
  - GCS emulator；
  - staging 或正式部署（需另行核准）。

## 2. Git 狀態與變更範圍

**提交**（皆在本機）：

| Commit | 內容 |
|---|---|
| `aa9004c` | 研究層與 API |
| `3398361` | 三層測試 |
| `68db626` | Flask 代理、UI、E2E |
| `0427418` | Flask 靜態路由修正，另含研究 blueprint 註冊兩行 |
| `5e27573` | 雲端匯出與 preflight |
| `821bb6a` | 文件 |
| `e36b698` | lint 修正與打包工具 |
| 最終 commit | 報告、驗收矩陣、交接文件 |

**重用 vs 新增**：

- **重用（不修改演算法）**：
  - `ResearchBackend`、reader 的 PIT 規則、`evidence_export`；
  - `conference_jsd_corpus_adapter`（Ethan 的契約）；
  - `cloud_config`、`cloud_sync`、`FirestoreHistoricalResearchRepository`；
  - `require_ingestion_token`；
  - 既有 Flask `FinTrustClient` 樣式。
- **加法式修改**：
  - `research_access.py`：新增兩個 backend 方法，有對等性測試；
  - `models.py` 與 `cases/1785.json`：新增研究涵蓋年度 `coverage_*_year`；
  - `main.py`：掛載 router；
  - `app.py`：註冊 blueprint 並修正靜態路由；
  - `fintrust_client.py`；
  - `Dockerfile.flask`：COPY 加入 `research_routes.py`。
- **新增**：`financial_research/` 共 15 個模組、研究 router、Flask 代理、研究頁面、6 個測試檔與 1 個 Node harness、5 個腳本、文件。

**完全未觸及**：

- 2330／2454 管線、規則門檻、可信度與風險分數、Gemini 敘事；
- Ethan 的 `data_shift.py`／`jsd_method.py`；
- 正式公司清單與 refresh 流程。

**1785 案例資料**：保留 2011–2016 事件期間（CLI 預設），另行標記研究涵蓋 2011–2025，並更正過時的「2017–2025 為未來工作」註記。

## 3. Phase 3 研究能力矩陣

| 模組 | 狀態 | 實際結果 |
|---|---|---|
| M1 重編橋接（RETROSPECTIVE） | READY（方法為 DRAFT） | 見下方說明 |
| M2 財務特徵 | PARTIAL（DRAFT） | 12 個特徵；回溯模式 FY2011–2025 共 139 格已計算、26 格不可計算；嚴格截點 2026-10-11 共 35 格已計算 |
| 嚴格 PIT | READY | 見下方說明 |
| M3 來源比對 | READY，一致性 INCONSISTENT | 見下方說明 |
| 文獻模型 | NOT_COMPUTABLE | 見下方說明 |
| JSD／文字 | NOT_READY，JSD NOT_APPLICABLE | 44 筆檔名紀錄、38 份不同 SHA、1,190 頁（1,139 頁有文字）、26 列清單、0 筆 JSD-ready |

**M1 重編橋接**：

- 158 列：合併 79、個體 79；
- 數值一致性檢查：差額欄、會計準則、毛利恆等式都是 0 個錯誤；
- 例：FY2013 合併營業成本 32,256,578 → 33,223,945 千元（Δ +967,367 千元），毛利率 5.7970% → 2.9718%；
- 存貨不在公告中，標示為不可計算。

**嚴格 PIT**：

- 截點 2016-05-13 之前：0 筆財務事實，顯示 `insufficient_point_in_time_evidence`，不是「風險低」；
- 2016-11-13 21:26:22 為 0 筆，21:26:23 為 27 筆（FY2013–2015 各 9 筆）；
- 截點 2026-10-11 00:00：67 筆，其中 FY2025 只有 5 筆。

**M3 來源比對**：

- 董事會公告 vs XBRL：40 項一致、2 項差異待查證、18 項不可比較；
- 重編公告（重編後）vs 重編 XBRL：27 項一致；
- TPEx 摘要 45 項不可比較（範圍是比對營收推定的，比較會循環）；
- FY2025 總資產 34,436,171 vs 34,434,450 千元、總負債 19,423,635 vs 19,421,914 千元，各差 1,721 千元；
- PDF（SHA `fc715140…`）第 8 頁與 XBRL 相同；原因未證實，不轉入風險分數。

**文獻模型**：Beneish 缺 PPE、折舊、SG&A、長期負債等；Dechow 缺 RSST 等；Jones 類缺多公司 panel。不提供係數；DSRI、GMI、SGI 只作描述性指數。

方法規格見 `docs/research/07_PHASE3_METHOD_SPECIFICATION_DRAFT.md`（待雨靚核准）。

## 4. Phase 4 能力矩陣

**FastAPI**（`/api/v1/research`，OpenAPI：`docs/data/openapi_research_v1.json`）：

- `GET /health`
- `GET /cases`
- `GET /cases/{ticker}`
- `GET /cases/{ticker}/timeline`
- `GET /cases/{ticker}/restatement-bridge`
- `GET /cases/{ticker}/feature-registry`
- `GET /cases/{ticker}/source-discrepancies`
- `GET /cases/{ticker}/text-readiness`
- `POST /financial-signals/compute`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/verify`

錯誤碼：缺模式、缺截點或格式錯回 422；生產環境的 ticker（2330）回 404；端點不支援的模式回 409；資料未佈署回 503；持久化需要 `X-Ingestion-Token`。

**Flask**（`/api/research/...`）：

- 只代理，不做計算；查詢參數採白名單；
- 瀏覽器端強制 `persist=false`；
- 422／404／409 原樣回傳。

**UI**：`historical-research.html` 有六個視圖：

1. 案例總覽
2. 重編熱圖與橋接（含「依 2016 年 11 月公告回溯重述」警示與範圍選擇）
3. 時間線（E1 清單 vs E2 原文、精度、截點）
4. 訊號探索（算式、分子分母、輸入來源、缺值原因、文獻就緒度）
5. FY2025 差異（雙來源與 PDF 第 8 頁）
6. 法說會／JSD 品質

另有：鍵盤操作分頁、`aria-live` 狀態、可分享的 URL hash、只顯示官方網域連結、所有文字經過跳脫。

**驗證**：

- in-process 鏈結測試 FastAPI → Flask → Node 渲染：FastAPI 與 Flask 回應一致，惡意文字（XSS）測試通過；
- 真實程序 smoke：uvicorn 與 Flask 各自獨立程序、本機 HTTP、headless Chrome，6 張截圖加 DOM 字串檢查全部通過；
- 前端沒有 npm build、lint、typecheck 工具鏈（repo 本身沒有），只跑 `node --check`。

## 5. Phase 5 矩陣

| 層級 | 結果 |
|---|---|
| Mock（記憶體 Firestore／GCS） | 鏡像對等、結果庫對等、匯出（試跑、批次、碰撞、故障注入、鎖）通過 |
| Firestore emulator（firebase-tools 13.35.1，emulator v1.19.8，`demo-fintrust`） | 3 項通過：既有歷史 emulator 測試，以及新的結果庫和研究輸出對等測試 |
| GCS emulator | 本機無可用工具，只做 mock 層級 |
| Live／staging | 未執行、未授權 |

- **資料責任歸屬**：原始 bytes → 本機 archive；中繼資料與事實 → 唯讀 SQLite（Firestore 為只建立不覆寫的鏡像）；衍生結果 → `research_results.sqlite3`（Firestore 鏡像經 `result_sync` 寫入）。
- **研究資料不包進 image**：雲端預設回 503，正式端點不受影響。
- **Preflight**：`research_cloud_preflight` 10 項通過，沒有任何寫入。
- **Runbook**：`docs/cloud/PHASE5_HISTORICAL_RESEARCH_CLOUD_READINESS.md`。
- **需另行核准**：
  - 讀取正式環境 IAM、Secret、預算；
  - 建立 staging 專案或 bucket；
  - 選定 staging 的研究資料來源；
  - 任何正式環境推送。

## 6. 資料完整性（前後比對）

`scripts/research_baseline.py --compare`：**IDENTICAL**。

- 16 張表的逐表 digest 都不變：facts 234、versions 44、comparisons 158、events 919、disclosed 60、availability 79、summaries 210、sources 102 等；
- raw archive 274 檔、conference archive 4,735 檔都不變；
- 研究層以 `mode=ro` 開啟資料庫，測試也驗證無法寫入。

**12 個既有 ZIP 與 sidecar SHA-256 全部不變**：

| 檔案 | SHA-256 |
|---|---|
| `fintrust_1785_2011_2016_full.zip` | `693e8671…` |
| `fintrust_1785_asof_2016-11-14.zip` | `304934a4…` |
| 對應 `.audit.json` | `c3ce8507…` |
| `fintrust_1785_2011_2019_full.zip` | `9cbbd789…` |
| `fintrust_1785_2011_2019_asof_2020-12-31.zip` | `7268951f…` |
| 對應 `.audit.json` | `75751ee0…` |
| `fintrust_1785_2011_2022_full.zip` | `3d4cba56…` |
| `fintrust_1785_2011_2022_asof_2023-12-31.zip` | `61042b7f…` |
| 對應 `.audit.json` | `1cdd0d5b…` |
| `fintrust_1785_2011_2025_full.zip` | `171e3da1…` |
| `fintrust_1785_2011_2025_asof_2026-10-10.zip` | `9f281d50…` |
| 對應 `.audit.json` | `bf6ba1de…` |

完整值見測試 TXT。

## 7. 回歸、故障注入與略過

| 測試 | 結果 |
|---|---|
| 後端全套 | 617 通過、5 略過（基準 564／3，新增 53） |
| 根目錄（Flask／前端） | 146 通過（基準 142） |
| Firestore emulator 層 | 3 通過 |

各子集計數見測試 TXT。

**略過原因**：

- 3 項 emulator 測試在一般執行中略過，已另以 emulator 實跑通過；
- live MOPS 需手動開啟；
- reportlab PDF fixture 需要額外套件。

**故障注入**：

- 截點後的資料洩漏 → fail closed；
- 竄改數值、證據 hash、版本、範圍、單位、時間 → digest 改變或不可計算；
- 竄改正負號 → INCONSISTENT；
- Firestore 寫入失敗 → 不留下半個 run，重試冪等；
- 匯出碰撞 → 不覆寫；
- 鎖 → 互斥。

**安全掃描**：

- ruff（新程式碼）：只剩行長、FastAPI `Depends` 慣用法、固定表名 SQL 格式，都經審查為可接受；
- bandit：`app.py` 既有的 `debug=True`（只在本機 `__main__` 啟動時生效）、一項常數表名誤報；
- pip-audit：後端無漏洞；根目錄 `pyarrow 22.0.0` 有 PYSEC-2026-113（既有相依套件，建議升到 23.0.1，本次未更動）；
- diff 秘密掃描：0 項。

## 8. 警告與未解問題

1. 發現既有安全缺陷：Flask 萬用路由會直接提供 `/financial_risk.db`、`/app.py`、本機 SQLite 等檔案。已用獨立 commit 改為只提供網頁資源，請審查。
2. 所有研究方法（近零門檻 1%、比率組、t−1 政策）都是 DRAFT，待雨靚核准；H1–H4 的法律分類（判決認定、訴訟主張或公司揭露）尚未逐段驗證，判決也未封存。
3. 研究資料不在 Cloud Run image 內；staging 採唯讀 volume 還是 Firestore 鏡像，需要負責人決定。
4. 既有問題延續：所有 XBRL 的公開時間仍未驗證；FY2025 差異原因未明；FY2016 EPS 比較數差異；FY2017–2019 沒有 PIT 事實。
5. 2016-11-13 21:25:31 的個體公告只為摘要觀測定時，沒有為合併事實定時，已在邊界測試中呈現。

## 9. 交付檔

完整絕對路徑、大小與 SHA-256 見 `HANDOFF_INDEX.json`，最終回覆也會一併列出：

- review ZIP
- 測試結果 TXT
- 本報告
- 研究 fixture
- OpenAPI 快照
- UI 截圖與 DOM
- 雲端證據
- 驗收矩陣
