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
