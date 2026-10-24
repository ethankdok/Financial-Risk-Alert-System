# FinTrust Financial ML — Round 1 事件資料庫交付（2026-10-24）

## 完成工作與邊界

Round 1 只負責具來源追蹤能力的財報更正／重編／涉嫌事件索引。沒有建立監督式 Y、沒有訓練或預測、不改網頁、不寫入 production DB、不修改其他同學模組。

開發分支：feature/financial-ml-round1-event-registry-20261024
起始研究分支：feature/fintrust-independent-audit-risk-benchmark-20261020

## 已匯入的真實資料

既有 Round10：12 筆公司公告線索、11 家公司。
既有 Round9：1785 光洋科（櫃買公告）、3027 盛達、8299 群聯（司法文書）、6452 康友-KY（投保中心資料），共四件案例。
既有原名單外研究：2305 全友 FY2015、3662 樂陞 FY2014/2015、2384 勝華 FY2014/2015，共五筆年度線索、三則事件。
補充：5210 寶碩 2026/10/21 偵辦新聞＋公司官網聲明，僅屬涉嫌事件；另新增 3432 台端 FY2022–2023、6918 愛派司 FY2023、7547 碩網 FY2021–2023、1806 冠軍 FY2023 的公告年季來源。注意 7547 不同年度的「重編」與「更正」須分辨，1806 是主管機關要求重行公告的紀錄。

共 **26 條原始來源紀錄**，預期去重 **24 個事件、23 家公司**。3662 與 2384 不同年度的同一公告合併成一事件，仍保留逐年度連結。
光洋科永遠是獨立保留案例，不進訓練或調參。

公開來源參考：
- 櫃買中心光洋科正式公告：https://www.tpex.org.tw/storage/eb_data/10512/10502015021.htm
- 點序 2025/5/27 公司公告轉載：https://news.cnyes.com/news/id/5995322
- 寶碩調查新聞：https://udn.com/news/story/7321/9827567
- 寶碩公司聲明：https://www.apex.com.tw/
- 其他每筆網址與原始索引：CSV source_url、supplementary_url、origin_record_ids 欄。

**不能混淆來源證據層級：** 不是每一則公告都已取得官方原件位元組或獨立驗證，沒有完成全市場歷史公告涵蓋率。此輪交付的是具體有真實來源的「事件候選資料庫」，不是正式正負標籤，也不是官方全市場資料庫。

## 輸出

1. round1_event_registry.csv — 每一事件公告一列，含類別、來源、年季、審核狀態。
2. round1_event_period_links.csv — 事件與受影響年度／季度連結；季報不冒充年報。
3. round1_event_registry_report.json — 來源與結果 SHA-256、事件及公司數、類別分布、年度連結數。

annual_target_candidate 僅標記值得後續調查的公司年度，不代表 Y=1。
training_label 目前全部空白；training_admitted 全 false。
輸出採不可覆寫、可重跑相同內容的規則。

## 單一 Round 驗收

在獨立 ML worktree 的 fintrust_backend 目錄執行：

    python -m unittest discover -s tests -p "test_financial_ml_round1_event_registry.py" -v
    python -m research.financial_ml.round1_event_registry --out data/financial_ml/round1_events

GitHub Actions financial-ml-round1-events.yml 會執行以上測試與實際來源導入，驗證 26→24／23 的數量、年度來源及 Holdout，並輸出 fintrust-round1-event-registry artifact。CI PASS 僅代表本輪導入與測試通過，不代表新聞與司法內容已全部取得原始位元組。

## 下一輪交接

Round2 將使用事件索引＋完整公司年度母體＋指定觀察期間建立實際 0/1 標籤。Round3 建立財務 X，Round4–5 驗證品質、特徵及資料分割。**Round5 結束後先使用 Logistic Regression、Decision Tree、Random Forest、KNN、SVM、Naive Bayes 等適合的傳統分類演算法訓練、比較（必要時包括二元、多類別、方向分類），最後才進行獨立案例推論。** 暫不開發神經網路。遇到問題優先在當輪集中修復，避免無止境拆分 Round。
