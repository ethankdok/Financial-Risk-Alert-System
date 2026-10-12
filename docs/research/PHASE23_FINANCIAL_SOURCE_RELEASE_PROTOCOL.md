# Phase 2–3：原始申報檔與既有財務事實的唯讀來源錨定

**功能：** 讓管理者已覆核且 SHA-256 核准的官方申報原檔，對應到 Finance Pipeline 已持久化的年度營收事實。只能附加來源證據到當次查詢的副本，**不得重寫原 SQLite／Firestore 財務數字**。

## 實作

- app/services/integrity/filing_artifact_checks.py：校驗本機封存 HTML、XHTML、XML、XBRL、PDF、ZIP 的檔頭、位元組 SHA-256、相對路徑與 Symlink。
- app/services/integrity/financial_source_release.py：對管理者批准的來源發布檔整體校驗，並對 selected revenue fact 做嚴格證據身分與數值比對。
- app/services/integrity/service.py：只對 Workbench 當次資料副本加上 approved source SHA、文檔 bytes marker 和可核驗公告時點。
- 原始證據紀錄 API 不暴露 internal source_document_verified 標記，但能顯示核准原始來源 SHA。沒有核准檔時原有行為維持不變。

## 核准財報來源文件規格

發布檔最外層 release_version = fintrust_financial_source_release_v1；records 1–100 筆。每筆包含：

- ticker、fiscal_year、evidence_id（必須與既有 selected fact 一致）。
- filing_version（必須和實際 validated MOPS t164sb01 URL 對應）、source_url、source_sha256。
- archive_relative_path、value_twd（原始資料庫的 NT$1 標準 Decimal 字串，不可重估或改值）、published_at（可 null，但絕不猜測公告即時時間）。
- review: status=approved、review_id、reviewed_at、ticker、fiscal_year、evidence_id、source_sha256、verbatim_line（核對的原文行）、reviewed_value_twd。
- review 以下項目均須管理者明確核對為 true：official_download_confirmed、company_identity_confirmed、filing_year_confirmed、revenue_statement_line_confirmed、consolidated_scope_confirmed、amount_and_unit_confirmed。

系統自動檢查 URL 公司代號、民國年度、第四季、report_id=C、filing_version、原檔 bytes SHA 與入庫財務事實一致性；只有來源人工審查成功時才承認該資料對應關係。這項人工核准不等於監管機構的數位簽章，使用者仍須對原始 MOPS 資料真實性負責。

## 伺服器選用設定

三個設定都不存在時完全不啟用。有任一設定卻不齊全，或核准發布檔／原始 bytes 不合格，會回應 503。不可從瀏覽器指定設定值。

    FINTRUST_FINANCIAL_REVIEW_MANIFEST=<核准發布檔完整路徑>
    FINTRUST_FINANCIAL_APPROVED_RELEASE_SHA256=<該發布檔完整原始 bytes SHA256>
    FINTRUST_FINANCIAL_ARCHIVE_ROOT=<原始申報檔封存根目錄>

NFM 對應的獨立設定見 PHASE23_NFM_REVIEWED_RELEASE_PROTOCOL.md。兩者分開管理，各自可獨立關閉與撤銷，不影響正式資料庫原始內容。

## 模型計算條件與回滾

- F4 僅在相鄰兩年的合併財務營收（原檔核准）與同一公司兩年的非財務指標（人工核准）同時具備，且範圍、政策、單位、版本無衝突時提供描述性成長差距。
- 若任何來源、公告時間、原文與資料庫事實不一致，拒絕讀取該核准發布檔；不採用部分有問題的版本。
- 不產生舞弊機率、金融授信等級或獨立供應商關係。
- 財務模型 Beneish／Dechow 完整輸入仍要使用獨立的已凍結文獻輸入證據政策；F4 原始營收驗證不代表模型八項／七項資料都齊備。
- 回滾：移除這三個伺服器環境變數後重啟 FastAPI；不需恢復 DB，因為從未變更 DB。

## 新增測試

tests/test_integrity_phase23_financial_source_release.py

已提交測試程式，**尚未在本機驗收環境實際執行**。最終需驗證 Page Quote、來源版本、缺資料與多公司隔離、完整 Phase 1.1 回歸、Flask API 和 Browser E2E，以及受保護資料庫哈雜湊不變性。
