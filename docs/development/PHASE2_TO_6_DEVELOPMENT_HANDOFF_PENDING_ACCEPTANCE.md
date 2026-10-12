# Phase 2–6 GitHub 開發交接：等待集中驗收（2026-10-13）

**基準：** 已審查 Phase 1.1 commit cb1ea1a3d80227d4733a860b6babff3b07ff63a4  
**開發分支：** feature/fintrust-phase23-integrate-phase11  
**狀態：** 已提交整合原始碼，尚未經 Claude CLI 真實資料與 E2E 完整驗證；不得 merge/deploy。

## 架構與既有前端隔離

原本 financial-integrity.html / financial-integrity.js 不變。新增獨立靜態頁面：

1. financial-nfm-evidence.html：獨立 F4 跨年度營收／員工數證據、來源 SHA、版本、缺失原因展示；使用現有 Flask /api/integrity/assessments/preview（僅 financial_checks）。
2. b2b-due-diligence.html：單一公司補件查核與資料就緒度。
3. b2b-watchlist.html：最多五家公司由使用者自行標示未驗證合作關係，唯讀聚合；無持久化。

新增 API 路徑：

- POST /api/v1/b2b/dossiers/preview
- GET /api/v1/b2b/companies/{ticker}/source-readiness
- POST /api/v1/b2b/watchlists/preview
- Flask proxy 前綴 /api/b2b 下對應路徑

Phase 1.1 原來所有 /api/v1/integrity 路由保持不變；獨立 B2B 預覽不會呼叫 live MOPS fetch、不寫入任何資料庫。

## 官方財務／非財務來源操作閘門

1. NFM staging：scan_nfm_archive.py 只抽取候選文字，永遠是未核准。
2. NFM reviewed release：app/services/integrity/nfm_reviewed_release.py + docs/research/PHASE23_NFM_REVIEWED_RELEASE_PROTOCOL.md；原 PDF bytes、審閱頁碼與文字，管理者釘選完整 release JSON SHA。
3. Financial original filing release：app/services/integrity/financial_source_release.py + docs/research/PHASE23_FINANCIAL_SOURCE_RELEASE_PROTOCOL.md；僅把已核准的 iXBRL/HTML 原檔 SHA 添加到 selected revenue fact 的記憶體副本，必須與公司代號、年度、MOPS 原申報版本、evidence_id、NTD 金額完全相同。
4. 兩份 release 的三項環境設定互相獨立且預設關閉。缺參數或來源不合法 → 503；清除設定並重啟即可回復原行為。沒有正式資料庫寫入。
5. F4 正式年度比對：app/services/financial_nonfinancial_alignment.py + integrity/nfm_evidence_bridge.py。缺任何已核准原始證據則 not_computable／unavailable；不產生舞弊分數。
6. 同一批多公司 NFM 資料由 Workbench 按 ticker 分流，再由 strict checker 檢查，避免其他公司資料污染此公司。

**重要限制：** Manifest SHA 只證明操作員核准的檔案未經修改；來源真實性／頁面原文與原 PDF 的連結仍依賴操作員的獨立人工查核。不得稱這是監管機構數位簽章或第三方獨立驗證。正式 2330／2454 尚沒有這兩種已核准的 release；實際 F4 必須保持不可計算。

## Phase 4–5

- cross_evidence.py 來源家族去重；第三方獨立文件另外依原檔 SHA 數量去重。
- research_evaluation.py：對每份歷史分數強制核對所有原始 feature_sources 的 SHA、來源核實與公開時點；不符合事前截止時間就排除。
- threshold ID 不代表真正經時間戳記證實的事前註冊。描述性矩陣不宣稱已證實預測力、舞弊機率、因果效果。
- scripts/evaluate_pit_holdout.py 僅本機讀入 JSON，結果輸出 stdout。

## Phase 6

- b2b_dossier.py + b2b_watchlist.py 只列交易對手補件與資料缺口。
- 使用者提供「supplier/customer/partner」是未驗證關係，不是系統發現的交易網絡。沒有持久化的 Watchlist、供應鏈連結推估、倒閉、違約、舞弊或停供機率。

## 必做測試（最後由 Claude CLI 集中執行）

1. 新增測試：test_financial_nonfinancial_alignment.py、test_integrity_phase23_*.py、test_integrity_phase456_dossier_evaluation.py、test_integrity_phase6_*.py。
2. Phase 1／1.1 原有 Integrity 測試、1785 歷史案例基準、Beneish／Dechow 研究模型不變性。
3. FastAPI → Flask proxy → Browser E2E；單公司 F4、B2B 查核及五家公司 Watchlist。
4. NFM 與財報核准發布檔的正反例，包括無設定、部分設定、錯誤 SHA、偽造官方主機、年份／數值錯置、頁碼／原文未審核、Symlink 與路徑跳脫。
5. 納入真實年度財務原檔與真實 NFM 文件後，驗證 F4 的正確計算／不可計算分支；不得為滿足 demo 填假資料。
6. Option B 受保護 SQLite 及其他已核准研究資料前後 SHA-256 完全一致。
7. Ruff、Bandit 與 full pytest 真實 exit code，不使用 ; true 掩蓋靜態警示。
8. 檢查 GitHub branch 差異，確認原始 Workbench HTML/JS 沒改變、不含任何 Secret、私人原檔、正式資料庫與本機使用者路徑。

**截止目前僅已提交程式碼及其測試原始碼，未執行本輪完整測試，亦尚未取得前述官方核准資料。切勿把本文件寫成 Phase 2–6 PASS。**
