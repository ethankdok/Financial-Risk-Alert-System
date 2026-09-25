# 台灣半導體 STRUX 式季度法說會資料集（TSMC 2330 Pilot）

## 本分支已完成的項目
- 真實資料來源已核實：TSMC 官方投資人關係網站列有跨年度季度法說會逐字稿。來源頁： https://investor.tsmc.com/english/quarterly-results/2024/q1 ， https://investor.tsmc.com/english/quarterly-results/2025/q4 。
- `research/tsmc_pdf_overrides.csv` 收錄已找到的官方 2024Q1 與 2025Q4 逐字稿 PDF URL；其他季度由單執行緒抓取程式嘗試讀取官網來源頁取得連結，無法解析的留待人工核查。
- `scripts/build_tsmc_corpus.py` 下載 PDF、抽取文字、驗證官方 HTTPS 網域、紀錄 SHA256／來源網頁／文件期間，產生本機 CSV 與逐期狀態表。
- `scripts/calibrate_tsmc_shift.py` 使用目前 repo 原有的**英文** JSD 與 TF-IDF Cosine 演算法，對台積電同一公司**相鄰財務季度、同種類完整逐字稿**比對；歷史樣本只取目標期開始前，排除資料不足/長度差異過大的 pairs。
- 用歷史有效樣本產生本語料的 JSD P90/P95、Cosine P10/P05；少於 30 對的校準結果是 null，不能輸出正式分級。30 對只是初步工程下限，實際研究仍需信賴區間、留出集與他公司驗證。
- 提供**使用者明確指定** `--upload-firestore` 時才寫 Firestore 的 `document_sources`、`shift_calibrations`、`shift_runs`。上傳的僅為來源 URL、SHA256、指標、門檻與對應資訊，**不會**將他人的完整 PDF 原文放進 DB。

## 操作（Mac；在 repo 根目錄）

```bash
git fetch origin
git switch feature/tsmc-quarterly-corpus
git pull origin feature/tsmc-quarterly-corpus
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/build_tsmc_corpus.py --start 2017 --end 2025
# 人工檢查 data/tsmc_corpus/tsmc_source_index.csv；
# 有 needs_manual_review 時，找到官方 PDF 後補到 research/tsmc_pdf_overrides.csv 並重新執行。
python3 scripts/calibrate_tsmc_shift.py --ticker 2330 --period1 2025Q3 --period2 2025Q4
```

結果：本機 `data/tsmc_corpus/calibration_result.json`。請先確認完整性、PDF 轉文字格式和語言，才能當研究成果使用。部分逐字稿包含翻譯與 Q&A；目前先固定為**完整逐字稿對完整逐字稿**，不得與僅 prepared remarks 的 STRUX 結果直接比較。

### 經人工核查來源及口頭報告
1. 同一份資料格式：`ticker,company,industry,year,quarter,period,document_type,language,text,source_page,source_pdf,sha256,text_length`。
2. 先做跨期相鄰樣本對及 PDF 文字品質檢查。
3. JSD(P,Q) = 1/2 KL(P||M) + 1/2 KL(Q||M)，M=(P+Q)/2，`log2`；TF-IDF 向量 cosine 越低、文字表示越不相似。
4. 畫出**台積電該文件集合**歷史指標分布，計算 P90/P95／P10/P05。
5. 檢查目標值是否滿足 JSD >= P90 且 Cosine <= P10，只有雙指標均成立才顯示待查的顯著文字漂移；不推論公司不實揭露或涉及詐騙。

### Firestore 寫入（與組員確認同一 GCP project 後才執行）
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/approved-service-account.json"
python3 scripts/calibrate_tsmc_shift.py --ticker 2330 \
  --period1 2025Q3 --period2 2025Q4 \
  --upload-firestore --gcp-project YOUR_PROJECT_ID
```

上傳前會檢查 >=30 組有效歷史資料。若 GCP 未授權或資料不足，不能宣稱已整合並寫入正式 Firestore。不可提交 service account 或任何 credential。

## 重要研究限制
- 本分支只是**半導體資料可行性 pilot**，台積電既非已查核詐騙案公司，也不能單憑法說會漂移推導投資詐騙。
- 「半導體或生技哪個最常被詐騙利用」目前無同一母體的完整官方產業統計；個別新聞數量不等於發生率。另一分支 `feature/taiwan-scam-text-shift` 收錄可追溯的案件種子集，尚須擴充與一致標註。
- 真正**產業**層級的歷史門檻需要同文件類型、多家半導體公司且長期間的資料；只有 TSMC 歷史資料僅能先說「TSMC pilot 門檻」。
- 台積電原始逐字稿可能包含中英文混用與問答格式變化；必須抽查文本且固定比較範圍。中文法說會需獨立中文 tokenizer 與新的校準集；現有 `data_shift.py` 的英文校準數字不得直接沿用。
- 當前 CI 為無網路的邏輯測試，**不是**已成功擷取所有 PDF 的證據。下載步驟需在具備網路的本地機器執行，資料來源若變動需人工確認。
