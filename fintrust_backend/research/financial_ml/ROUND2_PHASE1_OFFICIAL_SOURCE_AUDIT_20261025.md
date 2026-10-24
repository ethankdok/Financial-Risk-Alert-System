# FinTrust Phase 1 — 官方年度合併財報重編 Y1 來源查核紀錄
Date: 2026-10-25. Branch: feature/financial-ml-round2-binary-labels-20261024.

## 145 案件實測結論

- 45 件重編候選 + 100 件潛在對照組，共 145 件。
- 45 / 45 正例候選成功以「公司代號＋完整公告標題」配對至使用者合法取得的 FinLab important_info_announcement 原始記錄，保存日期、market、clause、sequence、公告全文 SHA-256。
- 37 件候選公告日期不晚於普通年度財報法定截止日期加 24 個月；8 件較晚。這僅為時間疑義，不是個別公司原始財報真正公布日期；不得據此核准負例或取消正例。
- 1 件（1203-FY2017）有公司自行出版的董事會決議日期佐證，並完成資產、營業成本和淨利的更正前後金額算術核對。
- 原始年報首次 MOPS 公告日期的獨立驗證數量：0。
- 原始版＋重編版 MOPS PDF/XBRL 成對版本確認：0。
- 對照組完整 24 個月官方公告及財報版本覆蓋驗證：0。
- 正式 Y1 核准：Y=1 為 0，Y=0 為 0，UNKNOWN 為 145。

重要：使用者要求實際開始 Phase1，本輪確實完成公告來源對照及第一家公司財報重編數字核對，但目前所能存取的公開搜尋工具無法獨立取得這些案件 MOPS 歷史原始首次申報日期及成對申報版本，不能聲稱已完成正式 Y1。

## 實際案例：1203 味王 FY2017（民國106）

FinLab 當地來源公告：2018-05-11 17:25:42。
內容明確區分：個體財報附註更正；合併財報重編。

發行公司年報文件載明 2018-03-29 董事會原始合併年報通過與 2018-05-11 董事會重編通過。
- https://www.vewong.com/ecmas0069/store/F4/ANN_REP_2017.pdf
- https://www.vewong.com/ecmas0069/store/F4/ANN_REP_2018.pdf

公告完整文字的公開轉載：
https://tw.stock.yahoo.com/news/%E5%85%AC%E5%91%8A-%E5%91%B3%E7%8E%8B%E5%85%AC%E5%8F%B8%E7%B6%93%E8%91%A3%E4%BA%8B%E6%9C%83%E9%80%9A%E9%81%8E%E6%9B%B4%E6%AD%A3106%E5%B9%B4%E5%BA%A6%E5%80%8B%E9%AB%94%E8%B2%A1%E5%8B%99%E5%A0%B1%E5%91%8A%E5%8F%8A%E9%87%8D%E7%B7%A8106%E5%B9%B4%E5%BA%A6%E5%90%88%E4%BD%B5%E8%B2%A1%E5%8B%99%E5%A0%B1%E5%91%8A-094644438.html

核對 3 組科目（單位新台幣仟元）：
- 資產總額 9,079,372 → 9,192,281，差額 +112,909；
- 營業成本 4,287,711 → 4,174,915，差額 -112,796；
- 本期淨利 633,605 → 746,401，差額 +112,796。

經公司文件與公告內容交叉確認確有歷史年度合併財報重編線索；但 BOARD DATE 不等於 FIRST-PUBLIC MOPS date，原始及更正的官方 MOPS 文件版本亦尚未保存，所以 1203-FY2017 的正式 Y1 保持 UNKNOWN，不能自行推定為 1。

## 研究規範

- 公司＋受影響之合併年報 FY 是標籤單位，同一公告多期別不可重複算獨立正例。
- 正式正例需有實際 MOPS 原始公告日、公告後 24 個日曆月內重編或核心數值更正證據、官方原始及重編資料、影響範圍。
- 正式負例需完整 MOPS 歷史查詢覆蓋及首次原始年報日期證據；沒有 FinLab 搜尋結果或 TEJ 非零次數等於 0 均不構成負例。
- 財報重編屬預警研究，不等於公司造假或違法。
- 光洋科 1785 保留獨立測試不納入訓練；把更正後或重編事件發生之後的財務數字作原始訓練 X 屬資料洩漏。

法規證據：證券交易法第36條，通常年度終了三個月內公告申報，但仍須以公司實際首次申報日期判定：
https://twse-regulation.twse.com.tw/TW/law/DOC01.aspx?FLCODE=FL007009&FLNO=36
證券交易法施行細則第6條，年度財報重編條件與一般更正差異：
https://twse-regulation.twse.com.tw/TW/law/DOC01.aspx?FLCODE=FL007010&FLNO=6

## GitHub / 本機重現

Code: fintrust_backend/research/financial_ml/round2_phase1_official_source_audit.py
Test: fintrust_backend/tests/test_financial_ml_round2_phase1_source_audit.py
CI workflow: .github/workflows/financial-ml-round2-finlab-events.yml

在 fintrust_backend 目錄執行：

python -m research.financial_ml.round2_phase1_official_source_audit --sprint-csv data/financial_ml/round2_official_sprint_20261025/official_y1_evidence_review_sprint_private.csv --finlab-csv data/financial_ml/finlab_restatement_candidates.csv --out data/financial_ml/round2_phase1_source_audit

輸出兩份私人研究檔：phase1_145_case_evidence_ledger_private.csv 與 phase1_quality_summary.json。另可依原公告匯出私人內容 trace CSV 做人工證據覆核，不得上傳公開 GitHub。
原始 TEJ、FinLab 授權資料皆僅存於本機資料目錄。

## 下一輪決策閘門

本輪已確實查到 145 件來源線索和可用證據限界。下一輪應在有歷史 MOPS 記錄存取權限的環境取得首次公開日、原始與修正版次及申報時間，先優先 1203，再處理已交叉證明的 P0。
對照組必須得到完整 24m 官方更正歷程的可稽核覆蓋，否則仍為 UNKNOWN。
