# Integrity Workbench Phase 1.1 最終報告（待獨立 Code Review）

- **分支**：`feature/integrity-workbench-phase1-1-case-1785`，起點為已驗收的 Phase 1 `0c51a74`。只在本機，**沒有 push、merge、PR、部署或雲端寫入**。
- **Gate A（審查修正）**：**PASS**
- **Gate B（1785 案例頁）**：**PASS**
- **Gate C（完整驗證）**：**PASS**，前提是經使用者明確核准的 **Option B**（受保護資料庫以新基線 `8734fb68…` 驗收；事件見 §4）。

## 1. Commits

| Commit | 內容 |
|---|---|
| `f1c91d1` | Gate A：CR-01–04、CR-06 修正與測試 |
| `a2ec6ef` | Gate B：1785 `RETROSPECTIVE_CASE` 唯讀頁 |
| `b11fb55` | 更新路由清單測試，納入新的唯讀路由 |
| `3a06e8a` | 測試隔離、session 防護、事件紀錄 |
| `056b153` | 寫入前防護、Option B 基線、鑑識與結案報告 |
| `30fc440` | 更正事件紀錄中的過度陳述 |
| `fcbb622` | lint 修正、1785 對照表 |
| `d0ce126` | 本報告、Meeting 報告、API 契約 v2（只有文件） |
| `adfbb44` | 鑑識報告中的本機路徑改為代號（只有文件） |
| 收尾 commit | 文件一致性修正（只有文件）。最終 HEAD 記錄於審查 ZIP 的 `MANIFEST.json` 與交付索引 |

**程式碼實際驗證的 commit**：完整 28 個驗證階段在 `30fc440` 執行；`fcbb622` 改動到的階段（語法、1785 案例、後端全套、E2E、ruff、bandit、秘密掃描、受保護檔案）已在 `fcbb622` 重跑。`fcbb622` 之後的 commit 只改文件，沒有改程式碼，所以沒有重跑耗時的測試階段。

## 2. 完成內容

### Gate A：獨立審查的修正

- **CR-01 官方來源辨識**：
  - MOPS 申報連結只在以下條件全部成立時才被視為官方來源：HTTPS、白名單主機（mopsov／mops.twse.com.tw）、正確路徑與功能、參數不重複且沒有未知參數、年度／季度／報表代號合理、`co_id` 與公司代號一致。
  - 其他連結一律 `unverified_source` 並附原因；被拒的資料保留，不會取得合併口徑或申報版本。
- **CR-02 最新年度不足**：頂層結果固定描述最新會計年度。最新年度無法計算時，標為 `latest_period_not_computable`／資料不足；較早年度只放在 `last_computable` 作歷史參考，不能觸發或解除目前的查核順序；頁面以紅色提示。
- **CR-03 示範資料與重複資料**：
  - 先排除示範資料、非年度資料、不可信來源，再從剩下的官方資料中挑選。
  - 重複的官方資料依 evidence id 固定挑選，不看抓取時間。
  - 申報版本／口徑／政策不相容，或讀取可能被截斷時，直接判為不可用。
- **CR-04 主張解析**：
  - 共用解析器只做最小修正，能正確處理千分位與負號，格式錯誤的千分位不再誤讀。
  - 對既有測試中所有金額字串做新舊比較：22 筆中 14 筆被更正，沒有無法解釋的變化。
  - 4 則鎖定的簡報主張每次都從原頁重新核對：列名 → 欄位 → 印出的數字 → 表頭單位 → Decimal 換算 → 年增率欄位順序；任何歧義判 `inconclusive`，且不再呼叫查核器。
  - 已知限制（未修改）：一句話中有多個金額時，解析器仍取最後一個。
- **CR-06 研究表述**：F1 差距與 DSRI−1 數值不同（0.15 對 0.136364）；F2 同時提供 NI−CFO 與 CFO−NI 兩個方向。
- **CR-05 假設**：「`report_id=C` 代表合併報表」與「會計年度 12/31 結束」已列在回應的 `assumptions[]`。
- **版本**：contract v2，以及相關方法版本；新舊欄位對照見 `docs/data/INTEGRITY_WORKBENCH_API_CONTRACT.md`。
- **真實結果不變**：2330／2454／3711 的決策欄位與已驗收的 `0c51a74` 輸出逐欄位相同（G1：IDENTICAL）。

### Gate B：1785 案例頁

- **API**：`GET /api/v1/integrity/research-cases/1785/summary?version_policy=…`，透過 Flask 代理與頁面 `financial-integrity-case.html` 使用；從健檢頁有一個入口。
- **模式隔離**：`RETROSPECTIVE_CASE`，hindsight=true，與 CURRENT_REVIEW 完全分開；2454 回 404，1785 不能用 CURRENT_REVIEW 查詢。
- **與已驗收研究證據一致**：
  - 26 格已計算、34 格不可計算，兩個版本的 run id 相同；
  - FY2015、FY2023 的 Dechow 分數已撤回；
  - FY2012 原始申報 0.892005（依賴尚待核准的 `verified_zero` 規則）；
  - 以 2016-05-13 為截點，事前沒有任何分數。
- **對照表**：見 `docs/research/INTEGRITY_1785_CASE_FEATURE_MATRIX.md`。
- **事件時間線**：每次請求都與官方封存紀錄重新比對；5 個官方原文、3 個僅官方清單、2 個待驗證。

## 3. 測試（依序執行、真實 exit code；每個階段前後都比對 5 個核准資料庫雜湊，全程 OK）

| 階段 | commit | exit | 結果 |
|---|---|---:|---|
| Z1 事件重現 | 30fc440 | 0 | `a2ec6ef` 的測試會建立預設資料庫；HEAD 不會 |
| Z2 絕對基線阻擋 | 30fc440 | 0 | 假檔不符基線：後端與根目錄測試都以 exit 4 拒絕執行 |
| A7 寫入前防護 | 30fc440 | 0 | 10 passed |
| P0／P1 審查問題重現 | 30fc440 | 0／0 | 修正前在 0c51a74 重現；修正後安全拒絕或結果正確 |
| G1 真實結果不變 | 30fc440 | 0 | 2330／2454／3711 與 0c51a74 輸出 IDENTICAL |
| G2 解析器新舊比較 | 30fc440 | 0 | 22 筆中 14 筆被更正，0 筆無法解釋 |
| A1 語法 | fcbb622 | 0 | py_compile／node --check 通過 |
| A2 Integrity 後端 | 30fc440 | 0 | 83 passed |
| A3 主張解析與查核 | 30fc440 | 0 | 110 passed |
| A4 根目錄 Integrity 與主張代理 | 30fc440 | 0 | 14 passed |
| A5 文獻 R01／R02、F01–F04 | 30fc440 | 0 | 45 passed（含真實資料層級 0.892005） |
| A6 1785 案例 | fcbb622 | 0 | 16 passed（含真實資料層級） |
| B1 後端全套 | fcbb622 | 0 | **819 passed、5 skipped** |
| B2 根目錄全套 | 30fc440 | 0 | **159 passed** |
| B3 全新 worktree | 30fc440 | 0 | 741 passed、83 skipped，另加根目錄 11 passed |
| C1 Firestore emulator | 30fc440 | 0 | 7 passed |
| C2 8085 埠 | 30fc440 | 0 | 第一次 exit 1（emulator JVM 殘留）。確認 PID 為 `demo-fintrust` emulator 後只停止該 PID，再重跑；第一次的紀錄保留 |
| C3 瀏覽器 E2E | fcbb622 | 0 | 2454 健檢 2 個畫面＋1785 案例 2 個畫面；HTTP、一致性、模式隔離、事前截點、事件狀態全部通過。顯示工具已修正；b11fb55 的失敗紀錄保留 |
| C4 殘留埠 | fcbb622 | 0 | 無 |
| D1／D4 受保護檔案 | fcbb622 | 0／0 | 2,027 個檔案符合 Option B 基線 |
| D2 核准研究資料 | 30fc440 | 0 | IDENTICAL |
| D3 1785 文獻 | 30fc440 | 0 | 26／34，60／60 格相同 |
| E1 ruff | fcbb622 | 0 | 新的生產程式只有 B008（FastAPI 標準寫法）；測試有長行與刻意使用的假 token（S106） |
| E2 bandit | fcbb622 | 0 | 4 項既有問題＋1 項 B105 誤報 |
| E3 pip-audit | 30fc440 | 0 | 無已知漏洞 |
| E4 秘密掃描 | fcbb622 | 0 | 0 筆 |

**略過的項目**：

- B1 的 5 項：emulator 測試 3 項（已在 C1 另外執行）、live MOPS 需手動開啟、reportlab 未安裝。
- B3：全新 worktree 沒有本機資料，真實資料測試依設計略過。

**保留的失敗紀錄**：

- `b11fb55`：C3 顯示工具錯誤、D1／D4（受保護資料庫變更）。
- `a2ec6ef`：A2 路由清單測試。
- `f1c91d1`：A3 選取範圍設錯。
- 每個 commit 的 C2 第一次嘗試。

**重跑說明**：`fcbb622` 只改了 `case_study.py` 的一行換行與測試的一個未使用 import，所以只重跑受影響的階段。

## 4. 資料事件（已結案）

| 項目 | 內容 |
|---|---|
| 事件 | Gate B 測試在開發時開啟了真實的 `fintrust_backend/data/financial_pipeline.sqlite3`，建立了一張空表，雜湊從 `5526d2ad…` 變成 `8734fb68…` |
| 鑑識 | `no_exact_backup_found`（28 個檔案完整 SHA-256 比對，0 個相符）；77／148 筆 facts 與 22 張規則卡逐欄位相同；**71 筆 facts 與多張表的內容無法證明未變** |
| 決定 | 使用者明確核准 **Option B**；新基線 `8734fb68…` 記錄於 `fintrust_backend/tests/approved_data_baseline.json`（含逐列指紋）；不得描述為「未修改」 |
| 防範 | 三個資料庫元件只要指向 `fintrust_backend/data` 就在寫入前被擋下；測試期間預設路徑一律指向暫存目錄；核准資料庫與基線不符時不執行任何測試（exit 4）；每個驗證階段前後都比對雜湊 |
| 文件 | `INTEGRITY_PHASE1_1_DATA_INCIDENT.md`、`INTEGRITY_PHASE1_1_INCIDENT_FORENSIC_ASSESSMENT.md`、`INTEGRITY_PHASE1_1_INCIDENT_CLOSURE.md` |

## 5. 已知限制與尚待核准

- **方法（待雨靚核准）**：`verified_zero` 規則、COMPUSTAT→台灣科目對照（DRAFT）、存貨週轉率需要的科目對照、是否加入營業現金流科目、跨申報重疊差異說明、F1 門檻與 F2 規則。
- **事件來源**：450 公斤與發生季度、2016-05-10 交易方法變更、32.7 億元，都缺一手來源。
- **尚未完成**：真正的事前預測驗證（需要舞弊標籤、對照公司、精確公告時間），以及 B2B 交易關係模型（未嘗試）。
- **工程**：
  - 正式程式在未設定環境變數時，資料庫元件仍以 `./data/financial_pipeline.sqlite3` 為預設並寫入結構；本輪只在測試加上防護。
  - 案例 API 每次 GET 會同步計算 3 個 dry run（約 3.5–4.5 秒），回應約 0.5 MB。
  - 既有問題：`app.py` 的 `debug=True`、`verifier.py` 的 assert、`fintrust_client.py` 的 urlopen。
  - bandit B105 是誤報（`original_token` 是印出的數字表格 token，不是憑證）。
  - ruff 的 B008 是 FastAPI 標準寫法；S106 是測試中刻意使用的假 token。
