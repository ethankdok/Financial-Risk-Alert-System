# MOPS → FinTrust → JCAATs：後端交接與接入契約

本文件基於 2026-11-21 提供的 `mops_pipeline_release.zip` 及其 `README_HANDOFF.md`、`pipeline/metrics.py`、`run.py`、`run_report.json`。這個 package 目前**不在本 GitHub 分支**；它屬於獨立可排程程式，必須先部署至有 Python 環境與 MOPS 連線權限的執行環境。本文是整合契約，不代表 JCAATs 已連線或訓練模型已上線。

## 1. 導覽與模組邊界

- **新聞查證**：外部新聞／投資說法 → 公司識別 → 既有 `/api/financial/companies/{ticker}/card`、`metrics`、`material-events` 提供已歸檔官方來源 → 查證輸出；若 `/api/financial/claims/verify` 尚未部署，不產生真偽結論
- **企業健檢**：既有 Cloud Run 金融指標／財報風險規則／重大訊息，以及上傳 MOPS 快照的 Beneish 八項指標、Dechow 七項指標、M-score、F-score；來自現有 `card.narrative_shift` 的 JSD 與文字品質判定也在此檢視
- **JCAATs**：尚未串接；未來可作為執行或排程器，或接受 FinTrust 輸出的模型訓練資料；上述兩者不是同一件事

## 2. 若 JCAATs 只需要觸發既有 Python pipeline

來源 zip 的命令列入口已就緒：

```bash
# 先在執行環境安裝 mops_pipeline/requirements.txt；以絕對路徑執行
python /absolute/path/mops_pipeline/run.py probe
python /absolute/path/mops_pipeline/run.py run
# 離線驗證，只處理已保存原始財報
python /absolute/path/mops_pipeline/run.py run --no-fetch
```

已有包裝：
- Linux/macOS：`mops_pipeline/schedule/run_scheduled.sh`
- Windows：`mops_pipeline/schedule/run_scheduled.bat`

輸出固定於 `mops_pipeline/output/latest/mops_metrics.json`、`.csv`、`.xlsx`、`run_report.json`。結束碼：`0` 成功、`1` 致命錯誤、`3` 已有另一次工作在跑、`2` 僅在指定 `--fail-on-missing` 且有缺漏時出現。Pipeline 支援冪等下載、鎖檔、日誌、原始 iXBRL 檔案名稱記錄。

不要從公開前端直接執行抓取或排程；應由受控的排程器、JCAATs 任務或 Cloud Run Job 啟動，再以**有權限的後端匯入程序**把經核對的結果放入既有持久化資料庫。勿把 ingestion token 或服務帳號資訊放入前端。

## 3. 模型輸出契約（未接通的未來接口）

在真正模型完成、核定版本和驗證規則之前，前端一律隱藏 JCAATs 分數。未來建議模型結果至少包含：

```json
{
  "schema_version": "jcaats-inference-v1",
  "ticker": "6505",
  "fiscal_year": 2025,
  "report_scope": "consolidated",
  "model_id": null,
  "model_version": null,
  "model_output": null,
  "feature_values": {},
  "source_filing_version": null,
  "source_filed_at": null,
  "prediction_as_of": null,
  "source_sha256": null,
  "status": "not_connected"
}
```

其中 `null` 均為**未填資料**，不是範例預測分數。

必須在後端確認：模型特徵與公開時間的先後關係、首次申報／更正版本區分、Y1–Y4 標籤定義與資料洩漏、產業及缺值處理、模型版本、預測時點、來源完整性。現有 MOPS 計算分數不等於 JCAATs 監督式分類器的輸出，也不可直接用最新重編財報冒充首次公開資料。

## 4. 上傳輸出實際涵蓋範圍

`run_report.json`：
- 油電燃氣業 12 家、2021–2025 共 60 個公司年度；M-score 60 筆可算；F-score 48 筆可算
- 電子通路業 38 家、同期間共 190 個公司年度；M-score 188 筆可算；F-score 152 筆可算
- 本次資料源總計 50 家；前端公司名錄可查 1,996 家，但沒有財報模型輸出的公司不能顯示虛構分數

來源 `pipeline/metrics.py` 明定需要全部八個 Beneish 成分才會給 M-score、七個 Dechow 成分完整才給 F-score，無法計算值為 `NaN`（JSON 中 `null`）。**F-score 在此指 Dechow et al. (2011) Model 1，不是 Piotroski F-score**。

## 5. 上線驗收要件

1. 在非正式環境啟動 mops_pipeline，確認 `run_report.json` 與 `output/latest` 的完整性及時間戳記。
2. 對照公司代號、年度 Q4、合併／個體範圍、首次申報版狀態及逐項輸入科目。
3. 以受控後端匯入，留存原始檔名、來源網址、申報時間與雜湊；重跑必須具冪等性。
4. JCAATs 若有正式模型推論能力，再加入獨立模型輸出、評估與失敗處理；不得將 M-score／F-score 重新命名為 JCAATs 分數。
5. 上線前驗證前端 `新聞查證`、`企業健檢`、會員驗證及 Cloud Run API；目前正式 Cloud Run 仍未部署某些 `/api/integrity`、`/api/financial/claims/verify` 路由。
