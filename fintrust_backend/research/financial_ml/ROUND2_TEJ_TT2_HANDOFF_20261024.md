# FinTrust Round 2 — TEJ TT2 integration and licensed data acceptance

Date: 2026-10-24. Branch: `feature/financial-ml-round2-binary-labels-20261024`.
Round 2 is **one round**: no separate debug round, no model training, no production writes.

## What is implemented, and what is not yet finished

Implemented: deterministic TEJ TT2 historical event import, first-publication/fiscal-year pairing, event-date 24-month window, de-duplication, positive/negative *source-conditional* labels, annual core-amount secondary target, SHA-256 manifest, per-row source lineage, exclusions, immutable CSV/JSON reports, heldout 1785, hermetic CI tests.

**Not completed:** Actual extraction from the university's licensed TEJ TT2 account. No authorized TEJ TT2 export, TEJ API token, institution session or annual-financial universe export was available in this execution. Therefore actual TEJ imported events=0 and actual TEJ Y=0/1 rows=0, despite code/CI passing. The earlier Round2 silver-tier labels (8 positive, 18 controls) remain separate and are **NOT** silently renamed to TEJ labels. The TWSE/TPEx 21,967 issuer-year positions likewise are only **candidate positions**.

## TEJ source understanding (NOT alleged fraud)

The licensed **TT2** restated-financial-statement database is reported to begin in 1990; vendor sample of the audit-quality restatement-summary module describes fields:
- 公司、年/月、重編次數
- 重編事件日、原編表日、重編編表日、重編原因、依據
- financial pre-restatement amount + adjustment amount + ratio for
  營業收入、營業利益、稅後淨利、資產總額、股東權益.

References:
- TEJ licensed products coverage: https://home.lib.fju.edu.tw/TC/sites/default/files/Database_file/TEJ%E6%94%B6%E9%8C%84%E6%B8%85%E5%96%AE%282023%29.pdf
- TEJ audit-summary documentation: https://ref.lib.nccu.edu.tw/Eserv/TEJ_audit_2021.pdf
- TEJ finance-restatement definition: https://www.tej.com.tw/TEJPLUS/%E8%B2%A1%E5%8B%99%E8%B3%87%E6%96%99%E5%BA%AB%E6%8A%80%E8%A1%93%E6%89%8B%E5%86%8A-%E5%9F%BA%E7%A4%8E%E7%AF%87.pdf
- TEJ API docs: https://api.tej.com.tw/document_python.html

**CRITICAL:** TEJ restatement includes accounting-note, opinion and some classification changes, not necessarily intentional fraud or material monetary change. `原編表日` denotes an auditor's signing date, **NOT** proof of original public release. That release date must come from a separate audited filing-cover/source record.

## Export exactly TWO permitted research files via campus-licensed TEJ client

**File A: TT2/重編彙整 historical EVENT export.** TEJ Finance DB > 上市(櫃)重編財務報表 > general/financial/securities industry, or the restatement-summary module if separately licensed. Include ALL events (not only the 120 current issuers) affecting FY2013–FY2023 annual Q4; permit event notices up to 2026-10-24 so the 24-month outcome window can be observed for FY2023. Include current and delisted/unlisted-again issuers where license covers them; select "上市+上櫃+下市+下櫃". Do not unintentionally filter out quarterly correction sources before their associated FY relevance is examined. Export:
company, report year/month, restatement event date, consolidated vs standalone, reason, basis, original signature date as context, five financial adjustment amounts **if available**.
Event dates and fiscal period must be separate columns.

**File B: Annual-filing universe.** From annual *consolidated* source/cover (TEJ Finance DB/TA1 / financial-report cover) for every issuer-year in the target cohort, including companies with NO restatement event. Export ticker, 12-month fiscal period, statement scope, **first actual public disclosure date** and optional industry/market. If the first-publication date is absent from your TEJ entitlement, supplement from dated MOPS filing archives. **Do not replace missing publication dates with 12/31, current report crawl time or auditor's signing date.**

Export both files to local CSV UTF-8 BOM (or Big5/CP950). TEJ original columns can have variants: inspect actual header. No license file/key or complete licensed derivative output is committed to the public GitHub repository. The project's root .gitignore already excludes `fintrust_backend/data/`. For local storage use that directory only, with access allowed by your TEJ license.

## How to run the completed adapter from fintrust_backend

1. Run preflight (no TEJ access required):

```powershell
python -m research.financial_ml.round2_tej_tt2 --preflight --out data/financial_ml/round2_tej
```

2. Once the TWO permitted raw CSVs exist on the user's authorized computer, generate an **UNAPPROVED template** which fills SHA-256 hashes but sets all coverage attestations to false:

```powershell
python -m research.financial_ml.round2_tej_tt2 --prepare-coverage --tt2-csv "data/financial_ml/tej_licensed/tt2_events.csv" --universe-csv "data/financial_ml/tej_licensed/annual_universe.csv" --out data/financial_ml/tej_licensed
```

Then review/save `round2_tej_coverage_REVIEW_REQUIRED.json` as `tej_coverage.json`.
Explicitly verify:
- `closed_event_census_for_exported_universe=true` only when full TT2 event history is actually included for every exported issuer/year and after the full 24-month period;
- `includes_historical_delisted_firms=true` only when no surviving-company selection bias remains, or narrow the cohort and document that limitation;
- `issuer_and_year_filters_match=true` only after checking TT2 and universe have the SAME firm/year scope;
- `covered_fiscal_years`: list real FYs included, e.g. 2013..2023 only if each year covered;
- `tt2_event_coverage_through`: actual latest **covered** event date (not download date).
The assertions are **human supplied**, not independent TEJ verification. Rows get SOURCE_CONDITIONAL grade, not GOLD.

3. Run:

```powershell
python -m research.financial_ml.round2_tej_tt2 --tt2-csv "data/financial_ml/tej_licensed/tt2_events.csv" --universe-csv "data/financial_ml/tej_licensed/annual_universe.csv" --coverage-json "data/financial_ml/tej_licensed/tej_coverage.json" --out data/financial_ml/round2_tej_verified_input
```

If actual CSV headers differ, create a private JSON mapping file with `tt2` / `universe` objects, mapping canonical names to exact source headers, and pass `--column-map data/financial_ml/tej_licensed/header_map.json`. Never fabricate a nonexistent TT2 field.

Example mappings (illustrative only, modify to actual export):

```json
{"tt2":{"company":"公司","period":"年/月","event_date":"重編事件日","scope":"財報類別","delta_revenue":"營業收入_調整金額"},"universe":{"company":"公司","period":"年/月","first_published_at":"首次公告日","scope":"財報類別"}}
```

## Output contract

- `round2_tej_tt2_events.csv` — one issuer/FY/event-date after dedup.
- `round2_tej_issuer_year_labels.csv` — two binary targets `y_tej_restatement_24m` and `y_core_adjustment_24m` (can be blank if censored or no financial-delta evidence).
- `round2_tej_exclusions.csv` — incorrect years, scope, invalid dates, reserved 1785 and other excluded records with precise reasons.
- `round2_tej_audit_report.json` — TRUE actual input/event/company-year counts, positive/negative class counts, incomplete coverage, hashes and source caveats.

**No arbitrary 0 from an empty TT2 query.** Only sources accompanied by a comparable annual filing universe, publication timing and full relevant event census can yield a negative. TT2 false negatives and post-event filing numbers must be studied as separate limitations before serious modeling.

## QA and acceptance

GitHub Actions `financial-ml-round2-tej-tt2.yml` tests schema/date/grain/holdout, TT2 duplicates, 24-month censoring, core missingness, source SHA conflicts, negative coverage, idempotence. Synthetic unit-test fixtures are NOT labeled as real TEJ training data. The CI's `preflight` should truthfully report actual TEJ rows=0 until an authorized user supplies their export locally.

Once actual licensed exports become available, Round2 data acceptance requires:
- at least one official TT2 positive; 0 may be issued only if full coverage proven;
- nontrivial independent positive issuer and label distribution counts;
- review of all exclusion reasons and null rates;
- joinable company-year keys for subsequent Round3 original-financial `X`;
- no TEJ licensed payload in public commit/CI artifacts; only metadata and code;
- source-date limitations clearly reported.

**Next after DATA acceptance:** Round3 X financial features; Round4/5 features/quality/training split; Round6 traditional classifiers; Round7 heldout prediction. No neural networks before that.


## 校內 TEJ Pro 存取核實（2026）

國立中正大學圖書館「常用電子資源」確實列有「臺灣經濟新報資料庫 (TEJ)」：
https://lib.ccu.edu.tw/p/426-1011-154.php?Lang=zh-tw
這**不等於**已核實中正大學帳號包含 TEJ TT2 的授權；需由登入後實際模組或館員確認。

**請使用 2026 年的 TEJ Pro 介面。** TEJ+ 舊系統已公告於 2026/3/20 停用，
過去 PDF 中的 TEJ+ 路徑只供瞭解重編欄位概念，不能當成 2026 畫面逐步操作依據。
參考：https://lib.npust.edu.tw/news/9586/

TT2 匯出格式若是 .xlsx：請先在 Excel 另存一份 CSV UTF-8，保留原始 xlsx 不覆寫。
「報表簽證日／原編表日」與「對外首次公告日」不是相同概念，
後者必須另行取得且不能臆測為 3/31。

## 這次 CI 的真正意義
- TEJ 統合程式 9 個 hermetic 測試 **PASS**（如未來 CI 更動，以最新 workflow 為準）。
- 測試資料為人工製造的研究小樣例，不屬於學校 TT2 授權資料；
  不應加總到原 26 筆 silver 標籤、不能加總到 21,967 年度候選格數。
- 真實 TEJ TT2 事件與數值標籤直到實際匯出前維持 0。
- 任一無法解讀的 TT2 年度事件會阻止該年度落為 Y=0；只有五項核心財務調整欄位全部明確為 0，才容許把「已有 TT2 重編事件」的核心金額標籤定為 0。
