# FinTrust 資管專題｜Phase 5 研究需求與架構鎖定（2026-10-18）

**狀態：使用者確認，後續專題 ML 研究以本文件為需求依據。** 與先前以 Pipeline 完整度優先的規劃不同，本階段要先產出**真正訓練好的大樣本財報異常偵測模型**；暫不做持續學習、定期排程、前端、部署或光洋科分數。

## 研究目標與資料範圍

- 先取得**足夠大的台灣上市、上櫃非金融業公司 × 年度**財報（優先 TIFRS FY2013–2025），再針對半導體產業實施同業模型比較。96 家半導體 × 3 年只屬小樣本測試，不是正式訓練的理想樣本。
- **現有 MOPS 官方 XBRL 封存先重用**；FinMind 三大報表為大量資料的候選來源，另行驗證季度/年度口徑、科目/單位與原始申報版本，不可直接將第四季值視為年度累計值。FinMind TaiwanStockInfo 產業名單僅為現時候選；歷史上市別、歷史下市公司、產業變動及存活者偏誤另行處理。
- 美國 SEC 官方資料僅作第二階段跨準則預訓練／遷移學習候選，不與 TIFRS 未校驗資料混用。

## 15 個文獻特徵是必要條件

**Beneish (1999) 8 個：** DSRI、GMI、AQI、SGI、DEPI、SGAI、LVGI、TATA。

**Dechow et al. (2011) Model 1 7 個：** rsst_acc、ch_rec、ch_inv、soft_assets、ch_cs、ch_roa、issue。

- **務必重用**既有 `app/services/financial_research/beneish_1999.py`、`dechow_2011.py`、`literature_method_registry.py`、`literature_inputs.py`、`literature_extraction.py`，不得把先前 `research/financial_ml/pilot.py` 的 15 個**一般財務比率**冒稱為文獻 8+7 變數。
- 依原文獻公式、驗證係數與台灣 XBRL 科目映射建立模型輸入；標明映射待方法負責人審核。Dechow 的 ch_cs 與 ch_roa 使用 t−2，缺資料不補零；issue 缺乏發行證據時為 UNKNOWN。
- 輸出每家公司年度的 15 變數、變數覆蓋率、無法計算原因、來源版本及品質紀錄。**Beneish M-Score、Dechow F-Score 固定係數輸出是文獻對照基準，不是台灣舞弊標籤或台灣校準機率。**

## 實驗與驗收

1. 資料清理與年度口徑、報表版本、年度前期欄位檢查，排除缺乏可靠來源者並保留缺值原因。
2. 用**時間切分**及**公司完全不重疊切分**，只在訓練集擬合 imputer/scaler/閾值；測試集不能參與特徵或模型選擇。
3. **單輪完整建模或多輪重複擬合／超參數比較（建議至少 10 次可重現重複實驗，並非精準上限）**，優先 Isolation Forest、LOF、Autoencoder、文獻分數對照；保存模型檔、資料版本、參數與結果。
4. 大量未標註公司**不能宣稱已確認正常**。可做無監督學習與分數穩定性分析；沒有獨立正常／異常標籤不宣稱 F1、Accuracy 或舞弊召回率。
5. **光洋科 1785 完全排除**任何訓練、閾值和特徵選擇，待模型／設定凍結後單獨測試。

## 開發順序（非生產 Pipeline）

- Phase 5A：官方 XBRL 封存 → 原有文獻程式 → 8+7 特徵/覆蓋率報告。
- Phase 5B：全台非金融公司母體與多年度財報批次取得；FinMind 原始資料來源封存、科目與口徑校驗。
- Phase 5C：15 變數大型有效訓練表、時間與公司切分、多輪模型訓練、收斂檢查、文獻特徵敏感度與模型成果比較。
- Phase 5D：模型凍結後再套入光洋科，產品整合與持續學習待後續規劃。

**安全界線：** 不改正式資料庫、既有前端，不洩漏密鑰，不 reset/clean/強切本機原分支；不把本機 SQLite 資料少推論成雲端資料不存在。

### 相關來源
- `docs/research/BENEISH_1999_DECHOW_2011_METHOD_LOCK.md`
- FinMind: https://finmind.github.io/tutor/TaiwanMarket/Fundamental/
- FinMind 台灣公司名單: https://finmind.github.io/tutor/TaiwanMarket/Technical/

## 2026-10-18 後續修訂：迭代實驗、模型候選與特徵重要性（使用者確認）
- 「至少十輪」表達希望充分訓練及多輪驗證，**不是**硬性 10 輪上限、10 種模型、也不是每輪新抓財報。區分神經網路 epoch、Isolation Forest 樹數、boosting rounds、不同亂數種子／重新抽樣與真正持續學習；輪數增加不保證績效改善。
- 優先對大量 15 文獻變數財報資料（Beneish 8 + Dechow Model-1 7）進行特徵清洗、時間與公司不重疊切分，再探索不同模型。第一波無監督基準：Isolation Forest、LOF、重建型 Autoencoder，評估分數與排序穩定性、收斂與分布漂移。
- Random Forest、XGBoost、CatBoost 優先列為**取得獨立異常／重編／舞弊結果標籤後**的監督式表格模型；也可研究無監督重建代理，但必須標注學習目標與標籤問題，不能把偽標籤訓練聲稱為真實準確率。
- Transformer：待多公司更長時間序列或足量表格預訓練後再評估；GNN：待供應鏈／股權／交易真實關係圖邊資料與洩漏控制後再評估。不要為模型先進而在 64 筆資料上強行使用。
- 研究模型融合：例如以**驗證集擬合的異常分數分位轉換**整合不同無監督模型；對真實 outcome 的效果仍待標籤驗證。
- 特徵重要性分為：（A）目前無標籤的模型分數擾動敏感度，**不可**解讀為影響舞弊的因果／預測重要性；（B）有獨立標籤後之 permutation importance、SHAP 等預測解釋，避免相關特徵誤讀。
- 保留現有 Phase1–5 的官方 MOPS/XBRL、SHA256 封存、15 變數文獻引擎、FinMind 蒐集／對映、readiness、安全 Worktree 和 reserved 1785 case；只是本階段研究優先順序改為**擴大資料、校正缺值、完成多輪模型比較**，Pipeline/網站/排程在後期處理。
- 最新 Phase5A: 64 公司年度，22 家公司，完全 15 變數僅 11 筆；Beneish 8 變數完整 17 筆、Dechow 7 變數完整 17 筆；TATA/RSST/Issue/LVGI 缺值是擴充首要標的。切勿填 UNKNOWN Issue 為 0。
