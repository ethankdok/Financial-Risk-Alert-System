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
