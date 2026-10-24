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
