# FinTrust 真實 AAER 0/1 模型改良驗收｜2026-10-20

## 任務
在不偽造 0/1、保持真實偏斜正負比例、排除測試集參與選模的前提下，
測試模型可否向 Precision / Recall / F1 / ROC-AUC 90% 接近。
**結果：未全部達到90%，且不能用 Accuracy 高取代真實舞弊偵測品質。**

來源與固定 SHA: Bao et al. (2020) JAR `data_FraudDetection_JAR2020.csv`
`ed4cefd9db2a23d0a13911d9f482fc755d3dcf6c9be0bc051af95ddcae5b286f`;
141,463 研究公司年度、949 研究正例、140,514 研究 0 對照、
18,147 家美國公司，FY1991-2014。
<https://github.com/JarFraud/FraudDetection>

## 已實際訓練的方法
- Logistic Regression / LightGBM / XGBoost / CatBoost。
- 固定當期 42 原特徵 + 10 前期財務金額 + 10 前後差異 +
  9 同期財務比率（共71項）、以及僅9項共同臺美原始金額+
  9項衍生比率（18項）。
- 欠採樣只在訓練集、不調整測試集 0/1 比例。
- RUSBoost (120/250)、BalancedRandomForest、EasyEnsemble、
  LightGBM 0/3/12/25 positive-cost 權重。
- 固定 3 組彼此不同的公司隔離測試；
  另以 fit<=FY2003 / val FY2004-08 / test FY2009-12
  進行嚴格公司 + 年份外測試。
- 正式分類門檻由 Validation F1 決定，
  模型由 Validation PR-AUC（ROC-AUC 僅平手時決定）選出；
  **不使用 Test 調整模型或門檻**。

## 四組真實獨立測試（不能當作相同測試樣本的受控改善）

|試驗|TEST 筆數|正例|模型|ROC-AUC|PR-AUC|Precision|Recall|F1|
|---|---:|---:|---|---:|---:|---:|---:|---:|
|原基準|20,905|134|Logistic|0.719586|0.015724|0.022305|0.179104|0.039669|
|新公司隔離 20261023|20,804|140|Logistic+跨期特徵|0.721346|0.017042|0.037453|0.071429|0.049140|
|公司+年份外測試|3,289|12|LightGBM|0.492422|0.005105|0|0|0|
|RUSBoost等9候選，隔離 20261028|21,246|145|LightGBM不額外提高正例權重|0.773425|0.023168|0.044534|0.075862|0.056122|

最佳新測試 TP=11, FP=236, FN=134, TN=20,865。
如在同一測試 n positive=145 / negative=21,101 上欲
**Precision>=90% 且 Recall>=90%**，至少需 TP>=131、
誤報最多約 14 筆；目前差距很大。
若只預測全部正常，Accuracy即可達 99.32%，不具可用性。

嚴格時間外實驗僅有 12 個 AAER 正例，估計十分不穩定。
晚年度 AAER 標籤有揭露/執法追蹤不足問題，
不能篩掉困難正例而宣稱 90% 指標。

## 文獻事實與重要研究品質限制
Bao et al. (2020) 在 2022 年發表官方 Erratum，
修正 serial fraud 實驗處理錯誤；修正後 RUSBoost
在2003-2008年間的平均ROC-AUC約0.7228。
DOI: https://doi.org/10.1111/1475-679X.12454

0是研究對照，**不是逐公司證明完全沒有財報不實**。
當前 Compustat 特徵尚未個別核定是否真為事件前首次申報版，
因此不能宣稱已達到合規、實務可用的「事前舞弊預測」。
不得把美國模型 ROC-AUC、Precision 套用到台灣公司或光洋科。

## 完整真實執行證據與工作檔
- 第一進階訓練 CI (含兩組 TEST 及完整 71特徵模型):
  https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39398335239
  artifact: fintrust-enhanced-aaer-real-supervised-results
- 第二成本敏感+RUSBoost 訓練 CI:
  https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39399129376
  artifact: fintrust-real-aaer-rusboost-ensemble-research
- 防資料洩漏的合成單元測試 CI:
  https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39398539715

完整預測逐列 CSV、固定研究模型 .joblib、Validation 全候選資料
與 untouched TEST 分數皆在兩個工作流程的 Artifacts 中。

## 接入台灣財報的必要條件
台灣FinTrust目前原來FY2013-15 360公司年度中
114筆具備12項初步FinMind候選值、246筆不完整；
**首次申報版本與正式0/1人工核准仍為零**。
欲真正接入台灣，須建立台灣來源版本與公布日期查核，
使用台灣正式重編/違規事件對應年份重標註，
並重新訓練同口徑模型作**獨立台灣測試**。
美國42特徵與台灣12金額並不相同，
即便先驗證共同9金額特徵仍須幣別單位與會計準則處理。
不要直接載入美國模型然後宣稱預測出光洋科真實舞弊。
