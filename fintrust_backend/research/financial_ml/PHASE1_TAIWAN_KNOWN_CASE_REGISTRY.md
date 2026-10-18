# Phase 1 — 台灣財報不實案例證據與標籤治理（2026-10-18）

## 研究目標與界線

預測特定**台灣公司某份已公告財報**的重大不實表達風險；主要輸入為在評分時間已公開且當時版本可用的 Beneish (1999) 8 特徵、Dechow et al. (2011) Model 1 7 特徵及可核對的輔助特徵。正式模型需全套 **台灣訓練、台灣驗證、台灣外部測試**，且具有時間 / 公司不重疊實驗。最終光洋科 1785 需以事件前「原始申報＋當時已知結果」回放；不能將事後重編數值當作事件前已公開資料。

**使用者最新修訂**：可使用真實美國 SEC 財報／正負樣本，或模擬資料／代理任務，作**預訓練、弱監督、輔助實驗、資料增強或研究對照**。但是**採納必須取決於事前定義的跨國可比性證據及台灣獨立測試**，而不是假定美國行為模式相同。合成標籤只表示模擬設定，不能被報告成「台灣公司實際財報不實」的確認標籤。

## 本輪真實案例蒐集（仍是 **review candidates**）

| 公司 | 研究候選受影響期間 | 來源與已查得事實 | 目前不可跨越的門檻 |
|---|---|---|---|
| **3027 盛達電業** | FY2015、FY2016 | 臺北地院 113 年度金訴字第 29 號**一審刑事判決**（2025-04-30）針對總額／淨額認列及重大不實表達有所認定；並引述公司於 **2017-06-08 23:58** 與 **2017-06-23 17:28** 的財報更正公告 | 判決是否確定、精確期別、2017 更正公告原始 MOPS、初次公開疑義的更早時間、原始未重編財報版本、方法審核 |
| **8299 群聯電子** | FY2014 待核對 | 高院 113 年度金上更一字第 2 號民事判決（2025-01-15）涉及舊財報不實、關係人交易及合併範圍。2016-08-05 檢調搜索另見公開報導，惟非已封存的一手首揭紀錄 | 核對具體財報期別與法院認定、上訴／確定狀態；歷年 original vs restated 財報不可混用 |
| **6452 康友-KY** | FY2017 Q2 至 FY2020 Q1 所涵蓋的四個年度（**起訴／訴訟主張，不等於四個確認正樣本**） | 投資人保護中心 2023-05-12 官方新聞稿，記載就上述期間財報**涉嫌**虛偽隱匿提出求償訴訟 | 案件結果及各期證據、正式首次揭露時間、原始版本；目前屬 alleged，不可直接給 `Y=1` |
| **1785 光洋科** | 既有財報不實研究案例 | 已在 `app/services/financial_research/case_labels.py` 及 `case_knowledge.py` 記載 | **不納入**任何本輪開發、訓練／調參／篩選與驗證；最後外部盲測才解鎖 |

來源（需下載並 SHA 封存原始文件後才能審核）：
- 3027 臺北地院司法判決： https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPDM%2C113%2C%E9%87%91%E8%A8%B4%2C29%2C20250430%2C1
- 8299 臺灣高院司法判決： https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPHV%2C113%2C%E9%87%91%E4%B8%8A%E6%9B%B4%E4%B8%80%2C2%2C20250115%2C1
- 6452 投保中心： https://www.sfipc.org.tw/News_Content.aspx?n=7458&s=571
- 8299 公視背景報導（**非法律定性或首次 MOPS 原文**）：https://news.pts.org.tw/article/331084
- 法規：證交法施行細則第六條，重編門檻與重大不實的法律判斷不能相互取代：https://twse-regulation.twse.com.tw/TW/law/DOC01.aspx?FLCODE=FL007010&FLNO=6

**證據分級**：法院對特定行為／期間的認定 > 有原始公開紀錄的公司更正重編／監理命令 > 官方正在進行的民事請求、刑事起訴或檢舉 > 報導與研究假說。判決的一審、上訴與確定狀態要另記，不因已出現「財報不實」字樣就推斷最終確定。**一般重編不一定等同造假**；沒有裁罰也**不能當成已證實正常**。

### 嚴格時間欄位

- `affected_fiscal_years`：結果標籤歸屬的被影響財報年度；不是案件發生日。
- `initial_disclosure_candidate_at`：搜尋時**發現的候選公開時間**；不等於查遍所有舊公告後的證實首次揭露。當未找到可靠時間一律 `null`。
- `legal_evidence_document_date`：法院判決／官方文件**文件日期**。絕不擅自當成「該日午夜已公開」，也不能據此倒填早期訓練標籤。
- `first_public_disclosure_primary_archived`：只有原始公告內容與時間戳，且已核對／封存後才可能為 true。
- `original_filing_pit_verified`：只允許取得當時已公開**原始版本**並有可核對數值的財報進入歷史預測。
- 所有待審 `supervised_label=UNKNOWN`；不創造 0/1，`admitted_into_model_*=false`。

**兩種不能混淆的回測**：
1. `RETROSPECTIVE_WITH_LATER_VERIFIED_OUTCOMES`：使用當時原始財報，事後的判決作獨立結果真值，以量測過去報表是否留下可識別特徵。模型可以是現代訓練，但不可稱為「2016 年模型真的已上線預警」。
2. `HISTORICAL_STRICT_ASOF`：模型超參數、訓練資料、當時已知 outcome、原始財報、發表時間均截斷於歷史時點，才可能聲稱當年可行的事件前預警。不能從後來判決把答案反向洩漏進當年訓練。

## 本輪已建立的功能

- `phase1_case_sources_seed.json`：3 件台灣案例＋保留光洋科＋美國／合成資料轉移政策。來源 URL 為可稽核搜尋錨點，**目前仍缺完整來源位元組 SHA**。
- `phase1_case_registry.py`：對公司身分、期間、來源類別、日期精度、審核狀態、保留案例與重複公司年度 fail-closed；產生 7 筆**公司年度候選**、來源索引、缺口報告。不產出訓練／測試標籤。
- `phase1_archive_evidence.py`：可將人工下載的官方 PDF/HTML/TXT 離線封存，保留 SHA-256，禁止覆寫來源不同的證據，**單純複製有雜湊仍不代表已確認其確實出自官方網站**。
- 對應 8 項資料庫測試＋3 項證據封存測試。測試及真實執行需要在使用者 ML Worktree 完成後才可宣稱通過。

## 執行方式（只寫本機研究結果，無 API／正式 DB）

```powershell
$branch = "feature/financial-ml-phase1-label-provenance-20261018"
if (@(git status --porcelain).Count -gt 0) { throw "Unsaved worktree changes" }
git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
if ($LASTEXITCODE -ne 0) { throw "Git fetch failed" }
git switch --detach "origin/$branch"
if ($LASTEXITCODE -ne 0) { throw "Git switch failed" }

python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Phase1 tests failed" }

$mlRoot=(git rev-parse --show-toplevel).Trim()
$mainRoot=Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$base=Join-Path $mainRoot "fintrust_backend\data\financial_ml"
python -m research.financial_ml.phase1_case_registry `
  --output (Join-Path $base "phase1_taiwan_known_case_candidates")
if ($LASTEXITCODE -ne 0) { throw "Case extraction failed" }
```

輸出：
- `taiwan_case_year_candidates.csv`（7 候選年度、0 個訓練標籤）
- `taiwan_case_evidence_register.csv`（4 來源錨點，未封存）
- `phase1_case_readiness.json`（缺口與保留案例報告）

**來源封存範例**：當原始司法判決已由使用者自行從上面司法網站另存為 HTML 時：

```powershell
python -m research.financial_ml.phase1_archive_evidence `
  --source-id judicial_3027_trial_2025 `
  --local-file "C:\path\downloaded-judgment.html" `
  --output (Join-Path $base "phase1_official_evidence_raw")
```

範例路徑需要替換成實際檔名。未另存證據時不執行這段。**它只是離線封存，不會自動認證官方來源**。

## 美國與模擬資料：可用，但須驗證台灣行為模式相容

研究允許 `US_SEC_REAL`、`SYNTHETIC_SCENARIO` 與台灣未標註樣本作輔助任務或預訓練。正式批准跨域遷移前：

1. 統一 GAAP / IFRS / TIFRS 的文獻帳項定義、時間跨度、公司規模、產業與會計年度。
2. 比較台灣／美國各 15 項文獻特徵的缺失率、產業及年份條件分布，使用分位數、KS / Wasserstein / JSD 等指標。先比較在共同支撐區域 (common support) 的公司，再評估領域差異。
3. 針對台灣真實已知正例與經審核的比較公司，評估只用台灣訓練、加入美國預訓練、加入合成輔助資料的**消融研究**，使用相同台灣驗證／保留測試設定。
4. 不以「美國樣本的 AUC 高」作為台灣可遷移的證據，不能依測試集選模型或校準機率；無標註的分布相似也不等於 **P(財報不實 | 財務特徵)** 相同。
5. 如果正式經驗證有幫助，可以把美國真實 outcome 用於**跨域預訓練**；合成資料可作已標記為 synthetic 的增強／健壯性試驗，但不得宣稱那些假想個案是台灣真實不實財報。

本階段**沒有**執行跨國分布比較，也沒有把美國／合成資料納入訓練，僅先建立拒絕自動批准的治理政策。

## 下一個階段（仍是 Phase 1）
1. 取得 3027 2017 年更正公告原文及最早相關財報不實疑義公開來源，釐清 2015/2016 年原始版本與影響項目。
2. 逐段審核 8299 司法證據與原始更正公告；6452 不可只憑投保中心提訴就標成已證實舞弊。
3. 擴大案例搜尋，將任何未列入現存 120 家抽樣的受影響公司納入**歷史案例資料獲取候選**，但不要改動凍結的 1785 holdout。
4. 制定可重現的案例／非案例追蹤窗口、時間知識可得性與角色分配，核准之後才逐年輸出可用於監督式模型的 outcome label。
