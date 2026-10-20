# 光洋科 1785｜重編前財務資料回測（更正最終案例方法）

## 研究方法更正

**模型輸入必須是重編前的財務金額**；重編後只用於回看對照，
不得加入訓練、凍結模型輸入、缺失值填補或模型選擇。

既有光洋科文獻研究 2013–2015 使用重編後 XBRL 的 M-Score/F-Score
可保留為歷史財報計算，但**不是使用重編前資料所做的預測**，
不得當作本次最終案例的主要模型結論。

## 可直接取用的正式來源

使用既有本機封存：
`historical_audit/packages/fintrust_1785_asof_2016-11-14.zip`

檔案內有 `data/restatement_comparisons.csv`（**158** 筆官方公告科目，
合併 79 筆、個體 79 筆），每筆同時提供：
`pre_restatement_value`、`post_restatement_value`、
`sign_factor`、`published_unit`、`fiscal_year`、
`accounting_framework`、`disclosed_at` 和原公告 SHA。

篩選條件：**1785、合併報表、FY2013–2015、TIFRS、12 個 Round3
財務金額欄位中確實存在者**。單位用官方 `TWD_thousand` 正規化為
完整 TWD，成本和收益保留公告的 `sign_factor`，
審核官方「重編後 − 重編前 = 差額」的一致性；
缺失為缺失、不補零、不融合個體報表、不跨會計準則。

版本限定：`pre_restatement_value` 代表公司 **2016-11-13
重編公告所回述的原報數值**。這可以做獨立的歷史
`retrospective pre-restatement replay`，但不自動證明該值
在 2016-05-13 事件前就曾被市場看到；
只有獨立證明最初申報日的「重編前申報版本」才可稱為
`STRICT_AS_OF` 提前預警。兩種證據層不互相替代。

## 把 PRE 真的帶入已選定機器學習模型

已驗證 Round3 **Validation Signed-log MAE 選出的模型為
Persistence**，形式是 `ŷ_(t+1)=x_t`，
逐個財務金額欄位獨立作用。完整的 Ridge、RandomForest、
GRU、LSTM、TCN、Transformer 模型輸入是完整
3 × 12 欄位；官方預重編公告未證實具有完整
36 格時，**不能用重編後金額補齊並強行跑這些模型**。

本次回測直接從官方公告 PRE side 做：

| 模型預測 | 用到的重編前輸入 | 對照（不進模型） |
|---|---|---|
| FY2014 數值 | FY2013 各財務科目 PRE | FY2014 PRE / FY2014 POST |
| FY2015 數值 | FY2014 各財務科目 PRE | FY2015 PRE / FY2015 POST |
| FY2016 數值 | FY2013/14/15 同科目 PRE 完整 3 年，僅以 FY2015 PRE 按凍結模型作出該科目預測 | 無官方同粒度 PRE/POST 對照者不補 |

程式會實際讀取 Round3 原本的 **fit-only RobustScaler**、
還原 signed-log 轉換後的數值，驗證與凍結 Persistence 公式一致，
不重新 `fit` / `partial_fit` 模型、不以 1785 重新選模。

FY2014、2015 的逐欄數字及差額會輸出真實 TWD：
- `forecast_twd`：由前一年 **PRE** 得出的模型預測；
- `observed_pre_twd`：當年度 **PRE** 金額，衡量數值預測誤差；
- `observed_post_twd`：當年度 POST，僅用來解釋官方重編差額；
- `normalized_pre_surprise`：數值相對變動，只是**預測偏離量**，
  不是舞弊機率、Precision、Recall 或 F1。

**提醒：Persistence 是數值預測基準線，並非舞弊二元分類器**。
其預測異常大，可能是營運波動或財報版本差異，還需要
財務審計驗證；不可將它解讀為模型已準確辨識造假。

## 執行與簡報數據

本輪程式：`round5_1785_pre_restatement_replay.py`

從現有獨立 worktree 的 `fintrust_backend` 執行：

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-1785-prerestatement-replay-20261020
powershell -ExecutionPolicy Bypass -File .\\research\\financial_ml\\verify_1785_pre_restatement.ps1
```

程式先測試，後在 **真正的官方封存包**上做模型數值運算；
零網路、零 production DB 寫入、不覆寫任何前幾輪成果。

結果輸出：

`Financial-Risk-Alert-System\\fintrust_backend\\data\\financial_ml\\final_1785_pre_restatement_replay\\`

- `1785_pre_restatement_replay_report.json`
- `1785_frozen_persistence_pre_only_predictions.csv`：**預測值/重編前/重編後真實數字**
- `1785_pre_vs_post_official_amounts.csv`：官方公告逐科目差額
- `1785_original_pre_feature_coverage.csv`：3 年 × 12 欄位是否有 PRE 資料

請回傳第一與第二檔；將它們導入 20 頁簡報的第 19 頁，
取代之前只放重編後 Beneish/Dechow 分數的舊版內容。
沒有真實封存包跑出的數值以前，不使用 CI 的合成資料填簡報。

CI: [Round5 real-PRE model tests](https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39357602090)。


## 2026-10-20 實際「重編前」資料回放與來源核對

**當年公告的全文轉載（原報數字、不是後來重編版）**：
https://news.cnyes.com/news/id/3615245 （鉅亨網轉載 2016-11-13
光洋科官方合併年報重編公告）。此新聞來源的公開文字可獨立閱讀，
但最後正式研究應再用使用者已封存的官方 ZIP/公告原始 SHA 比對。

重編前的 FY2013/14/15 合併 TIFRS **實際數字**（單位：仟元）：

| 欄位 | FY2013 PRE | FY2014 PRE | FY2015 PRE |
|---|---:|---:|---:|
| revenue | 34,241,550 | 53,305,891 | 61,372,337 |
| cost_of_goods_sold | 32,256,578 | 51,680,276 | 61,122,755 |
| gross_profit | 1,984,972 | 1,625,615 | 249,582 |
| net_income | 408,817 | 416,617 | -1,060,607 |
| current_assets | 9,803,059 | 11,251,855 | 9,674,248 |
| total_assets | 19,637,440 | 20,863,396 | 19,592,292 |
| current_liabilities | 5,300,506 | 4,866,286 | 8,357,583 |
| total_liabilities | 10,264,696 | 11,389,910 | 11,666,628 |

第九欄 **operating_income** 來自公告內同年度同口徑
`營業毛利淨額 − 營業費用合計`（8 個直接揭露科目＋1 個推導）：
FY2013 **702,974**；FY2014 **277,150**；FY2015 **-1,135,106**
（單位仟元）。它是透明公式的衍生科目，而不是聲稱原公告直接列示。
來源完整，不使用重編後輸入。

此時已選定的 Frozen Persistence 數值模型，以 FY2014 PRE 預測
FY2015：Gross Profit **1,625,615**（預測）對比 FY2015
**249,582**（PRE 實際）；Net Income **416,617**（預測）
對比 FY2015 **-1,060,607**（PRE 實際），單位仟元。
這是一個可重現、確實使用重編前數字的回溯年度數值實驗，
**並非 precision、recall、F1-score，也未證明事件前即收到警示**。

程式支援由凍結 ZIP 計算同樣的八個直接財務科目，以及
在 `gross_profit` + 原官方負數 `營業費用合計` 都存在時，
生成第九個 derived `operating_income`。
對比原始 DOC 及新聞轉載數值若有不一致，正式研究應以
通過獨立 source-hash 驗證的官方存檔為準，而不是這份轉載。

**最終 CI 11/11 PASS**：
https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39358667278 。
包含：模型輸入僅來自 PRE、重編後變動不影響預測、
已申報的正式財報差額一致性、衍生營業利益僅由 PRE 推導、
未披露特徵不補零、來源 SHA 固定、以前年度財務金額回測與
CSV/JSON 輸出。

演示 PPT 保持 20 頁，**第 19 頁現已使用真正 FY2013–2015 PRE
金額重新設計**；原先 2013–2015 POST Beneish 分數已不作為
該頁的「重編前預測成績」。PPT 的 web 公告抄錄版
不取代可驗證官方歷史 ZIP 的最後接受測試。
