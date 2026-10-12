# FinTrust NFM reviewed-source release v1（管理者核准機制）

**定位：** 官方非財務資料候選值通過人工覆核後，才讓唯讀 Workbench F4 使用。同一發行人自行申報的員工數不是第三方獨立驗證。此機制沒有建立新的資料庫，預設完全關閉。

## 先產生候選值（不會修改資料）

在 fintrust_backend：

    python -m scripts.scan_nfm_archive --root <已歸檔資料夾> --pdf <相對PDF路徑> --pdf-sha256 <原PDF雜湊> --pages <相對pages-json路徑> --pages-sha256 <pages-json雜湊> --ticker 2454 --fiscal-year 2024

掃描器會核對原始 PDF 與 pages JSON 的各自 bytes SHA，再列出員工人數候選值、頁碼、擷取原文與年份線索。但兩份檔案各自 SHA 正確，不代表 JSON 原文必定由該 PDF 生成，也無法確定公司、會計期間、scope 或公告日期。

## 審核與核准

必須由研究成員／資料管理者對照原始 PDF 檔案以及官方 MOPS／TWSE 登錄來源，確認公司代號、財政年度、合併／個體範圍、數值、單位、員工計入範圍、期末／平均基礎、官方來源網址與實際公開時間。

只有獲人工批准的 Release JSON 可以進入系統。Release JSON 應保存在 Git Repository 外、不含敏感路徑與金鑰。每筆 records 的欄位：

- ticker（4–6 位數）、fiscal_year、measure（employees）、value（正數 Decimal 字串）、unit（persons）。
- scope（consolidated 或 individual）、period_basis（year_end_stock 或 annual_average）、measurement_policy（必填明確定義）。
- filing_version_id、source_url（HTTPS 官方主機）、source_sha256（原 PDF 的 SHA-256）、archive_pdf_relative_path（僅封存根目錄內的相對路徑）、published_at（如未知可為 null，絕不可把擷取時間當公告時間）。
- review 物件：status=approved、ticker、fiscal_year、pdf_sha256、scope、review_id、verbatim（8–500 字元，原文）、reviewed_value、reviewed_unit=persons、pdf_page（從 1 起算）、reviewed_at（有時區）、source_origin_confirmed、pdf_page_quote_confirmed、fiscal_period_confirmed、metric_definition_confirmed、statement_scope_confirmed、positively_scale_related（均須人工核對後為 true）。
- 頂層 release_version 必須為 fintrust_nfm_reviewed_release_v1，records 為 1–80 筆。

由資料管理者在核准版本的完整 JSON bytes 上計算 SHA-256，並把核准值放在**伺服器環境變數**（不得提交有值的設定檔）。

## 選用環境設定

只有下列三項全部存在時才會啟用，不設任何一項時維持 Phase 1.1 的既有行為：

    FINTRUST_NFM_REVIEW_MANIFEST=<唯讀已核准manifest檔案位置>
    FINTRUST_NFM_APPROVED_RELEASE_SHA256=<管理者核准的manifest SHA-256>
    FINTRUST_NFM_ARCHIVE_ROOT=<本機已封存PDF根資料夾>

載入器先核對 manifest bytes，逐筆核對原 PDF bytes、官方網址、人工覆核欄位、版本、公司與期間。任一筆錯誤，整個發布檔都拒絕。不得使用瀏覽器或外部任意 HTTP 請求帶入這三個設定值。

**注意：** 正確 Manifest SHA 證明管理者釘選的是哪一版內容，不等於監管機構的數位簽章。人工來源核對是否可靠，仍需由研究成員與方法負責人負責。

## F4 與正式資料仍然有缺口

F4 需要**兩個相鄰年度營收**和**兩個相鄰年度同口徑員工人數**。本側載機制只補充核准的非財務來源；Phase 1.1 原財報 facts 尚沒有正式原 PDF SHA 與位元組驗證，因此就算核准 NFM 發布檔，現有正式 2330／2454 的 F4 仍可能正確顯示 not_computable。不得為了顯示數值而偽造 source_sha256 或 source_document_verified。

STRICT_AS_OF 仍由 Phase 1.1 的 Workbench 拒絕；有 published_at=null 的 Release 只供 CURRENT_REVIEW 候選資料，不能做歷史事前預測。

## 測試、風險與回滾

測試：tests/test_integrity_phase23_nfm_release.py（使用臨時假 PDF）；完整系統需再測與資料缺口條件的互動，以及 Option B protected SHA 不變性。

回滾：取消這三個環境變數並重啟 API，即不載入任何核准發布檔。毋須修改或回滾正式資料庫。

不合規的 Manifest、Symlink、路徑跳脫、PDF bytes 不符、未審核頁碼、資料年份不符、偽造網址、明確日期卻無公告時區等均禁止進入可計算 F4。
