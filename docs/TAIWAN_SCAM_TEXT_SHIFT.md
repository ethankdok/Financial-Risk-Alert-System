# 臺灣假投資文本與財經資料：資料選型及 Data Shift 實作

## 問題定義（不要把「案件數最多」與「財損最高」混為一談）
- 刑事警察局公布 2026/06 全國受理件數：網路購物 29%（最多），假投資 11%，假交友投資詐財 8%；財損以假投資 32% 居首，假交友投資詐財 22%。
- 本系統原有股票／金融資訊查證，研究範圍可鎖定「假投資詐騙」，但它不是所有詐騙中件數最多的類型；股票、虛擬資產等是常見話術標的，不等於能從這個統計判定哪個細分產業件數最多。
- https://www.cib.npa.gov.tw/ch/app/news/view?id=1887&module=news&serno=6b3742ba-fda4-4ed4-ab3b-ff761d30af9b

## 資料來源與用途

| 來源 | 實際內容 | 適合用途 | 注意 |
|---|---|---|---|
| 165 官方闢謠 CSV https://data.gov.tw/dataset/38262 | 編號、標題、發布時間、發布內容 | 假投資／詐騙話術的公開案例輔助語料 | 闢謠文章不等於詐騙訊息原文；先標註主題；不同主題勿混 |
| 165 假投資網站 CSV https://data.gov.tw/dataset/160055 | 網站名稱、網址、通報件數、統計日期 | 詐騙網址交叉查驗 | 沒有長篇詐騙話術原文，不能直接做文本 JSD |
| 165 打詐儀錶板 https://165dashboard.tw/ | 各類詐騙案件／財損 | 研究題目及抽樣優先序 | 統計不是文本語料 |
| TWSE OpenAPI https://openapi.twse.com.tw/ | 每日上市公司重大訊息、公司資料等 | 真實臺灣公告時間序列（官方基線） | 常用 API 是當前資料；如需長歷史請另外存檔並查歷史 MOPS |
| MOPS https://mops.twse.com.tw/ | 歷史重大訊息、法說會、財報 | 同公司或同產業跨期官方文字 | 確認使用條款、日期與原始網址；不要直接混入假投資廣告 |
| 臺灣財經繁中語料 https://huggingface.co/datasets/lianghsun/tw-finance-159M | 財經／產業新聞（text、url、updated_at） | 補充臺灣財經語言背景或同媒體時間序列 | 約 470MB，下載需要接受使用條件；CC BY-NC-SA 4.0；無詐騙標籤 |

目前**未確認存在**可直接下載、同時具有「臺灣假投資原文 + 經人工確認的真假標籤 + 日期 + 足夠連續月份」的單一 STRUX 式整合資料集。要自己整合公開語料，保留資料來源與標籤品質。資料集未放在 GitHub，也未宣稱模型經真實資料驗證。

## 新模組如何與 STRUX 共存
- 原 `data_shift.py` 不變，繼續分析英文 earnings calls 與 STRUX 的歷史門檻。
- 新 `taiwan_shift.py` 走繁體中文 pipeline：中文連續字串拆成二字、三字 n-gram；英文詞另取 token。
- 每篇文先建立 token 頻率分布，逐篇正規化再跨篇平均得到 P、Q。
- JSD(P,Q) = 0.5 KL(P || M) + 0.5 KL(Q || M)，M=(P+Q)/2，log base 2。
- 同批文件共同建立 TF-IDF，分別平均各期各篇的 TF-IDF 向量，再算 Cosine。這與 STRUX 英文 tokenizer **不是同一量測定義，不能套 STRUX 的 P90=0.366397 或 cosine P10=0.664451**。
- 同產業、同資料來源、歷史**連續月份**比較建立 JSD P90/P95 和 Cosine P10/P05。僅用目前分析期之前的資料校準；少於 30 組合就回傳 `未校準` 而非亂填門檻。
- 聯合判斷：JSD >= 自己的 P90 且 Cosine <= 自己的 P10 → 顯著*文字分布漂移*（仍須人工追查）。不是「偵測到詐騙」。

## 資料格式（CSV，UTF-8 with BOM 可讀）

```csv
date,text,sector,source,ticker,url,label
2024-01-15,"公司公告本季營收與接單展望...",半導體,mops,2330,https://example.invalid/source,unlabeled
2024-02-10,"公司公告新增投資計畫...",半導體,mops,2330,https://example.invalid/source,unlabeled
```

上面兩行**只是欄位示意，不是真實資料**。必要欄位：`date`（ISO 日期）、`text`、`sector`（研究者一致的產業分類）、`source`（必須一致，例如 mops 或 165_debunk）。建議加 `ticker`、`url`、`label`，保留原始文獻與驗證狀態。切勿把未人工核實的網路文本標成詐騙。

整理好真實 CSV 後，設定環境變數（例如於 Mac 專案資料夾）：

```bash
export TAIWAN_SHIFT_DATASET="$PWD/data/taiwan_texts.csv"
python3 app.py
```

API 與既有 Flask 合併：

```http
POST /api/taiwan-shift/analyze
Content-Type: application/json

{"sector":"半導體","source":"mops","period_1":"2026-07","period_2":"2026-08"}
```

每期至少 5 篇資料才能計算，且必須相鄰月份。**只有累積至少 30 對符合條件的歷史相鄰月份**，才會輸出資料集專屬門檻及聯合規則。不能從一篇貼文對一篇官方公告計算，宣稱可據此證明真假。

## 研究驗證待辦
1. 先定義唯一研究任務：例如「臺灣上市公司同產業重大訊息跨期分布變化」與「疑似假投資話術」是*兩個不同任務*；前者先建時間序列及驗證，後者另建立已核實的文字標籤。
2. 蒐集每月同來源真實文本，紀錄抓取日與 URL、去重、移除模板文字；台灣產業別優先採證交所產業分類，勿混合自訂分類。
3. 使用資料年份切分校準集／測試集；先比較月份篇數和篇幅差異，避免月報樣式或來源轉變被誤認漂移。
4. 人工抽查部分高／低漂移結果，建立 drift 原因標記；不能直接使用警方月份統計當作逐篇文章的真實詐騙標籤。

## 方法及資料引文
- Lin, J. (1991), Divergence measures based on the Shannon entropy, IEEE Transactions on Information Theory. https://doi.org/10.1109/18.61115
- scikit-learn `TfidfVectorizer` documentation: https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html
- 刑事警察局 2026/07/20 詐騙統計與投資詐騙 https://www.cib.npa.gov.tw/ch/app/news/view?id=1887&module=news&serno=6b3742ba-fda4-4ed4-ab3b-ff761d30af9b
