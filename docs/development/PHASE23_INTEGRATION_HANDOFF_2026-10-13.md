# Phase 2＋3 與 Phase 1.1 整合交接（2026-10-13）

狀態：GitHub 原始碼已整合，但新增程式尚待 Windows／Claude CLI 完整回歸。**不能視為 Phase 2＋3 全部完成。**

## 基準、分支與安全

- Base：Phase 1.1 最終安全推送 cb1ea1a3d80227d4733a860b6babff3b07ff63a4
- Work branch：feature/fintrust-phase23-integrate-phase11
- 完全不修改 main／v4-integration、JSD 計算演算法、正式 SQLite、雲端或部署；不建立 PR。
- 原 Phase 1.1 的 Option B 核准基線與鑑識紀錄必須保留。

## 已整合的程式

1. financial_nonfinancial_alignment.py：四筆相鄰年度證據的財務／非財務成長比對，含版本、範圍、計量政策、官方 URL 與可選 PIT 截點。
2. integrity/nfm_evidence_bridge.py：嚴格 F4 橋接；校驗 MOPS t164sb01 的 ticker、ROC year、Q4、report_id、filing_version、source SHA 及非財務文件身分。缺任何必要佐證即拒絕計算。
3. IntegrityWorkbench.readiness、assess 和 method_versions 已接入嚴格 F4，不新增對外寫入 API。
4. financial-integrity.js 可展示未來合格的 NFM 文件來源、版本、SHA、公告時間與官方網址。
5. 新增純計算和 F4 桥接測試，保留 DRAFT_PENDING_METHOD_OWNER_REVIEW。

## 目前真實資料的限制

Phase 1.1 的 pipeline facts 只有 MOPS 下載網址驗證，沒有財報原檔 source_sha256／source_document_verified，也沒有已驗證的兩年 NFM 官方資料。不得只憑 URL、自行填寫 SHA 或上傳時間即顯示「官方原檔已證實」。現有 2330、2454 F4 應仍為明確不可計算。

F4 只是 Brazel et al. 2009 啟發的描述性差距，不是該論文完整舞弊模型，也不產生台灣樣本校準的舞弊機率。兩種資料均可能由同一發行人自報，不算獨立第三方驗證。

## Claude CLI 驗證交接（不在本機 Phase 1.1 分支上直接 merge）

取得新分支後建議建立隔離 worktree。先核對 protected-stores 入口防護及 Option B 基準。於 fintrust_backend 執行：

python -m pytest -q tests/test_financial_nonfinancial_alignment.py tests/test_integrity_phase23_nfm_bridge.py

之後重跑 Phase1／1.1 Integrity、1785、API 契約、完整後端和 Flask 根目錄測試，及 2454 Workbench／1785 Chrome E2E；檢查沒有 NFM 時的 unavailable、偽造來源、衝突 filing、公司錯置和資料截止時間。

所有階段必須保留真實子程序 Exit Code。Ruff／Bandit 不得再透過 true 隱藏非零結果；已存在的警示應分類，不得寫成零警示。每個階段前後比對受保護資料的 SHA；任何異動須停止。乾淨 worktree 缺資料而 skip 不能算作真實資料通過。

## 尚未完成的 Phase 2＋3

- 官方 NFM（例如員工數／產能）文件抓取、版本封存與原檔 SHA 佐證。
- 財務原檔與目前年度 fact 的可重現來源錨點，不能改寫已核准 fact。
- Beneish、Dechow 的多公司完整模型輸入與 literature source gate。
- 2330／2454／1785 真實數據校驗、Method Owner 科目對應審核、前後端實測。
- Phase 4–6 已另外提交跨證據彙整、PIT 研究評估與獨立 B2B 頁面／API 初版；詳見 docs/development/PHASE2_TO_6_INTEGRATION_STATUS.md。這些程式尚未完成真實資料與 E2E 集中驗收。
