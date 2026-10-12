# Phase 2–6 第二輪 GitHub 開發紀錄：離線證據分段、真實來源就緒度、批次 B2B 與 PIT 閘門

**分支：** feature/fintrust-phase23-integrate-phase11

**基準：** Phase 1.1 cb1ea1a3d80227d4733a860b6babff3b07ff63a4

**交付狀態：** 程式碼已提交，尚未經完整 Windows 真實資料 / Flask / FastAPI / 瀏覽器 E2E 驗收。本輪不新增雲端寫入、部署或正式資料庫變更。

## 使用者前端要求

既有 financial-integrity.html 和 financial-integrity.js 不修改、不調整頁面配置。

新增的功能是獨立入口：
- b2b-due-diligence.html：單一企業合作方查核 + 官方來源就緒度
- b2b-watchlist.html：最多五家由使用者明確選定之企業的批次查核摘要
- 前端全部使用 textContent / DOM 節點，不將外部文字拼入 innerHTML
- 查核清單不寫入 browser storage、不持久化後端

## Phase 2–3：官方非財務資料前處理

- nfm_candidate_extraction.py：從有明確頁碼的純文字中擷取「員工人數」候選值。
- scripts/scan_nfm_archive.py：對本機封存的原始 PDF 與 pages JSON 分別驗證 SHA-256，限制相對路徑與檔案大小，再輸出候選值。
- 永遠輸出 candidate_requires_document_period_scope_review，絕不直接標記為 F4 已驗證輸入。
- 即使兩份本機檔案的雜湊一致，仍不能證明頁面文字確實從該 PDF 擷取，也不能證明文件出自公司／MOPS、報導的財政年度、合併範圍與公開時間。人工核對與獨立取得紀錄仍為必要條件。
- source_readiness.py + GET /api/v1/b2b/companies/{ticker}/source-readiness：呈現每家公司最新兩年營收原始來源 SHA、位元組核驗、公開時間及非財務資料缺漏；直接調用 F4 strict gate 防止「數量足夠但口徑錯誤」被誤標為可計算。
- 已串接到獨立 B2B 單公司頁面。

## Phase 4：來源去重

- cross_evidence.py 現在另外計算 distinct_verified_third_party_source_artifacts，依原始 SHA-256 去重。
- 有獨立來源標籤、但沒有原檔 SHA 的文件不算已驗證第三方原始文件。
- 同一文件支持兩種指標時，家族數可能是二，但實際原始文件數是一。

## Phase 5：實驗限制

- 僅用 threshold_id 字串不等於事前註冊：結果保持 threshold_pre_registered=false。
- 歷史評估狀態為 descriptive_cohort_computable_not_preregistered，絕不宣稱外部實證已通過。
- 新增 feature_sources 來源串列：每筆輸入都需原始 SHA、已核驗來源及可確認的公開時間，否則拒絕計算。
- 另外修正：無效資料不可提前佔用公司／截止時間唯一鍵而排除其後合格觀測。
- 獨立 event label 文件、負例完整追蹤、訓練／測試公司分離仍必須有真實證據；現階段只有方法與工具。

## Phase 6：自選 B2B 多家公司查核

- b2b_watchlist.py：相同 Workbench 僅做 read-only 個別評估，之後聚合五家公司以內的補件清單。
- FastAPI POST /api/v1/b2b/watchlists/preview。
- Flask POST /api/b2b/watchlists/preview。
- b2b-watchlist.html / b2b-watchlist.js 與原頁面分開。
- 使用者自行輸入的 supplier/customer/partner 只是未驗證關係，沒有供應鏈自動推論。
- 禁止重複公司、未知欄位、外部後端網址、自行指定風險標籤與 persist=true。
- 結果不持久化，不產生信用、違約、舞弊或供應中斷機率。

## 新增／修改的合成資料測試

- tests/test_integrity_phase23_nfm_candidate.py
- tests/test_integrity_phase23_source_readiness.py
- tests/test_integrity_phase6_watchlist.py
- tests/test_integrity_phase456_dossier_evaluation.py（PIT 與第三方來源額外負面測試）

本輪僅提交測試程式，**尚未執行本機完整測試**，不能稱為測試通過。原 Phase 1.1 結果仍是之前版本的驗收，不能拿它替代這個整合分支的回歸結果。

## 真實開發仍需補齊／正式前必要條件

1. 有證據的官方 PDF / iXBRL source artifact 與管線 fact 對應（不能用 URL 身分冒充原檔驗證）。
2. NFM 候選值經逐頁原始文件核對、企業／年度／計量政策審核，並配合真實公司兩年資料。
3. Beneish／Dechow 對 2330、2454 的多公司 frozen observation 與正式來源資料完整度。
4. 帶明確歷史事前時點的 outcome labels、負樣本與 timestamped 預註冊紀錄。
5. Phase 2–6 合併一次性本機完整回歸、真實資料煙霧測試、Browser E2E、所有保護資料雜湊及真實 Exit Code。

**任何 unavailable / not_computable 不是低風險；歷史 1785 事後分數不得挪用為 2330／2454 目前的風險分數。**
