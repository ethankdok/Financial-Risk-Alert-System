# FinTrust Step 5｜跨年度抽樣 2014–2025

**本輪實際完成**：保留原 545 筆、用正式公告轉載逐案核對 Y1/Y2 並新增 7 筆年度（7861 ×3、7895 ×2、6021 ×2），合計 552 筆。Y1 正例 70、Y2 正例 33。7 筆 Y3/Y4 沒有足夠年度司法證據，因此留空並標記待查；**不製造假的 0 或 1**。

距離 1000 筆還差 **448 個真正存在的 TEJ 公司年度觀測值**，只用你本機的授權 SQLite 讀取；這個環境沒有完整 TEJ SQLite，沒有聲稱已完成 1000 筆的 X/Y 人工查證。新增 448 筆先標 `ALL_FOUR_Y_PENDING`，待「查證→寫回→再查」工作流完成，不會直接參與訓練。

- FY2013：保留 341 筆作 IFRS 起點，不再新抽 2013。
- FY2014–FY2025：每年度目標約 54–55 筆，新增配額 22–46 筆／年。
- 產業：只讀 TEJ `industry` 證期會代碼原值，例如 01 原樣保留；17 金融業不進一般產業 X 模型；**沒有產業自訂群組**。
- 同年度、同產業：優先補已有 Y2 正例之「FY×FSC code」對照，但保留其他產業，防止過度集中；不會採樣到舊固定測試公司。
- TEJ20 缺值：新候選至少 18/20 項非空才挑選。所有缺值填補只准在訓練 fold；模型不得讀入「年份」或「missing pattern」替代訊號。
- Beneish/Dechow：`step5_canonical15_strict.py` 從原始合併 FY 科目嚴格計算；缺原始組成科目的欄位保留空白，**不把 AQI/DEPI/SGAI/LVGI/TATA 代理值換名冒充正規公式**。
- 財報版本：目前 TEJ 為回溯快照，尚未通過原始 MOPS first-filed PIT 驗收；研究分數應標為回溯測試。

## Windows 執行（位於 fintrust_backend）

將本套件解壓到 `step5_1000_20261109`，並提供原先的 `XY545_TEJ證期會代碼及20項X實際對接.csv`（上一輪你已產出）。

```powershell
python .\step5_1000_20261109\step5_expand_tej_1000.py `
  --existing545 ".\step5_1000_20261109\XY545_TEJ證期會代碼及20項X實際對接.csv" `
  --verified-seed ".\step5_1000_20261109\新增官方更正案件_Y1Y2人工查證.csv" `
  --db ".\data\financial_ml\tej_local_training\fintrust_tej_financial_ml_private.sqlite3" `
  --out ".\data\financial_ml\step5_1000_20261109"
```

成功會產出：`FinTrust_1000_跨年度XY標籤查證主表_PRIVATE.csv`、`新進樣本人工查證待辦.csv`、`年度跨期抽樣分布.csv`、`TEJ證期會原始代碼_新樣本分布.csv`、`原始固定測試公司名單_117.csv`、`抽樣驗收摘要.json`。

**人工標籤查核**：開啟 `新進樣本人工查證待辦.csv`，以 ticker + fiscal_year 查官方 MOPS 更正紀錄及司法／投保中心案件，填寫 `Y1,Y2,Y3_official,Y4_court_found`（未知可留空），記錄日期、文件頁次、來源 URL 和受影響年度，再用 `step5_apply_manual_reviews.py` 匯入；會留下逐列 diff，原 545 筆禁止覆寫。

```powershell
python .\step5_1000_20261109\step5_canonical15_strict.py `
  --db ".\data\financial_ml\tej_local_training\fintrust_tej_financial_ml_private.sqlite3" `
  --master ".\data\financial_ml\step5_1000_20261109\FinTrust_1000_跨年度XY標籤查證主表_PRIVATE.csv" `
  --out ".\data\financial_ml\step5_1000_20261109"
```

**禁止上傳 GitHub**：TEJ SQLite、TEJ 衍生原始 X、逐公司年度私人 CSV、授權原始檔、Secret、完整專有資料。GitHub 只推程式、合成測試及 README。

## 現階段驗收

- 9/9 合成測試通過，另外已用真實 545 X/Y 重算固定測試集 117 公司雜湊，與原實驗一致。
- Excel 實際含 **552 筆**，不是宣稱已得到 1000 個已人工核實樣本。
- 待跑本機 TEJ 及逐列記錄新增 448 筆的 Y，才可開始「1000 筆的模型驗證」。