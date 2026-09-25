# MOPS 法說會 PDF 擷取流程

此流程查詢 MOPS `t100sb02_1` 的公司與公告年度清單，保留清單 HTML 與 SHA-256，依公告中的 PDF 檔名去重，透過官方 `FileDownLoad` 表單下載，每頁保留文字和頁碼。圖表或圖片頁另存 PNG，供後續分析與人工核對。重跑同一公司與年度時會重新查詢並下載，於 manifest 標記 `new`、`updated` 或 `unchanged`。

在 `fintrust_backend` 目錄執行：

```bash
python -m pip install -r requirements.txt
python -m scripts.sync_mops_conference_pdfs --ticker 2330 --year 2025 --output data/official-ir-pdfs
```

排程可定期執行相同命令（例如每日一次）。以非零退出碼 2 偵測不完整批次，讀取 `data/official-ir-pdfs/2330/2025/manifest.json` 的逐檔原因。部署時須把 `--output` 指向持久化儲存空間；容器的暫存檔系統不適合保存歷史版本。尚未建立雲端排程或儲存桶。

`status=complete` 需要：清單格式可驗證、沒有未處理的分頁、所有列出的附件都能下載並解析、每頁有足夠文字，而且沒有尚未驗證的圖表或圖片。只要一個條件未滿足，整批標記 `failed`，但保留已取得的檔案作為後續修復的證據。影像頁即使 OCR 產生文字，也不能證明圖表中的數值和關係已完整擷取，因此會標記 `needs_review`。目前沒有聲稱法說會的圖表已完成語意分析。

已用官方 2330 民國 114 年清單及當次取得的附件離線重播。該清單有 16 筆公告、8 個不同檔名；需要以有權連線 MOPS 的排程環境再執行 HTTP 端到端測試。若官方表格格式或分頁方式變更，流程會拒絕把不確定的批次判為完成。

## 2026-09-26 live 連線驗證

已在本機非沙箱網路以 `2330 / 2025` 重跑 live MOPS 流程：

```bash
cd fintrust_backend
python -m scripts.sync_mops_conference_pdfs \
  --ticker 2330 --year 2025 \
  --output data/official-ir-pdfs-live-test
```

結果：

- MOPS 清單查詢成功：`rows=16`、`listing_pages=[1]`。
- 附件去重成功：`expected_pdfs=8`。
- `FileDownLoad` 下載成功：`downloaded_pdfs=8`。
- PDF 文字解析與 manifest 寫入成功：`parsed_pages=98`。
- 批次狀態仍為 `failed`，不是 `complete`：此執行環境的 Python venv 未安裝 PyMuPDF，無法做頁面視覺層偵測與 review image render，因此 `pages_requiring_manual_review=98`，每頁保留 `visual_detection_unavailable`。這代表「PDF 已下載且文字層已解析」，不代表圖表或投影片中的數值已完整分析。

真實環境修正紀錄：

- Python 3.14 對 MOPS 憑證觸發 `Missing Subject Key Identifier` 的 strict X.509 驗證錯誤；程式改為保留預設 CA/hostname 驗證，但關閉 `VERIFY_X509_STRICT` flag。
- MOPS 清單中的 PDF onclick 只設定 `fileName`；`step=9`、`filePath=/home/html/nas/STR/`、`functionName=t100sb02_1` 來自頁面上的 `fm_fileDownload` hidden form。下載 payload 必須合併 hidden defaults 與 onclick filename。
- MOPS 分頁按鈕可能以 `page(0)` 表示第一頁；parser 以按鈕顯示值修正為 page 1，並逐頁下載所有可見頁碼。若未來出現多頁，manifest 會列出所有 `listing_pages` 並保存每頁 HTML 與 hash。

後端已提供查詢契約：

- `POST /api/v1/financial/admin/companies/{ticker}/conference-pdfs/sync`
- `GET /api/v1/financial/companies/{ticker}/conference-pdfs/{year}/status`
- `GET /api/v1/financial/companies/{ticker}/conference-pdfs/{year}/documents`
- `GET /api/v1/financial/companies/{ticker}/conference-pdfs/{year}/documents/{filename}/pages`
- `GET /api/v1/financial/companies/{ticker}/conference-pdfs/{year}/documents/{filename}/analysis`

目前 repository 實作是可配置的本機 archive 目錄，API contract 已明確把 `storage_contract` 標成 `local_file_archive_only`。部署前須改接持久化物件儲存與 metadata store（例如 GCS + Firestore），不能把 Cloud Run 暫存磁碟當唯一副本。
