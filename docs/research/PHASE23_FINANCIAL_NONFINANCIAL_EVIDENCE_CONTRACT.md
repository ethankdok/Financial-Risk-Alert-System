# Phase 2＋3｜財務與非財務資訊一致性分析：方法與資料契約

研究方法：Brazel, Jones, & Zimbelman (2009) 的財務與非財務成長比較思路。
實作：fintrust_backend/app/services/financial_nonfinancial_alignment.py
方法核准：DRAFT_PENDING_METHOD_OWNER_REVIEW。

## 功能範圍
比較全年營收與員工人數、產能等相關非財務活動指標的相鄰年度成長率。
本模組只有純計算與合格證據條件，不進行檔案、資料庫、網路或雲端寫入。
尚未連接本機 Phase 1.1 Workbench、正式非財務數據來源或前端。
它沒有實作論文中的舞弊分類模型，沒有校準門檻，不回傳舞弊機率或供應鏈中斷機率。

## 必要四筆證據
每家公司需要兩個相鄰年度、每年財務與非財務各一筆。
GrowthEvidence 欄位：
- ticker、fiscal_year、metric、value、unit
- statement_scope：合併／個體公司範圍，四筆須相同。
- measurement_policy：計量政策，同一指標兩年度須相同。
- period_basis：營收 annual_flow；非財務可為 year_end_stock 或 annual_average，但同一指標不能跨年混用。
- source_url、source_sha256、filing_version_id、published_at。
- source_trust：需由上游官方附件身分驗證器核准為 verified_official_document。

官方網域本身不足以證明文件身分。上游必須先核對附件、公司代號及原檔。
Demo、缺失來源、不同申報版本、期間／單位／範圍衝突、零或負分母等皆回傳 not_computable 與具體原因。
發行人官方揭露的財務及非財務數字都屬發行人自報，不是獨立第三方交叉驗證。

## 計算
financial_growth = financial_t / financial_(t-1) - 1
nonfinancial_growth = nfm_t / nfm_(t-1) - 1
growth_gap_percentage_points = (financial_growth - nonfinancial_growth) * 100

輸出 Decimal 字串、期間、來源、證據限制；不回傳風險等級。

## 嚴格時點
當傳入 cutoff_at，每筆 published_at 必須有時區且可證明早於 cutoff_at。
擷取或入庫時間不能替代原始公告時間；不明時點直接不可計算。

## 測試證據
19 項 synthetic unittest 已在隔離 Python 環境通過，包含計算、版本衝突、缺年度、官方網域、安全性及 PIT。
測試通過只代表純計算核心；不代表已取得正式員工／產能資料，也不等於真實資料 E2E 通過。

## 與 Phase 1.1 同步
本 GitHub 分支基於遠端 v4-integration，因為本機 Phase 1.1 尚未推送。
請先完成 Phase 1.1 獨立驗收與安全推送，再從該 Commit 建立整合分支，以 cherry-pick 或選擇性移植納入本模組。
後續仍須完成官方非財務資料擷取及版本封存、文獻模型多公司輸入適配、Workbench F4／前端串接、真實資料測試及研究方法審核。

## 參考文獻（APA 7）
Brazel, J. F., Jones, K. L., & Zimbelman, M. F. (2009). Using nonfinancial measures to assess fraud risk. Journal of Accounting Research, 47(5), 1135–1166. https://doi.org/10.1111/j.1475-679X.2009.00349.x
