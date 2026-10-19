# 最終案例｜1785 光洋科：官方歷史財報模型分數 + Round3 凍結推論

## 已完成開發（2026-10-20）

這是 FinTrust Financial ML Phase/Round 完成後的獨立 **final case**，不把 1785 納入
FY2013–2025 台灣 120 家公司訓練樣本、季度 fit 欄位選擇、超參數設定或任何閾值校正。

實作：`final_1785_case_replay.py`；
11 個人工資料結構的 fail-closed 回歸測試；
`verify_1785_final_case.ps1` 一鍵接上使用者本機的原始 1785 證據 ZIP
及已完成的 Round3/Round4 報告。

## 光洋科已存在的「真實歷史模型數字」

既有來源：`docs/research/LITERATURE_COMPARATIVE_CASE_STUDY_1785.md`，
由完整的文獻原始計算引擎 **Beneish (1999) full8**、
**Dechow et al. (2011) Model1** 產生；程式從既有研究表格逐年度
解析並 SHA 記錄來源文件，不重新訓練，也不將重編前和重編後
拼成同一個時間序列。

| FY | 當次研究的報表版本 | Beneish M-Score | Dechow F-Score |
|---|---|---:|---:|
| 2011 | 原始年度報表（TW-GAAP PDF） | -1.730106 | 未能計算（缺 t-2） |
| 2012 | 原始年度報表（TW-GAAP PDF） | -2.286269 | 0.892005 |
| 2013 | 重編後 XBRL | -2.942811 | 0.718185 |
| 2014 | 重編後 XBRL | -2.300361 | 0.984084 |
| 2015 | 重編後 XBRL | -2.240182 | **不採納**（重疊期科目不一致） |

2011 的 M 值大於 Beneish 原始**美國文獻參考** -1.78；
這是「在該範例財報欄位下，文獻分數位於參考線某側」，
不是台灣驗證的舞弊預測機率，不能當成真正於 2011 年即發出預警。
2012 的 F=0.892005 依賴原始專案 documented verified-zero 規則，
該規則的方法審核仍由研究負責人確認。

> 光洋科於 2016-05-13 出現官方財報不實說明，2016-11-13 公布
> FY2011–2015 重編前後比較；這兩個不同時間的證據不能混入事件前模型輸入。

## 凍結 Round3 模型實際推論的准入設計

基礎模型的模型選擇在未見 1785 的 Validation 集完成：
`persistence` 是 Signed-log MAE 最小的年度 12 維金額預測 baseline。
僅重用 frozen Round3 `annual_checkpoints/fit_only_preprocessor.joblib`
與其預先選定模型，不對 1785 `fit` 或重新挑選模型。

欲以 FY2013、FY2014、FY2015 三年輸入推估 FY2016：
- 三年各 12 個完整年度財務金額（共 36 格），欄位完全吻合 `METRICS`；
- 公司為 1785、**合併**口徑、**TIFRS**、幣值為完整 TWD；
- 原始財報發表時間有原始證據，不能晚於事件前截止（保守固定 2016-05-13
  00:00 Asia/Taipei）；
- 不允許使用 2016 年 11 月公布的重編前後比較值回填
  2016 年 5 月以前的輸入；
- 預測只輸出 FY2016 十二項**財務金額**，絕不輸出舞弊機率、
  Accuracy / F1 或使用 1785 調參。

本機已有 `fintrust_1785_asof_2016-11-14.zip` 正式
SHA `304934a4a2e05dc16439155b267554a99a731ff6c07fa95e1cd05f25504f2bcf`。
嚴格 ZIP 既有 27 筆 FY2013–2015 事後重編數值，並非全 36 項
`original as-of`，因此真實 2016 年 5 月之前完整數值推論不能靠此 ZIP
補成「成功預測」。程式使用獨立 `package_verify.verify_package`
先進行 ZIP 全量 SHA/語義驗證，之後對每個特徵輸出
`MISSING` 或 `PRESENT_BUT_NOT_PRE_EVENT_ORIGINAL`
的明確缺口。

**這是完成的來源/推論管線與真實文獻模型結果**，不是
聲稱已實際證明 FY2015 會被新模型辨識為舞弊。
光洋科最終盲測在原始申報／時間證據通過核准前仍不能視作
early warning accuracy 的正式成果。

## 一鍵使用者本機真實封存驗證

在獨立 `Financial-Risk-Alert-System-ML\\fintrust_backend`，保持
`ml-env` 啟用且沒有未提交的改動：

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-1785-final-case-inference-20261020
powershell -ExecutionPolicy Bypass -File .\\research\\financial_ml\\verify_1785_final_case.ps1
```

若本機分支已存在，用 `git switch feature/financial-ml-1785-final-case-inference-20261020`。
現有 Round3、Round4、historical ZIP 皆僅讀取，無網路、
無 prod DB 寫入、不改前端、不刪除舊結果；輸出資料夾不可覆寫。

驗證通過輸出：
`Financial-Risk-Alert-System\\fintrust_backend\\data\\financial_ml\\final_1785_case_replay/`

- `1785_case_final_report.json`：獨立正式結果、模型身份、封存 SHA、
  2016 事件前輸入判定；
- `1785_historical_model_scores.csv`：2011–2015 真實研究分數，
  可直接匯入 Canva/PowerPoint 表格；
- `1785_pre_event_input_gaps.csv`：36 格候選值的分年／分項明確缺口；
- `1785_presentation_text_zh.txt`：提供簡報所用的逐頁文字。

簡報：維持 20 頁，**第 19 頁**直接放上述 Beneish／Dechow 真實分數、
財報版本、2016 事件時間線及 frozen-Round3 准入狀態；無假造機率。


## 完整終端推論的追加路徑（與現有歷史結果分離）

最終凍結推論模組另支援 `--pre-event-zip`，僅供獲得獨立來源驗證後使用：

- 原始歷史 ZIP 必須使用專案內 `verify_package` 的 **strict point-in-time**
  語義驗證，並明確為 1785、`parameters.as_of=2016-05-12`；
- 只收 FY2013–2015 的合併報表、TIFRS、TWD、
  `original`、`point_in_time_eligible=true`，
  且每筆 `effective_available_at` 早於保守的 2016-05-13 00:00；
- 相同年度／財務科目重複、非有限數值、沒有可信的原始資訊、
  時間晚於截止均拒絕；
- 36 格齊備，才讀取已選定的 frozen Round3 scaler 與模型，
  依訓練時**相同**的 signed-log／RobustScaler 管線，
  輸出 **FY2016 12 項財務金額**；不因單一光洋科更改模型。
- 若主專案有 `fintrust_1785_asof_2016-05-12.zip`，
  `verify_1785_final_case.ps1` 會自動偵測並額外進行以上驗證；
  無此檔則輸出既有真實文獻分數及逐欄缺口。
  **不會自動建造、偽造或下載不存在的事件前原始申報。**

CI **16/16 PASS**：https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39320743343 。
涵蓋文件表格解析、原始／重編版本、防回填時點、重複同口徑、
輸入不完整時拒絕預測、完整 frozen persistence 推論、
報告輸出與不可覆寫等情境。

正式簡報已更新為 **20 頁**。第 19 頁呈現本次真實回溯模型分數，
沒有把不同版本拼為單一特徵序列、沒有虛構 Precision / F1。
