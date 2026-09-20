# 資料庫整合與 Pipeline 精細設計 v1

日期：2026-09-20。狀態：**現況已查核；統一契約與流程設計完成；遷移、runtime 重構、雲端排程尚未實施**。

本次使用唯讀 SQLite 及現有程式碼，不連線正式 Firestore、不啟用外部抓取、不修改原資料。
本文件中的新表、欄位、端點、排程均為目標規格，不代表現有功能。

## 1. 查核範圍與結果

主樣本：`fintrust_backend/data/backfill-small-v2.sqlite3`。舊樣本 `backfill-small.sqlite3` 另外保留，不合併、不覆蓋。
正式環境的 project、資料量、索引、IAM、費用額度均未驗證；目前不能宣稱正式資料庫已整合完成。

| 實際表 | 粒度／現有主鍵 | 主樣本筆數 |
|---|---|---:|
| companies | ticker | 96 |
| financial_filings | ticker + period | 10 |
| normalized_financial_facts | SHA1(ticker, analysis_type, period, metric_code) | 182 |
| analysis_runs | run_id | 4 |
| calculated_metrics | run_id + analysis_type + period + metric_code | 448 |
| rule_results | run_id + analysis_type + rule_id | 80 |
| latest_analysis_snapshots | ticker | 2 |
| ingestion_runs | run_id | 4 |
| official_events | event_type + event_id | 0 |

2330、2454 各有 2021FY–2025FY、每年 16 個歷史 facts；另各 11 筆 latest facts 被記在 2026Q2。
每家公司兩次分析，因此 448 筆 metrics 是版本歷史，不應直接去重刪除。
96 家公司中 reviewed=4、medium=92；分類完整不等於分類已人工確認。
舊樣本有 96 家公司與 1 筆 ingestion run，沒有財報事實或分析結果，不能當成第二份完整資料集合併。

### 已確認問題（高信心）

| 優先度 | 證據 | 風險與處理 |
|---|---|---|
| P0 | 6/6 月營收 facts 的 period 都是 2026Q2 | 月資料錯掛季度；重新從 snapshot／來源還原真正月份，不可用抓取日期猜月份 |
| P0 | 12/22 latest facts 的 source_url 指到不相符的資料集：6 月營收 + 6 資產負債項目 | 非空 URL 不代表正確證據；逐 statement_type 綁定來源 |
| P0 | `company_registry.py` 是 4 家靜態表；pipeline 使用 get_company/list_companies | 資料庫 96 家不等於可抓取 96 家；改接主檔，另設追蹤名單 |
| P0 | SQLite 直接匯入寫 financial_facts；pipeline 寫 normalized_financial_facts | 兩套 facts／預設 DB 路徑不同；建立共用 canonical repository 與相容 adapter |
| P0 | 直接匯入 key 含 scope；分析 facts key 不含 scope；filing key 也無版本 | 合併／個別或更正版可能互相覆蓋；改版前不能盲目全量合併 |
| P1 | latest_fact_rows 對所有欄位共用第一個 available source、共同 period | 程式造成上述語意錯誤；metric_rows 也需分離月指標期間 |
| P1 | financial_fact_from_row 把 retrieved_at 當 filed_at，historical 一律推定 consolidated | 公告時間與擷取時間混淆；scope 應由原始報表證據取得 |
| P1 | records_found/records_written 都設為 persistence.total | 混合 filing/fact/metric/rule 計數，不能當新增資料量 |
| P1 | refresh_company 抓 latest + 多年 history，再做 AI，最後才寫 DB | 一次錯誤牽連多階段、重跑浪費；拆抓取、解析、分析、發布 |
| P1 | Firestore save_pipeline_result 為單一 batch；最新快照無版本競爭檢查 | 擴充時需分批與發布閘門；舊任務不可覆蓋新結果 |
| P1 | PipelineEvidenceRepository 由最新 snapshot 推定舊 metric 來源 | 歷史證據可能對錯版本；metric 必須指向自己的 input_fact_ids |

原本 QA 的 PASS 只驗證既定檢查，未檢查 period 與來源語意。新的上線閘門為 **BLOCKED**。
目前沒有足夠跨日樣本可判斷分布漂移；事件表為空，不能驗證事件覆蓋率；本次也沒有與官網重新逐值對帳。

## 2. 統一資料格式（canonical contract v2）

### 基本規則

- ticker 為字串；這版只涵蓋 TWSE。未來跨市場改用 company_id=market:ticker，勿先把不同市場公司合併。
- 主檔唯一標準欄位為 `name`、`subindustry_code`、`subindustry_label`；既有 company_name/semiconductor_subindustry 透過 adapter 對應。
- 子產業保存 classification_version、source、confidence、reviewed_at、reviewed_by；官方產業碼與專題細分類分開。
- UTC aware timestamps 入庫；SQLite 用 ISO 8601、Firestore 用 Timestamp；UI／排程用 Asia/Taipei。
- 分開 source_published_at（可未知）、retrieved_at、parsed_at、committed_at。未知公告時間為 null，不能填抓取時間。
- period 用 YYYY-MM、YYYYQn、YYYYFY 顯示；另存 period_start、period_end、period_kind。
- period_kind=instant / month / quarter / ytd / year；Q2 標籤不能證明數值是單季而不是上半年累計。
- 民國年在 adapter 轉換，保留 raw_period。資產負債使用期末 instant；損益／現流記錄完整期間。
- 原始值保留 raw_value、raw_unit、scale、currency；金額正規化為 TWD 基本單位，EPS 為 TWD/share，百分比為 percentage_points，倍數為 ratio。
- 可採 decimal 字串作跨 SQLite/Firestore 精確交換；Python 計算用 Decimal，前端數值呈現另轉。不可直接把既有 float 當成原始精確值。
- 缺值用 null + missing_reason，不填 0；拒絕 NaN/Infinity；負值依科目允許，不能把負現金流或虧損通通判壞。
- official/demo 使用獨立資料庫或 namespace；namespace 必須參與所有 identity，包括最新快照。

### 表與關聯

| 目標實體 | 唯一識別與必要欄位 | 關係／整合方式 |
|---|---|---|
| companies | ticker、官方名稱、market、listing_status、classification metadata | 公司唯一主檔；不可由抓取結果覆蓋人工分類 |
| company_tracking | ticker、ingestion_enabled、rule_profile、priority、backfill_state | 96 家主檔與啟用名單分開；初期啟用 2330/2454 |
| source_snapshots | snapshot_id、source_id、dataset、payload_hash、storage_uri、retrieved_at、schema_fingerprint | 原始全文存檔；DB 存 metadata；相同 payload 可共用 blob |
| fetch_attempts | attempt_id、run_id、snapshot_id、HTTP 狀態、bytes、duration、error、retrieved_at | 每次 HTTP 都留紀錄；304 或內容未變仍計請求 |
| financial_filings_v2 | filing_version_id、ticker、period、scope、source_native_id、revision/hash | 更正版追加，不覆蓋舊版；未知修訂序號使用內容 hash |
| financial_facts_v2 | fact_id、fact_key、filing_version_id/snapshot_id、metric_code、period bounds/kind、scope、dimension_hash、unit、value | immutable observation；取代兩套事實寫入途徑 |
| selected_facts | fact_key → fact_id、selection_reason、selected_at | 同期間不同來源保留並存；只發布可比較且通過 QA 的選定值 |
| official_events_v2 | source_id + native_event_id + revision、ticker、published_at、title、content_hash | 無原生 ID 才用公司＋事件類型＋日期＋標題等穩定欄位 hash；正文 hash 用來追蹤修訂 |
| event_documents | document_id、event_id、URL、hash、language、document_kind、parse_status | 法說簡報／逐字稿／事件附件；附件抓取有額外預算 |
| ingestion_runs_v2 | run_id、parent_run_id、job_key、pipeline、stage、source_id、ticker 可空、status、counts | 批次來源父 run 與公司子 run 分開；舊 run 透過 adapter 保留 |
| quality_findings | finding_id、run_id、snapshot_id/fact_id、check_code、severity、evidence、resolution | 不合格資料可追溯，不直接丟棄 |
| analysis_runs_v2 | analysis_id、input_manifest_hash、parser/metric/rule/classification versions、status | 分析輸入可重現，與 ingestion run 不共用身份 |
| calculated_metrics_v2 | analysis_id + metric_code + period + scope；value nullable、missing_reason、input_fact_ids | 原始事實與比率保持分表；不能从最新快照猜来源 |
| rule_results_v2 | analysis_id + rule_id；rule_version、evidence_metric_ids、status | insufficient_data 與 low_risk 分開 |
| published_snapshots | namespace + ticker → analysis_id、generation、data_as_of | 前端只讀已發布版本；保留舊分析供稽核 |
| pipeline_jobs / source_state | job_key、lease、fencing_token、cursor、not_before、budget counters | durable queue、限流與斷點；跨 worker 共用 |
| pipeline_outbox | event_id、committed_run_id、target_stage、delivery_status | 寫資料與建立後續工作具一致性；崩潰後可補送 |

fact_key = SHA256(具版本標籤的 canonical JSON array：namespace,ticker,metric_code,period_start,period_end,period_kind,scope,dimension_hash,currency,unit)。
fact_id = SHA256(fact_key + source_id + source_revision/content_hash)。identity 不使用 analysis_type=latest/historical；那是使用情境，不是事實粒度。
scope=unknown 不與 consolidated 合併；dimensions 未知的 segment facts 不可混入全公司合計。
資料來源優先序只在相同期間、單位、scope、dimension 下套用：已驗證的 MOPS filing 優先於 TWSE 摘要；不同值保留衝突證據，不能單看 retrieved_at 選最新。

### 月營收整合決策

`monthly_revenue` 以實際 YYYY-MM 儲存。`previous_month_revenue` 與 `prior_year_month_revenue` 是來源欄位角色，應映射成前月／去年同月的 monthly_revenue observation，保留 source_field。
年增率、月增率以相應兩期選定事實計算。來源提供的變動率可留作對帳，不直接當重算結果。
若無法從原始 snapshot 還原年月，先 quarantine，不以 2026Q2 或執行月份代替。
月營收與季度營收分別維護資料時點；前端不可用同一個「財報更新時間」表示兩者。

### 不合併的資料

Flask 的 admins、keywords、risk_features、audit_logs、analysis_records 保持管理／文字風險領域，不搬進財務 facts。
Flask 與 FastAPI 以明確 API／repository 邊界讀取同一發布結果；analysis_records 不等同 analysis_runs。
這輪不改為 Postgres，也不假定舊記憶中的部署就是目前實際設定。

## 3. Pipeline 的準確階段

| 階段 | 輸入 → 輸出 | 成功條件／失敗處理 |
|---|---|---|
| 0 排程投遞 | schedule_id + scheduled_for → job_key | 驗證 OIDC／管理授權；同 job_key 原子 create-if-absent；落 durable queue 才回 202 |
| 1 領取 | pending job → lease + fencing_token | 過期才可重新領取；heartbeat；過期 worker 不可提交 |
| 2 預算檢查 | source_state + job → permit | 來源總配額、速率、併發、冷卻均通過；手動／重試／backfill 同樣受限 |
| 3 抓取 | endpoint + cursor/conditional headers → fetch_attempt + raw snapshot | 檢查 HTTP、Content-Type、JSON/HTML 結構；200 的封鎖頁不是成功資料 |
| 4 去重 | payload hash + parser version → parse job 或 unchanged | 先存 raw；同內容同 parser 不重解析；parser 升版可重播 raw，不需 HTTP |
| 5 正規化 | raw + source adapter → staged filings/facts/events | 逐來源映射期間、幣別、單位、scope；全市場抓一次後按 ticker 分流 |
| 6 品質閘門 | staged + existing → pass/warn/quarantine | 結構變更封鎖整個來源；單家公司壞列隔離該公司，不清掉其他好資料 |
| 7 寫入 | validated rows → immutable observations + selected pointers + outbox | 重跑不增加相同 observation；failed attempt 不前移成功 cursor |
| 8 分析 | committed selected facts + versions → analysis_id | input manifest 不變且版本不變則跳過；依賴不足記 insufficient，不硬算 |
| 9 發布 | completed analysis + QA → published pointer | generation/CAS 比較避免舊 job 覆蓋新資料；失敗保留舊快照并顯示 stale |
| 10 可選 AI | committed evidence + prompt/model version → ai_result | 與財務發布分離；AI timeout/額度不足不回滾 facts；按 hash 去重 |
| 11 收尾 | 子階段結果 → run summary + checkpoint | 清楚記錄成功／部分成功／失敗／未變／預算延後；outbox 可獨立補送 |

分析必須從已入庫且已提交的 facts 讀取，不能繼續由抓取服務先算完再順便入庫。
API handler 不使用無耐久性的背景 task 執行整晚工作；本機可用 CLI worker，雲端採 durable queue + 有執行保障的 worker/job。

### Run 狀態與計數

狀態：queued → running → completed / unchanged / partial / failed / quarantined；running 可轉 retry_wait → running；超預算為 deferred_budget；取消為 cancelled。
attempt_no 屬於同一邏輯 job，重試不是新增相同批次。父 run 所有子工作結束才結算；有失敗為 partial，不能偽裝 completed。
source row 計數：rows_received = rows_accepted + rows_rejected + rows_ignored。
各實體另計：inserted、updated（只限 pointer/metadata）、unchanged、quarantined；HTTP requests、DB reads/writes、LLM requests/tokens 分開。
不要把多張表相加當「新增來源筆數」。兼容舊 PersistenceCounts 時標示 write_attempts，不改寫歷史統計意義。

### 交易與競爭

- SQLite：canonical rows + outbox + cursor 在同一 transaction；單寫入 worker，busy timeout，失敗 rollback。
- Firestore：採小批 immutable staged writes，驗證批次 manifest 完整後再以 transaction 發布 committed manifest／pointer。Reader 僅讀 committed，不能只分批寫就宣稱整體 atomic。
- 建議初始單批不超過 200 個小文件，另按序列化 bytes／索引負擔分批；200 是本專案保守設定，非官方限額聲明。
- 改寫 published pointer 時需 fencing_token、目前 generation、輸入版本比較；回填舊年不能使前端退回舊資料。
- Scheduler 可能重複投遞，必須有持久 idempotency key，而非僅靠程序記憶體鎖。[官方說明](https://docs.cloud.google.com/scheduler/docs/overview)
- Firestore transaction／batch 使用限制與行為依實際部署驗證；跨批次提交規則由本專案自行保障。[官方說明](https://firebase.google.com/docs/firestore/manage-data/transactions)

## 4. 錯峰排程與請求預算

以下全部為 **Asia/Taipei、本專案建議初值、尚未啟用**；不是免費額度保證。TWSE/MOPS 官方允許頻率、專案 Firestore/LLM 額度仍須另核對。
先修正先前規劃的重複：現有 3 個 TWSE endpoints 已包含月營收，所以是「2 個財務表 + 1 個月營收」，不可再額外重抓月營收一次。

| 工作 | 時間／cron | 每次工作 | 正常 HTTP 次數 |
|---|---|---|---:|
| 公司主檔 | 週日 01:17；17 1 * * 0 | 全市場公司資料一次 | 1/週 |
| 財務摘要 | 每日 06:11；11 6 * * * | 損益、資產負債各一次，依序執行 | 2/日 |
| 財報觀察加班次 | 啟用 filing_window 時 18:11 | 同上；預設關閉，窗口可設定且有到期日 | +2/日 |
| 月營收 | 每日 18:23；23 18 * * * | 全市場一次；按內容差異選擇受影響公司 | 1/日 |
| 重大訊息 | 08:07–21:37；7,37 8-21 * * * | 全市場一次 | 28/日 |
| 夜間重大訊息補查 | 23:07、次日 06:07；7 6,23 * * * | 全市場一次 | 2/日 |
| MOPS 增量 | 每日 20:19 起 | 已知待補 filing/revision queue；初期僅 2330/2454 | 變動，獨立預算 |
| 歷史回填 | 23:10–05:30 窗口 | 已啟用公司逐批；每晚至多 12 家 | 最多 84 個初次文件請求/夜 |
| 品質稽核 | 每日 06:47 | 完成批次＋昨日異常；只查 DB/raw | 0 外部請求 |
| 法說補漏 | 週六 10:43 | 初期只查已啟用 2 家；事件發現的附件另入 queue | 含變體/附件、受 MOPS 預算限制 |
| 新聞／社群／LLM | 預設 disabled | provider、授權與預算確認後才配置 | 0 |

上述 TWSE 日常約 33 次（2+1+30），主檔日 34，財報加班次日最多 36，**不含重試、redirect、MOPS、附件**。
重大訊息較前版補上夜間兩次；仍非即時完整保證。來源如只給短期列表，需确认保留窗口并設 archive 補漏，否則不能承諾零遺漏。
晚間 23:07 到次日 06:07 有 7 小時盲窗；前端明示抓取時間與監測時段。

### 限流預設

- TWSE：同來源全域併發 1、兩次 outbound request 起始至少隔 5 秒、每日硬上限 60（包含失敗/重試/重新導向）。重試預留 10，其餘未用配額不是必須耗盡。
- MOPS：初始全域併發 1、起始間隔至少 10 秒＋0–5 秒 jitter、每日硬上限 120；增量預留 24、回填 84、重試 12。來源顯示允許並穩定後才考慮併發 2。
- 法說頁變體、附件與缺年 probe 均算請求，84 個文件計畫不能視為必然只發 84 個 HTTP。預算達上限即暫停，不為了完成 12 家越額。
- 解析／分析 worker 初期 2，LLM 最多 1 且預設關閉。多個 Cloud Run instance 共用 budget/lease，不以單 instance semaphore 當全域限流。
- 手動 refresh 與排程共用 queue；priority 可提升，不能绕過冷卻或配額。
- 每日配額重置以台北日界定義；跨午夜回填同時受每夜批次上限與每日硬上限，不能重置後無限制繼續。
- 稽核在夜間窗口結束後執行；逾時回填 checkpoint 後停止領新工作，不讓稽核與無界回填競爭。

### 重試與斷點

| 情況 | 行為 |
|---|---|
| 429 | 整個來源進 cooldown；等待 max(Retry-After, 本地退避)；不得換 IP／憑證绕過 |
| 503／timeout | 5m、30m、2h + jitter，最多 3 次重試；重試也扣預算，持續失敗開 circuit |
| 401／403／驗證頁 | 停來源並要求檢查權限，不自動換來源身份繼續 |
| 404 未申報 | 記 unavailable，不立刻重試；依申報觀察窗口下次 probe |
| JSON schema 缺欄／200 HTML 封鎖頁 | raw 留存、quarantine、停止發布；通知維護者 |
| DB transient error | 重播 staged batch，不重新下載；相同 fact_id 不重複新增 |
| worker crash | lease 到期恢復，沿最近 committed checkpoint 重試 |

cursor 區分 last_attempt、last_success、last_committed_snapshot；解析失敗不能更新成功游標。
全量列表不依單一最大日期裁切：比較 source native id/revision/hash，以重疊窗口防止更正公告漏抓。
歷史 raw cache 按內容版本保留；需以低頻重新驗證較近期 filing，不能永久信任以 ticker/year 命名的舊 cache。

## 5. MOPS 與子產業的漸進擴充

1. 先把 company resolver 改為 repository-backed，保留 4 家 seed 作測試／demo fallback；official 模式主檔不可用就明確失敗，不能默默回到 4 家。
2. 96 家全部可保留主檔，但 ingestion_enabled 初期只開 2330/2454。reviewed 才啟用子產業專屬規則；medium 可抓資料並跑共同規則。
3. 2330/2454 完成 v2 校驗後擴至原 4 家，再擴至 12 家，最後 96 家。每階段看來源錯誤率、解析失敗率、DB/LLM 成本。
4. 96 家每晚 12 家是 8 個成功夜晚的容量估計，不是保證 8 天完成；缺件、限流、重試都可能延長。
5. 每家回填保存 ticker/year/scope/revision 狀態；已驗證現有年度不重抓；補缺年與更正版單獨入 queue。
6. 尚未驗證可用的「全市場新 filing 索引」。TWSE 摘要／重大訊息可當提示，但不是完整新申報索引；不能承諾只抓新增且不漏件。
7. 在可用索引確認前：初期 2 家每日檢查目標年度；擴充後採 12 家輪替＋受事件影響公司優先。同一來源預算共享，輪替模式最差約 8 個成功夜晚才完整巡檢，前端要揭露。
8. 法說不能只靠重大訊息觸發；加低頻補漏及事件附件狀態。新聞／社群為獨立擴充，不與可靠財報來源混為同一資料可信度。

## 6. 品質閘門與驗收標準

必須通過：必填欄／型別、唯一 identity、公司與 filing 外鍵、finite value、可解讀單位、period bounds/kind、scope、dataset URL 對應、namespace 隔離、來源版本鏈、提交狀態。
金額轉換需用原始單位對帳；資產=負債+權益採明確容差（依來源 scale/rounding），不硬要求浮點完全相等。
年度和月／季／累計資料不可直接加總比較；同期間同 scope 跨來源差異超容差進待查，不自動覆蓋。
缺少可選 XBRL concept 可 warn，但必需的規則輸入缺失應顯示 insufficient_data；不把不足規則當低風險。
freshness 分開 last_checked_at、source_as_of、last_changed_at；內容没變也可成功查核，不能把「沒新財報」判為抓取故障。

驗收案例：

- 同 schedule 兩次投遞只產生 1 個 job；兩個 worker 競爭只允許有效 lease 提交。
- 96 家處理 TWSE，正常每 cycle 僅 2 個財務 dataset requests；月營收只 1 次。
- 月營收本月／前月／去年同月跨一月邊界映射正確；月指標不得落在季度 period。
- 損益、資產負債、月營收各綁自己的 snapshot/source；缺失來源不借用其他可用來源。
- 同來源同內容重跑：facts 新增 0、分析新增 0、LLM 0，但 fetch_attempt 增加。
- parser/rule 升版：可從 raw／facts 重播，不發 HTTP；analysis version 留歷史。
- consolidated/individual/unknown、單季/ytd、official/demo 互不覆蓋。
- 更正版新增版本，選定 pointer 可更新，舊 evidence 仍查得到。
- 寫入中斷／第 2 批 Firestore 失敗：不發布半套結果；舊快照可讀；重跑不重複。
- 回填與新資料競爭：舊 run 完成後不覆蓋新發布 generation。
- 429、403、解析錯誤、LLM timeout 都有獨立狀態、預算与可重試判斷。
- SQLite 與 Firestore emulator 使用同一 contract fixtures，讀回結果語意一致。
- 2330/2454 五年 facts 逐科目／年度／單位對帳，月營收改正後重新計算 metrics/rules/snapshot。

## 7. 相容遷移與檔案實作順序

| 順序 | 擬新增／修改 | 完成條件 |
|---|---|---|
| A | data_contracts_v2.py、canonical_fact_repository.py、schema_migrations | SQLite/Firestore 共用 identity、格式與 namespace；先用全新測試 DB |
| B | company_registry.py／company_master_repository.py | 以 DB 主檔讀取、明確追蹤開關，不依靜態 4 家限制 |
| C | analysis_repository.py、fact_repository.py、pipeline_evidence_repository.py | 單一 canonical write/read；修正來源、期間、單位與精確 evidence references |
| D | source_snapshot_repository.py、source_fetch_pipeline.py | TWSE source-level fetch、hash、raw 重播與來源限流 |
| E | ingestion_run_repository.py、job_repository.py、outbox worker | 父子 run、stage counts、lease、checkpoint、circuit、budget |
| F | ingestion_pipeline.py、analysis worker、publisher | 從 DB 分析、版本化與發布 compare-and-set；AI 解耦 |
| G | config/pipeline_schedule.json、管理 endpoints、部署定義 | dry-run → 本機一次 → 小樣本 → 限量排程；不是這份設計文件就會執行 |

遷移步驟：

1. 對實際目標 DB 確認名稱／路徑、備份並記錄 row counts/hash；SQLite 用一致性 backup，不在活躍寫入時直接複製單檔。
2. 建 v2 新表／collections，舊資料不刪。migration_id + schema_version 可重跑。
3. 把 alias 明確映射；scope/公告時間/月份無法可靠還原的資料標 legacy_unverified/quarantine，不捏造值。
4. 由已存 raw snapshots／XBRL 還原並修正。若月資料原始檔不可得，另建受預算控管的修復抓取任務，不直接改 period 字串掩蓋問題。
5. 比較 legacy/v2 數量差異與原因：月角色合併、更正版本、quarantine、分析歷史各自對帳。
6. 2330/2454 shadow read 比較 API、facts、metrics、rules；測試通過才切 reader flag。舊 API 回應格式透過 adapter 保留。
7. 正式切換只准單一 canonical writer；需要雙寫時以 outbox 跟蹤，不做無追蹤 best-effort 雙寫。
8. 回滾切 reader 到舊版並暫停新排程；v2/raw 保留以便重播。舊資料刪除與保留期另行批准。

本輪交付：現況稽核、可重跑唯讀檢查、統一契約與整合／遷移／排程設計。未直接遷移，是為保留目前已確認存在語意錯誤的證據，避免錯誤資料被自動化擴大。

## 8. 證據與重跑

- 本次可執行查核：`fintrust_backend/scripts/audit_database_contract.py`（只用 Python standard library，mode=ro；BLOCKED exit=2）。
- 同步可檢視 notebook：`docs/database/DATABASE_CONTRACT_AUDIT.ipynb`。
- 現有 schema／写入：`app/services/analysis_repository.py`、`fact_repository.py`、`firestore_analysis_repository.py`。
- 現有抓取：`app/services/twse_openapi.py`、`official_event_sources.py`。
- 現有 orchestration／ledger：`app/services/ingestion_pipeline.py`、`app/pipeline_models.py`。
- 雲端遷移工具：`fintrust_backend/scripts/migrate_financial_sqlite_to_firestore.py`，預設 dry-run，只有 `--execute` 才會寫入 Firestore；contract audit 不通過時會直接阻擋。

在 repo 根目錄執行：

```bash
python fintrust_backend/scripts/audit_database_contract.py fintrust_backend/data/backfill-small-v2.sqlite3
```

判讀：SQLite integrity/主鍵檢查通過，不代表期間／來源／scope 語意正確。本報告以資料品質技能要求補上語意與關聯檢查，未將舊 PASS 沿用為全系統可靠性的保證。

完成新的 2330／2454 shadow backfill 後，應先執行：

```bash
PYTHONPATH=. python fintrust_backend/scripts/audit_database_contract.py <validated.sqlite3>
PYTHONPATH=. python fintrust_backend/scripts/migrate_financial_sqlite_to_firestore.py \
  --source <validated.sqlite3> --project fintrust-alert-ccu --tickers 2330 2454
```

dry-run 顯示資料筆數與 audit gate 均正確後，才由已授權的 Cloud Run／本機 ADC 執行相同命令並加上 `--execute`。本次環境沒有可用的 gcloud／ADC，因此尚未執行雲端寫入；Scheduler 仍保持未啟用。
