# 臺灣投資詐騙題材與 STRUX 式資料集：2026-09-26 初步查核

## 初步查核結果
- 刑事局公開案件證實 AI 半導體／再生能源曾同案出現（2026-06-04，整案財損逾 3000 萬）。新聞來源不可拆解該案件在不同題材各有多少件或財損。
- 中央社公開案件可找到 2024-03-08 生技未上市股話術、2026-03-10 生技未上市股疑涉詐偽、2026-06-18 蟲草素技術投資疑涉詐。不同案件性質（散戶推銷、公司內部發行、法人投資）應先制定納入／排除規則。
- 2021 未上市股案同時利用疫苗、電動車與 5G 題材；跨題材案件不可當成每產業各一獨立案件，也不得把總財損分配到個別產業。
- **目前沒有發現政府發布的「半導體 vs 生技假投資發生件數」完整母體資料，故不能宣稱誰較常見。** 本資料夾 CSV 僅為**方便後續擴充的非隨機公開案例 seed**，不能拿它的筆數算發生率或作統計檢定。

## 可驗證案例登錄
參閱 `research/taiwan_investment_scam_case_seed.csv`；每筆含唯一案號、來源、發布日期、投資題材標籤、案件類型、財損註記，以及跨題材／重複報導排除提醒。每個調查群組只計一件；不要把發布日當犯罪發生日。

## STRUX 式資料可行性
1. MOPS 法說會一覽表、公司 IR 法說會簡報／公告：可建立 company、ticker、industry、fiscal_period、conference_date、prepared_text、source_url、document_hash 等欄位。官方 MOPS 有法說會與歷史重大訊息，但**簡報不等於完整逐字稿**。
2. 金管會／證交所公開資料：每月營收、XBRL、財務報告與公司分類。數值資料可與跨期文字結果並呈，不宜直接混到 JSD 詞頻。
3. FinmoConf 有台股歷年法說會簡報索引（第三方），可協助尋找 PDF；下載與批次使用須核對網站授權／條款。
4. Hugging Face `andynoodles/Taiwan-Financial`：**財報版面 OCR**，非逐字法說會；15 公司、138 份 2021–23 財報、約 194k 區塊。適合測試財報文字抽取但要處理同頁 OCR 錯誤與非完整文件重組；下載授權須查。
5. HF 搜尋結果出現 `jchilling/taiwan-earnings-calls`，但無法連線到實際資料集頁面或確認可下載，**暫不納入可用資料清單**。

## 下一階段正式研究設計
- 產業發生率：需同一時段、同一通報母體、相同定義的全部案件；請求警方按「投資題材」統計，若取不到，只能做「公開案例中提及的題材次數」，明確註明選樣偏差。
- 文本比較：同一上市公司相鄰季度的**同種文件**（例如每季 prepared remarks 與下一季 prepared remarks）；若取得的是 PDF 簡報，應一致地比較同類章節，而非將完整 PDF 與一段新聞相較。
- 門檻：與 STRUX 分離，以繁中同種文件、相鄰季度、相近篇幅計算 JSD 與 TF-IDF Cosine，分別建立同業／同公司校準分布及數量、時間範圍，並在留出時期驗證。
- Firestore 結構：`document_sources`（公司、產業、來源、文件日期、期間、來源 URL、SHA256、抽取版本）；`shift_calibrations`（產業／文件種類／語言／斷詞與向量方法、歷史期間、樣本對數、percentiles）；`shift_runs`（每個比較的兩份文件 ID、JSD、Cosine、threshold ID、品質、判斷、計算時間）。
- **注意現有 `taiwan_shift.py` 是按「同來源同產業的相鄰月份群組文章」設計，為防詐公開闢謠文的試驗入口；它不是按公司相鄰季度法說會的最終 STRUX 式方法。找到產業資料後，應另外改造其分組鍵（ticker、document_type、fiscal_quarter）及門檻校準流程，再匯入資料庫。** 特別是目前的「前序30組相鄰月份」不能硬套到每季法說會；應調整並揭露校準母體。

## 一手與原始資料入口
- 刑事局 AI 半導體與再生能源案 https://www.cib.npa.gov.tw/ch/app/news/view?id=1885&module=news&serno=6b1c2c2d-4597-4b14-b1f0-d8fa2ab597c6
- 刑事局 2021 多產業未上市股票案 https://www.cib.npa.gov.tw/ch/app/news/view?id=1885&module=news&serno=d753118f-4b12-47bc-928d-baeca2ae5eea
- CNA 生技案 2024 https://www.cna.com.tw/news/asoc/202403080308.aspx
- CNA 生技公司案 2026 https://www.cna.com.tw/news/asoc/202603100260.aspx
- CNA 蟲草素案 2026 https://www.cna.com.tw/news/asoc/202606180178.aspx
- MOPS https://mops.twse.com.tw/
- TWSE 法說會簡報付費主動派送 https://eshop.twse.com.tw/zh/mops/detail/8a82e9e69b05c644019b2b7a58a7001d
- 台股法說會索引 https://finmoconf.diveinvest.net/
- 財報 OCR 公開資料 https://huggingface.co/datasets/andynoodles/Taiwan-Financial
