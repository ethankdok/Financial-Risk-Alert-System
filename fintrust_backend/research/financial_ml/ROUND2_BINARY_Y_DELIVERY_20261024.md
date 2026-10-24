# FinTrust Round 2：真實公司年度 0／1 標籤資料集（2026-10-24）

## 結果與研究範圍
**已產生真實公開公司資料的 numeric Y**，但屬 SILVER（經來源核對的回溯研究標籤），
不是 GOLD（原始首次申報、完整逐年查詢、24 月觀察期審核通過）。
本輪不執行機器學習模型、不創造財務 X、不改動 production DB 或前端。

主要研究目標：
DOCUMENTED_ANNUAL_CONSOLIDATED_CORE_FINANCIAL_CORRECTION_OR_RESTATEMENT_OBSERVED_BY_ASOF
＝截至 2026-10-24，已查到的公司年度合併報表「核心財務金額更正／重編」紀錄。

此目標與「已證明財務舞弊」**完全不同**；因原始首次申報公布時間未全部核實，
也**不是事前 24 個月發生與否的嚴格 Y**。 `strict_24m_y` 留空、不得以此評估早期預警。

**實際完成 26 筆公司年度二元標籤：Y=1 共 8 筆，Y=0 共 18 筆。**
Y=1 來自 5 家有實際財報金額差異的發行公司公告轉載；
Y=0 來自 9 家各 FY2022、FY2023 申報索引「合併年報更補正＝無」的二手 MOPS 衍生資料。
後者是 **當前網站快照的觀察狀態**，不等於完整官方更正史已確認無事件，
不應當作最終 gold 陰性資料；所有數字都有來源網址。
為避免 0 過度自信，本輪並不把其 `negative_window_complete` 寫為 true。

## 8 筆 Y=1，逐年度公告來源
- 2305 全友電腦 FY2015；2017-02-15 公告重編 FY2015 合併財報。
  https://news.cnyes.com/news/id/3718617
- 3432 台端 FY2022；2024-04-23 公告 FY2022 合併資產／遞延所得稅改列。
  https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=7cffa3ea-9b03-4248-a893-f0a1966defd8
  （FY2023 不在此正例，避免把沒有證據的差額寫成核心金額已變更。）
- 6918 愛派司 FY2023；2025-02-13 重編商譽減損。
  https://news.cnyes.com/news/id/5861634
- 6485 點序 FY2023／FY2024；2025-05-27 更正年度合併存貨／營業成本／損益等。
  https://news.cnyes.com/news/id/5995322
- 7547 碩網 FY2021／FY2022／FY2023；2024-12-10 公告 FY2021 合併重編，
  FY2022／FY2023 為合併報表更補正（另有個體報表的重編，兩者不可混為一談）。
  https://news.cnyes.com/news/id/5805614

## 18 筆 Y=0 的來源範圍
2330 台積電、2454 聯發科、2317 鴻海、6488 環球晶、
2303 聯電、3034 聯詠、3711 日月光投控、3008 大立光、2603 長榮。
每家公司僅取網站實際顯示的 FY2022Q4／FY2023Q4 合併財報，
該頁標註「更(補)正：無」，各自附有可查詢網址：
https://toalpha.tw/stock/2330/filings  等。
來源為第三方轉錄官方資料，已做頁面內容核查，但不是 MOPS 完整
事件查詢紀錄。**不能因為網站上現況顯示無更正就推論全部歷史時間絕對沒有重編。**

這批便利抽樣的負例偏向大型知名公司、正例多為相對小型公司，
具有嚴重的取樣偏差風險。Round3–6 必須再由相似規模、
相同產業與相同年度的公司擴充負例，正式驗證時不能只用此
便利樣本宣稱泛化能力。

## 開發與檔案
- `round2_reviewed_binary_evidence_20261024.json`：每個公司年度的來源及人工核對結果。
- `round2_binary_labels.py`：先重新載入 Round1 immutable 索引，
  逐個核對正例是否在索引內具有相同股票、年度、日期、類型、來源網址。
  0 必須有指定股票與 2022/2023 年年度申報快照，不允許憑空全市場補 0。
- `round2_binary_research_labels.csv`：26 列；有真正 numeric `y`=0 或 1。
  仍標註 `exploratory_label_only=true`，而不是直接能宣稱正式財報舞弊績效。
- `round2_targeted_followup_queue.csv`：Round1 尚未升級的年度事件，不大量產生假的 0。
- `round2_binary_label_report.json`：實際 Y 數量、證據等級、SHA、不可使用的研究宣稱。

## 一次驗收

在 `fintrust_backend` 目錄：

```powershell
python -m unittest discover -s tests -p "test_financial_ml_round2_binary_labels.py" -v
python -m research.financial_ml.round2_binary_labels --out data/financial_ml/round2_labels
```

GitHub Actions `financial-ml-round2-binary-labels.yml` 也用**相同真實來源**
執行測試及輸出 artifact，沒有下載網路資料、沒有產生假事件，
允許同內容重跑但拒絕默默覆寫既有成果。

## 下輪交接（不是本輪實作）
Round3 只進行真實年度原始財務 X 欄位取得、數值覆蓋率、
缺值治理、與上述 26 筆 Y 之公司年度配對。光洋科 1785 保留最終案例，
永遠不進訓練選模。Round5 完成後再訓練傳統分類器，
最後才進行真正的獨立預測與泛化評估。
如未升級官方 as-filed 及 24 個月觀察期證據，模型只能稱
retrospective silver-label experiment，不可以稱 24-month early warning。


## 2026-10-24 Round 2 擴充：全市場資料與實際資料量稽核

使用者指出原有 **26 筆**遠不足以評估機器學習，因此直接在本 Round 2 分支擴充，不另開 Round。

### 已成功執行的官方公司主檔蒐集

新檔案：
- `round2_marketwide_universe.py`：抓取、保存 TWSE/TPEX 官方公司主檔原始回應、SHA，統一兩市場不同欄名，結合原 120 家名單及原本已知標籤。
- `test_financial_ml_round2_marketwide_universe.py`：測試不同市場 schema、重複鍵、CSV 退路、無標籤不能冒充 0、不可宣稱過去上市資格。
- `.github/workflows/financial-ml-round2-marketwide.yml`：對實際官方來源執行並上傳可下載 CSV/JSON/官方原始回應。

實際 CI：https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/40101670495

**實際官方連線成功：**
- TWSE `https://openapi.twse.com.tw/v1/opendata/t187ap03_L`：**1,091 家**。
- TPEx `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O`：**894 家**。
- 官方目前公司合計 **1,985 家**；保留不在目前名單的既有研究公司，總數 **1,997 家**。
- FY2013–2023 共 **21,967 個候選公司年度**。
- 現有 26 筆來源標籤只有 **25 筆落在 FY2013–2023：Y=1 七筆、Y=0 十八筆**；有一筆 6485 FY2024 的 Y=1 位於本次時間範圍之外。
- 未配對標籤 **21,942 筆**；可證實已取得合格 X+Y 的資料 **0 筆**。

**嚴重品質限制：** 21,967 只是現在公司名單與年度的笛卡兒積，再加歷史案例。它們未必當年已上市，可能包含尚未掛牌的年度；不含所有過去已下市公司。沒有官方完整事件檢索就不能轉成大量 Y=0。這個結果不能報告成幾萬筆機器學習訓練集。

### MOPS 歷史事件批次查詢實測

新增 `round2_mops_keyword_discovery.py` 及單元測試，使用舊式公開歷史主旨查詢 `ajax_t51sb10`，**限定 113/114 年兩個年度、兩個關鍵字，四次請求**，保存回應 SHA 與狀態，不繞過驗證碼、不不斷重試。GitHub Actions：https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/40101817264

結果：**4/4 回應都不是可解析的公告表格（每份約 800 bytes）**，
結果為 `NO_DOCUMENT_TABLE_NOT_COVERED`，**新增可核准 0/1 = 0**。
這代表此環境下這條舊版查詢路線不可用，不能以空結果宣稱「未發現重編」。
不要反覆執行同一舊式 endpoint。

### 可擴大的歷史事件來源與匯入工具

為了避免只靠逐家新聞查詢，新增 `round2_bulk_outcome_adapter.py` 和測試：
- 接受獨立取得的歷史公司年度事件 CSV；
- 嚴格要求合併年度報表、first_filed_at、事件日期、24 月完整追蹤截止、來源雜湊、正負明確標示；
- 事件在首次申報後 24 月內才可列 Y=1；沒有事件但完整 24 月來源涵蓋才可列 Y=0；
- 同公司年度重複、早於首次申報／晚於窗口事件、不完整負例、保留 1785 或無來源者拒絕；
- 匯入結果標為 `SOURCE_REPORTED_NEEDS_INDEPENDENT_AUDIT`，**不會憑 CSV 內容自稱已做過獨立官方驗證**。
- 此 adapter 的單元測試為合成資料，**目前沒有額外的真實大規模匯入檔，也沒有新增真的 Y**。

有研究價值但**須另行取得權限或匯出來源檔**的兩條路：
1. **TEJ TT2 上市櫃公司重編財報資料（1990 年起）**；若學校訂閱，可取得系統化的重編事件名單與年度，適合補足不同年代及下市公司，仍須核對標註定義、首次申報與事件時間。
2. **FinLab 重大訊息資料庫（2006 年起，>百萬筆公告）**；免費歷史資料範圍以服務條款及實際帳號權限為準，全文篩選後仍需確認受影響財報年度與更正性質。
資料庫網頁資訊不是資料本體，**不能宣稱我們已經下載或完成標記**。

### 擴充版目前驗收結論

官方現行公司名錄資料管線與來源驗證 **PASS**；
既有 silver numeric Y **26 筆**仍然有效地獨立保存。
**大型正式標註資料集尚未完成**，阻礙是真正的全市場歷史更補正事件資料，
不是再換一種分類器就能解決的問題。

下一步若要達成使用者要求的數千公司年度、上百正例，必須
**先取得可用的完整歷史事件原始批次資料**（TEJ TT2、合法匯出的公告歷史或可用的新版 MOPS 官方批次功能），
再以 bulk adapter＋原始申報歷史建立同定義標籤。
絕不能將 21,942 個未知年度直接轉成 Y=0。

### 擴充版執行

在 `fintrust_backend`：

```powershell
python -m unittest discover -s tests -p "test_financial_ml_round2_marketwide_universe.py" -v
python -m unittest discover -s tests -p "test_financial_ml_round2_mops_keyword_discovery.py" -v
python -m unittest discover -s tests -p "test_financial_ml_round2_bulk_outcome_adapter.py" -v
python -m research.financial_ml.round2_marketwide_universe --out data/financial_ml/round2_marketwide
```

批次歷史事件 CSV 若由可信來源實際取得後：

```powershell
python -m research.financial_ml.round2_bulk_outcome_adapter --input-csv <PATH_TO_REAL_HISTORICAL_CSV> --out data/financial_ml/round2_bulk
```

不得把 synthetic test fixture 送進正式訓練。
