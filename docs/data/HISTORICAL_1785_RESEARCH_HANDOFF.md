# 1785 光洋科 historical research handoff (FY2011–2016)

Audience: Yu-Jing (financial-statement research) and Ethan (conference-text / JSD research).
Everything below can be used with **only the ZIP files and Python's standard library**. No Firestore, GCS,
SQLite, FinTrust code or credentials are needed.

## 1. Purpose

1785 光洋科 is a known case of misstated financial statements. The former chairman and CFO admitted improper
accounting in a TPEx announcement dated 2016-05-13, and the company published 重編前/重編後 (before/after) restatement
tables on MOPS on 2016-11-13. The two packages let you study the case with an explicit statement of **what was public
when**:

- **Retrospective research**: what the case looks like with everything recovered today.
- **Point-in-time research**: what an analyst could have known at a cutoff, with no later information.

## 2. The two packages

Both are in `fintrust_backend/data/historical_audit/packages/` (local, not in git).

| | Full (retrospective) | Strict (point-in-time) |
|---|---|---|
| File | `fintrust_1785_2011_2016_full.zip` | `fintrust_1785_asof_2016-11-14.zip` |
| SHA-256 | `693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826` | `304934a4a2e05dc16439155b267554a99a731ff6c07fa95e1cd05f25504f2bcf` |
| `manifest.mode` | `retrospective` | `strict_point_in_time` |
| Schema | 1.1 (unchanged, preserved) | 1.2 |
| Cutoff | none | end of 2016-11-14, Asia/Taipei (exclusive `2016-11-15T00:00:00+08:00`) |
| `suitable_for_historical_backtest` | `false` | `true` |
| Contents | everything recovered: later XBRL, all notices, TPEx summary workbooks, 2011 conference PDFs | only evidence verifiably public before the cutoff |
| Financial facts | 72 rows (27 point-in-time eligible) | 27 rows |
| Restatement comparisons | 158 | 158 |
| Summary observations | 79 | 11 |
| Filing versions | 17 | 7 |
| Timeline events | 359 | 249 |
| Conference documents | 2 (2011, bilingual) | 0 |

Next to the strict ZIP is `fintrust_1785_asof_2016-11-14.audit.json`. This is a **reviewer-only** sidecar, not a
research input. It holds:

- generation time;
- archive-wide exclusion counts;
- the row-level summary decisions;
- raw-evidence retrieval provenance.

It is bound to the ZIP by `package_sha256`. Do not feed it to a model.

**Which one to use**

- Any claim of the form "could have been detected at time T" must use the strict package, or a strict package
  rebuilt for that cutoff.
- The full package is for description, labelling and exploratory work.

## 3. Folder structure

```
fintrust_historical_research_dataset/
  README.md
  manifest.json                  mode, cutoff, counts, per-file SHA-256
  data/
    financial_facts.csv|.json    canonical financial facts (facts contract v1.3)
    filing_versions.csv          each archived filing artifact (original / restated / unknown_revision)
    restatement_comparisons.csv  重編前/重編後 rows from the MOPS 2016-11-13 notices
    historical_summaries.csv     TPEx 上櫃公司季報 summary values (summary contract 1.1)
    publication_timeline.csv     announcements, notices and e-book uploads with their public time
    source_inventory.csv         archived source documents
    coverage_matrix.csv          fiscal-year evidence coverage
    missing_evidence.csv         known gaps (header-only in the strict package)
    conference_*.csv             full package only (see section 9)
  conference/pages|text/         full package only
  raw_evidence/                  original bytes, named by SHA-256
  validation/                    quality_report.json, checksums.sha256, verify_package.py
  contracts/                     field contracts
```

## 4. Verification (do this first)

```bash
python -I validation/verify_package.py fintrust_1785_asof_2016-11-14.zip
# {"status": "verified", "mode": "strict_point_in_time", "package_schema_version": "1.2", ...}
```

The verifier is standard-library only. It checks the checksums and safe paths. For strict packages it also runs the
semantic point-in-time checks, which fail closed:

- no date after the cutoff;
- no modern metadata;
- every evidence reference resolves;
- every timestamp is in Asia/Taipei.

To extract safely, run the verifier on the ZIP first and then unzip. Alternatively, use `safe_extract` in
`package_verify.py`, which verifies the package before writing any file.

## 5. Field dictionary and units

**`financial_facts.csv`** (one row per fact)

| Field | Meaning |
|---|---|
| `fiscal_year`, `period` | fiscal year of the *figures* (e.g. `2013`, `2013FY`). **Not** a publication time. |
| `metric_code` | canonical metric (`revenue`, `cost_of_goods_sold`, `gross_profit`, `net_income`, `total_assets`, …) |
| `value`, `unit` | value in **TWD** (whole New Taiwan dollars). EPS, where present, is in TWD per share. |
| `statement_scope` | `consolidated` or `individual` (parent-only) |
| `accounting_framework` | `TW_GAAP` (FY2011–2012) or `TIFRS` (FY2013+) |
| `filing_version_type` | `original`, `restated` or `unknown_revision` (section 6) |
| `point_in_time_eligible` | `true` only when a verified public time exists |
| `effective_available_at` | earliest verified public time of this value (Asia/Taipei) |
| `observation_available_at` | time of the official disclosure that states this exact value |
| `filing_available_at` | verified public time of the filing artifact itself |
| `availability_evidence_*` | the disclosure that dates the value (ref, URL, SHA-256 of the included notice) |
| `artifact_reference_status` | strict only: `withheld_not_public_at_cutoff` means the value is dated by a notice and the later XBRL file's identity is withheld |

**`restatement_comparisons.csv`**

- `pre_restatement_value` / `post_restatement_value` / `difference` are in **TWD thousand** (`published_unit`), as
  disclosed.
- Deductions are negative. `sign_factor` gives the canonical sign.
- `pre_restatement_value` means *as previously reported according to the 2016-11-13 notice*. It is not necessarily
  the first-published figure.
- `disclosed_at`: 21:25:31 for the individual table, 21:26:22 for the consolidated table, 2016-11-13 Taipei.

**`historical_summaries.csv`**

- `value` is in **TWD thousand**; `normalized_value` is in TWD.
- `report_period` is the summary report that printed the value. `fiscal_year` is the year the value belongs to:
  a `prior_year_comparative` row prints the previous year inside a later report.
- `statement_scope_basis`: the scope of the whole report row, inferred from that row's revenue.
- `pit_evidence_*` and `side_consistency` are described in `contracts/` (summary contract 1.1).
- In the strict package, `evidence_type = official_disclosed_observation`. Each value there is dated by the MOPS
  notice that states it, and the TPEx workbook reference is withheld, because the workbook's own availability is
  unverified.

**Times.** All are ISO-8601 with an offset (strict package: always `+08:00`). They are separate, and none of them
is a retrieval or generation time:

- `filing_available_at`
- `observation_available_at`
- `disclosed_at` / `document_available_at`
- `effective_available_at`
- `available_from` (events)

## 6. Original vs restated

- **original**: the report as first filed. For FY2011–2015 the originals are scanned TWSE e-book PDFs. They have
  no machine-readable values, and their verified upload time (2016-08-25) is a conservative upper bound: they may
  have been public earlier.
- **restated**: figures after the 2016 restatement. These are the XBRL facts for FY2013–2015 and the 重編後
  columns.
- **unknown_revision**: FY2016 XBRL. No evidence says whether it was ever revised.
- Within each period and metric, never mix originals and restatements unless you deliberately compare them. Group by
  `filing_version_type` (facts) or use the pre/post columns (comparisons).

## 7. Fiscal year vs publication time

A fiscal year is **not** a publication date. FY2013 figures were first published in 2014, but the restated FY2013
values used here became public only on **2016-11-13 21:26:22**. When you align features to a prediction date, use
`effective_available_at` (or `disclosed_at`), never `fiscal_year` or `document_dated_at`.

## 8. What each researcher should use

**Yu-Jing (financial-statement features)**

- Point-in-time work:
  - strict `data/financial_facts.csv` (27 restated consolidated FY2013–2015 facts, 9 metrics);
  - `data/restatement_comparisons.csv` (before/after for FY2011–2015, both consolidated and individual;
    TW-GAAP for FY2011–2012, TIFRS for FY2013–2015);
  - `data/historical_summaries.csv` (11 disclosure-dated summary values).
- Descriptive work: the full `financial_facts.csv` filtered by `filing_version_type`, plus `coverage_matrix.csv`
  and `missing_evidence.csv` to see what is absent.
- Do not treat the TPEx summary workbooks (full package, `raw_evidence/official_summaries/`) as pre-cutoff
  information.

**Ethan (conference text, numeric context)**

- Text: in the full package, `data/conference_text_corpus.csv`, `conference/text/<sha256>.txt` and
  `data/conference_page_index.csv`. These are the archival page text of the two 2011-03-25 decks.
- Numeric context: `restatement_comparisons.csv` and `historical_summaries.csv`, keeping the units noted above.
- `data/conference_jsd_corpus.csv` is header-only by design (section 9). Do not lower JSD readiness rules to fill it.

## 9. Conference documents

**The two 2011 decks are one meeting.** `178520110325M001.pdf` (Chinese) and `178520110325E001.pdf` (English) share
the same MOPS row and meeting date 100/03/25 (2011-03-25), and both have 47 pages. They are two language versions
of the same presentation, so count them as **one** observation, not two.

They are not quarterly JSD-ready:

- the JSD adapter requires a confirmed reporting period, and neither deck states one that could be validated
  (`readiness_issues = period_unconfirmed`);
- they are investor presentations, not earnings-call transcripts, and must not be relabelled as transcripts;
- MOPS gives only the meeting date, so first public availability is unverified, and the decks are excluded from
  strict packages.

**Missing 2012–2016.** The official MOPS conference listing (t100sb02_1) returns 「查無資料」 for 2012–2016
(`conference_coverage.csv`: `no_official_record_found`). That shows absence from MOPS, not proof that no
conference took place. Third-party indexes were used only as leads and are never evidence.

## 10. Limitations

- **No pre-revelation inputs.** Before 2016-05-13 there are no verified financial inputs: 0 facts, 0 comparisons,
  0 summaries and 0 filing artifacts. The original reports' first-publication times are not recovered.
- **Restated values only, from 2016-11-13.** The strict facts are restated values dated by the 2016-11-13 notice.
  Original FY2012–2015 machine-readable values are not available (scanned PDFs only).
- **Partial summary coverage.** Summary values enter strict packages only where a contemporaneous notice states the
  identical value, which gives 11 of 79 rows.
- **Known cosmetic issues in the preserved full package.**
  - Its `statement_scope_basis` text repeats the *revenue* wording on operating-income rows (the scope and every
    value are correct).
  - One `missing_evidence.csv` FY2016 detail is split into two rows at a parenthesis.
  - Both are wording issues, not value defects, so the full ZIP was intentionally left unchanged.
- **Single company, single event.** This is one case study. It is not a sample.

## 11. Reporting findings without overstating them

- Say "point-in-time as of <cutoff>, Asia/Taipei" and name the package SHA-256.
- Do not claim the strict data shows that the misstatement was detectable **before May 2016**. There are no
  verified inputs before 2016-05-13.
- Do not report accuracy, AUC or similar for "prediction" on this case. With one positive company, results are
  illustrative only.
- Report the 2011 decks as one meeting, and say the 2012–2016 conference record is absent from MOPS.
- Distinguish *as previously reported (per the 2016 notice)* from *first published*.
- Keep units explicit: facts are in TWD; comparisons and summaries are in TWD thousand.

## 12. Standard-library example

```python
import csv
import io
import zipfile

PACKAGE = "fintrust_1785_asof_2016-11-14.zip"
ROOT = "fintrust_historical_research_dataset/"

def rows(archive: zipfile.ZipFile, name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(archive.read(ROOT + name).decode("utf-8"))))

with zipfile.ZipFile(PACKAGE) as archive:
    facts = rows(archive, "data/financial_facts.csv")
    comparisons = rows(archive, "data/restatement_comparisons.csv")

# Restated consolidated revenue (TWD) and when it became public.
for fact in facts:
    if fact["metric_code"] == "revenue":
        print(fact["period"], int(fact["value"]), fact["filing_version_type"], fact["effective_available_at"])

# Before/after revenue lines (TWD thousand) from the 2016-11-13 notices.
for row in comparisons:
    if row["canonical_metric"] == "revenue":
        print(row["period"], row["statement_scope"], row["pre_restatement_value"], row["post_restatement_value"],
              row["disclosed_at"])
```

## 13. Phase 2A addendum — FY2011–FY2019 packages (2026-10-11)

Two new packages extend the case to FY2019. The FY2011–2016 packages above are **unchanged** (same SHA-256), so
results computed on them remain reproducible.

| | Full (retrospective) | Strict (point-in-time) |
|---|---|---|
| File | `fintrust_1785_2011_2019_full.zip` | `fintrust_1785_2011_2019_asof_2020-12-31.zip` (+ `.audit.json`, reviewer-only) |
| SHA-256 | `9cbbd789d05d7652884b04f4ed2e865c9070557937ed34afec6476c70c92cb5e` | `7268951fdee67c3fd99465a45595f94550838aeacfb6d12affbd984e4559e0d7` |
| Cutoff | none | end of 2020-12-31, Asia/Taipei |
| Financial facts | 126 (18 per year, FY2013–FY2019) | 27 (unchanged: the FY2013–2015 restated facts) |
| Filing versions | 26 | 10 (adds the FY2019 PDFs, public from 2020-02-14) |

What is new for FY2017–FY2019:

- **Facts and units.** There are 18 consolidated facts per year from the MOPS XBRL; FY2019 is inline XBRL. Units are
  unchanged: TWD, with EPS in TWD per share. In FY2018 the taxonomy moved to `ifrs-full` concepts; the canonical
  metrics are unaffected, and the accounting identities hold every year.
- **Not point-in-time eligible.** These facts appear only in the full package. The XBRL bytes have no verified
  publication time and no official disclosure dates their values, so the strict package correctly has **no**
  FY2017–FY2019 facts. Do not use fiscal-year end or audit-report dates as availability.
- **Verified availability.** Only the FY2019 PDFs (2020-02-14) have a verified upload time. The FY2017/FY2018 PDFs
  stay unverified, because the archive's 更(補)正 column is blank.
- **FY2018 correction.** The FY2018 report notes (note 9) were corrected and re-uploaded on 2019-05-29. The
  notice lists no changed amounts.
- **FY2016 comparative EPS.** The FY2017 filing presents FY2016 EPS as −1.39, against −1.23 in the FY2016 filing,
  with net income unchanged. Treat it as a retrospectively adjusted comparative; the reason is not established.
- **Conference documents.** MOPS lists conference documents for 2018 (10) and 2019 (4); they are not yet archived
  (`document_missing`). The 2017 decks (2017-04-14) are included and are core in this package.

## 14. Phase 2B addendum — FY2011–FY2022 packages (2026-10-11)

The FY2011–2016 and FY2011–2019 packages are unchanged. The new files are listed below.

| | Full (retrospective) | Strict (point-in-time) |
|---|---|---|
| File | `fintrust_1785_2011_2022_full.zip` | `fintrust_1785_2011_2022_asof_2023-12-31.zip` (+ `.audit.json`, reviewer-only) |
| SHA-256 | `3d4cba560cfd8e46cf521291604583724b7ca2eb520384f35157caa2ee66221b` | `61042b7f17834077b67c77037be2202802a074cbefe39b7771be2d9aed1f4d56` |
| Cutoff | none | end of 2023-12-31, Asia/Taipei (exclusive 2024-01-01 00:00) |
| Financial facts | 180 (FY2013–FY2022, 18 per year) | **48** = 27 FY2013–2015 restated facts + **21 FY2020–2022 facts** |
| Filing versions | 35 | 14 |
| Conference documents | 32 files (26 distinct), 712 pages | none (meeting dates are not publication times) |

**What is new for Yu-Jing (financial features)**

- **Columns to read.** `data/financial_facts.csv` uses the same columns as before. Its new evidence value is
  `availability_evidence_kind = financial_report_disclosure`, which means the value is stated by the MOPS annual
  board-approval notice. For FY2020–2022 that covers 7 metrics per year: revenue, gross profit, operating income,
  net income, EPS, total assets and total liabilities. Each has an exact `effective_available_at`:
  - FY2020: 2021-03-05 17:38:20;
  - FY2021: 2022-03-16 17:59:38;
  - FY2022: 2023-03-02 22:38:39.

  The other 11 metrics per year (COGS, receivables, inventory, cash flows, total equity, …) are **not**
  point-in-time eligible: no timestamped official disclosure states them.
- **Value-level, not file-level.** The XBRL file itself is still `unverified`. Only the values the notice states
  are dated.
- **Board-notice figures.** `data/disclosed_financial_values.csv` (full package) holds every line of the three
  notices, including lines with no canonical metric. Use `normalized_value` (TWD; EPS in TWD/share). Its
  "equity attributable to owners of the parent" line is **not** total `equity`.
- **FY2017–FY2019.** Still 0 PIT facts. No equivalent notice exists, and the FY2019 PDF has no text layer.
- **FY2016 EPS.** The comparative EPS discrepancy (−1.23 against −1.39) is unchanged and unresolved; no new source
  explains it.

**What is new for Ethan (conference text)**

- **Coverage.** All official MOPS conference documents for 2018–2022 are archived: 28 files, every one
  hash-verified. Together with 2011 and 2017, the full package has 32 files. They sit in
  `data/conference_documents.csv`, `data/conference_text_corpus.csv`, `conference/text/<sha256>.txt` and
  `data/conference_page_index.csv`.
- **Use only distinct, paired documents.**
  - Drop rows whose `content_duplicate_of` is non-empty; for example, the 2018 May deck was listed for three
    meeting dates.
  - Group by `language_pair_key`: M (Chinese) and E (English) are one presentation.
  - That leaves 26 distinct files, about 13 presentations.
- **JSD readiness.** `data/conference_jsd_corpus.csv` has **0** rows, because every document has
  `period_unconfirmed` under the unchanged JSD contract. The archival text is complete: 693 of 712 pages carry a
  text layer. Do not assign a fiscal quarter from a meeting date.

**Reporting.** These packages support retrospective description and point-in-time feature construction at the
stated cutoffs. They do not show that the 2016 misstatement, or any later outcome, was predictable.
