# FinTrust 真實 0/1 財報不實監督式學習｜外部 AAER 實驗

**日期：2026-10-20。這是已實際完成的真實公司財務資料模型，不是合成資料測試。**
**研究來源：美國上市公司、SEC AAER + Compustat，並非臺灣 MOPS 原始申報。**

## 可信來源與標註定義

採用 Bao, Ke, Li, Yu, Zhang (2020), *Journal of Accounting Research* 58(1):199–235
正式發表研究附帶的公開資料：
https://github.com/JarFraud/FraudDetection ，
檔案 `data_FraudDetection_JAR2020.csv`。
研究作者與團隊根據 SEC Accounting and Auditing Enforcement Releases
和公司年度會計資料編纂 `misstate` 正負標籤：

- **1**：研究資料標示為 SEC AAER 財務不實相關的公司年度。
- **0**：研究資料中的對照公司年度，**並不代表已經證明絕對沒有隱藏舞弊**。
- **人工標註來源**：原論文專業研究團隊的既有人工蒐集／判定。
  本次取得、清洗並訓練了**全部已公開的0/1研究資料**，
  但**不宣稱本次由 ChatGPT 或組員逐一重新閱讀141,463份 SEC 案件**
  並獨立驗證它們全部正確。

正式訓練採用來源 SHA-256：
`ed4cefd9db2a23d0a13911d9f482fc755d3dcf6c9be0bc051af95ddcae5b286f`。

## 本次實際資料量

|研究項目|觀測|
|---|---:|
|財報年度|FY1991–FY2014|
|公司|18,147|
|公司年度總量|141,463|
|AAER正例 = 1|949|
|研究對照 = 0|140,514|
|原始金額特徵|28|
|財務比率特徵|14|
|測試集公司|2,723|
|測試集公司年度|20,905|
|測試集正例|134|
|測試集負例|20,771|

各子集**公司ID gvkey互不重複**，以是否曾有AAER公司做
group-level stratification；訓練98,593筆、驗證21,965筆、
獨立測試20,905筆。不能宣稱有 time-blocked / as-of 嚴格實驗，
因為這次刻意選擇跨年份的公司隔離測試。

**特徵層防資訊洩漏：** `misstate`、`p_aaer`、`gvkey`、
`fyear`均**不是輸入特徵**；用訓練資料 fit 缺值填補與 RobustScaler。
但本次未證實 Compustat 原始提取內容是事件前 as-filed 財報，
因此**不可宣稱事前舞弊預警的完整證明**。

## 模型與真實 holdout 測試

基線 `DummyClassifier`、`LogisticRegression(class_weight=balanced)`、
`RandomForest(class_weight=balanced_subsample)`，
驗證集依 PR-AUC 選模型，依 F1 選分類門檻，
Test 完全保留到最後才評估。

所選 `logistic_balanced`（驗證集門檻 = 0.77）：

| Holdout 指標 | 實際值 |
|---|---:|
| ROC-AUC | 0.719586 |
| PR-AUC (Average Precision) | 0.015724 |
| Precision | 0.022305 |
| Recall | 0.179104 |
| F1 | 0.039669 |
| Accuracy | 0.944415 |
| True Positive (TP) | 24 |
| False Positive (FP) | 1,052 |
| False Negative (FN) | 110 |
| True Negative (TN) | 19,719 |

**這不是可直接上線的高準確率模型。**
真實正例比例約0.64%，若全部猜0，Accuracy達99.36%但Recall=0。
實際模型測試顯示能學到部分辨識訊號，但 Precision只有2.23%，
誤報非常多，必須改善特徵與正例涵蓋率。

## 真實交付

開發程式：`published_aaer_real_supervised.py`

真實研究報告：
`results/real_aaer_supervised_holdout_report.json`

完整標籤、20,905筆holdout獨立推論、已凍結模型：
GitHub Actions
https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39392976287
產出的 `fintrust-real-aaer-0-1-supervised-holdout` artifact。

獨立研究API：
`GET /api/v1/research/external-aaer-benchmark`。
它只讀經驗證的研究報告，**不修改臺灣 production 財報風險分數、
不會自動對 1785 光洋科或其他臺灣公司下舞弊判定**。

API驗證測試：
https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39393712821
，3/3 PASS。

### 真正尚待完成之臺灣驗證

- 臺灣 2013–2025 的 MOPS 「原始首次申報」量化欄位，包含版本與官方公告時間核對；
- 臺灣獨立官方更正/重編/裁罰事件及非AAER定義的負例追蹤，
  取得可審核的臺灣年度0/1標籤；
- 將美國42特徵模型與臺灣特徵對映或重訓、採嚴格as-of保留案例評估；
- 保留 1785 為**最終盲測**，絕對不能將其真實重編後數據混入模型訓練。

這些工作**沒有因外部美國模型完成而自動被視為完成**。
