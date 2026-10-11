# 1785 光洋科 — Historical Source Evidence Inventory (FY2011–FY2025)

Machine-readable form: `evidence-export --dataset source_inventory`. Reviewed request plan:
`fintrust_backend/app/services/historical_audit/evidence_plans/1785.json`.
Raw bytes are kept only in the gitignored archive `fintrust_backend/data/historical_audit/raw/`.

Source counts per phase and cumulative. Source documents are the notices, listings, summaries and PDFs in
`historical_source_documents`. MOPS XBRL filings are filing versions acquired by `backfill`. The
`source_inventory` export lists both.

| Phase (retrieved, UTC) | Fiscal years | Source documents | MOPS XBRL filings | Inventory rows added | Cumulative inventory rows |
|---|---|---|---|---|---|
| Phase 1 / 1B (2026-10-09/10) | FY2011–FY2016 | 41 | 4 | 45 | **45** |
| Phase 2A (2026-10-11) | FY2017–FY2019 | 18 | 3 | 21 | **66** |
| Phase 2B (2026-10-11) | FY2020–FY2022 | 24 | 3 | 27 | **93** |
| Phase 2C (2026-10-11) | FY2023–FY2025 | 19 | 3 | 22 | **115** |
| **Total** | FY2011–FY2025 | **102** | **13** | **115** | |

The per-phase figures in the sections below ("Phase 2A added 21 official sources", "Phase 2B added 27 official
sources") count source documents plus XBRL filings. They equal the "inventory rows added" column; Phase 2B
originally stated 30, an arithmetic error corrected in the carryover review.

The Phase 1 sections immediately below describe only the first 45 rows. Shareable Phase 1B snapshot:
[`../development/evidence/historical_audit_1785_phase1b_evidence.json`](../development/evidence/historical_audit_1785_phase1b_evidence.json).

## Source categories

| Category | Meaning | Never treated as |
|---|---|---|
| `official_original_filing` | complete pre-restatement report, labelled 「此檔案為重編前之財報」 by the TWSE archive | proof of its first-publication time |
| `official_restated_filing` | complete restated report (archive label 「重編」 or in-filing restatement wording) | proof of which correction round the bytes are |
| `official_filing_unknown_revision` | complete report without revision evidence (FY2016) | an original |
| `official_historical_summary` | TPEx 上櫃公司季報 selected indicators | an audited filing |
| `official_restatement_comparison` | MOPS notice with 重編前/重編後 summary tables | a complete original or restated statement |
| `official_publication_notice` | TPEx announcement / MOPS material information | proof of the exact contents of any archived file |
| `official_document_index` | MOPS t05st01 listings, TWSE t57sb01 listings | financial evidence |
| `unverified_candidate` | discovery lead only (e.g. Wayback Machine) | anything persisted as evidence |

## Inventory

### Complete filings

| Period | Scope | Framework | Classification | Source | SHA-256 (prefix) | Bytes | Verified availability |
|---|---|---|---|---|---|---|---|
| 2011FY | individual (母公司) | TW-GAAP | original | TWSE e-book `201104_1785_A01.pdf` | `2fa465f91e50c783` | 889,392 | 2016-08-25 16:13:45 (archive upload; conservative) |
| 2011FY | consolidated (母子公司合併) | TW-GAAP | original | `201104_1785_A02.pdf` | `088c6b1a8239df36` | 848,160 | 2016-08-25 16:14:29 |
| 2011FY | consolidated | TW-GAAP | restated | `201104_1785_A06.pdf` | `aa29c5b83ab85e47` | 4,945,053 | unverified (later corrections) |
| 2012FY | individual | TW-GAAP | original | `201204_1785_A01.pdf` | `629d459c96d9cd1e` | 893,081 | 2016-08-25 16:15:45 |
| 2012FY | consolidated | TW-GAAP | original | `201204_1785_A02.pdf` | `cd1a816b38421841` | 887,763 | 2016-08-25 16:16:26 |
| 2012FY | consolidated | TW-GAAP | restated | `201204_1785_A06.pdf` | `4f28e3a7b44daa4c` | 4,880,344 | unverified |
| 2013FY | consolidated | T-IFRS | original | `201304_1785_AI1.pdf` | `44c777c18128a59d` | 1,211,480 | 2016-08-25 16:17:04 |
| 2013FY | consolidated | T-IFRS | restated | `201304_1785_AI4.pdf` | `a9e9d1819c7389d4` | 5,922,024 | unverified |
| 2013FY | consolidated | T-IFRS | restated | MOPS t164sb01 XBRL | `6bf36dc71e09637e` | 281,676 | unverified (Phase 1) |
| 2014FY | consolidated | T-IFRS | original | `201404_1785_AI1.pdf` | `320b3dc81a7671c8` | 1,195,049 | 2016-08-25 16:18:27 |
| 2014FY | consolidated | T-IFRS | restated | `201404_1785_AI4.pdf` | `5b3a62ede7cc84e5` | 5,381,890 | unverified |
| 2014FY | consolidated | T-IFRS | restated | MOPS t164sb01 XBRL | `4d720af5a7b429df` | 349,550 | unverified |
| 2015FY | consolidated | T-IFRS | original | `201504_1785_AI1.pdf` | `0ca2d7e5636c0f6e` | 1,710,935 | 2016-08-25 16:20:54 |
| 2015FY | consolidated | T-IFRS | restated | `201504_1785_AI4.pdf` | `cc03c4c27ab614ad` | 5,073,849 | unverified |
| 2015FY | consolidated | T-IFRS | restated | MOPS t164sb01 XBRL | `02e3bf2ebc1dd88c` | 327,797 | unverified |
| 2016FY | consolidated | T-IFRS | unknown_revision | `201604_1785_AI1.pdf` | `56650227225a59a9` | 3,499,401 | **2017-03-22 14:20:15** |
| 2016FY | consolidated | T-IFRS | unknown_revision | MOPS t164sb01 XBRL | `c88a70a319af8989` | 352,386 | unverified |

TWSE e-book source: `POST https://doc.twse.com.tw/server-java/t57sb01` with
`step=9, kind=A, co_id=1785, filename=<file>`, which returns a temporary
`/pdf/…` link. Every downloaded size equals the archive's listed 檔案大小.

PDF parser compatibility: the primary statements (pages 3–9 of the FY2013
original, for example) are **scanned images**. No values are extracted
(`validation_status = extraction_pending`); no OCR was built. These PDFs
establish *which* official original/restated documents exist, not their numbers.

### Summaries and comparisons

| Source | Content | Framework | Availability |
|---|---|---|---|
| TPEx `O_2011Q4.xls` … `O_2016Q4.xls` (`https://www.tpex.org.tw/storage/statistic/financial/`) | Per file: 1785 current-year and prior-year 營業收入, 營業利益, 營業外收支 (≤2014 files) / 稅前淨利 (≥2015 files), 稅後純益, EPS; period-end 股本, 每股淨值, 淨值/資產, 流動比率. 84 observations | TW-GAAP (2011, 2012 files), T-IFRS (2013+ files) | **unverified**: `Last-Modified` 2016-07-25 (2011–2014 files) and 2017-05-24 (2015–2016 files) describe current files only. 12 values are corroborated by the 2016-11-13 notices |
| MOPS notice 2016-11-13 21:25:31 (individual), 21:26:22 (consolidated) | 158 before/after rows, FY2011–FY2015 | by year | verified at the notice time |

### Notices and indices

TPEx announcements 10502004811 (2016-05-13), 10502013431 (2016-11-15) and
10502015021 (2016-12-29); MOPS material-information listings for ROC 101–106
(279 rows) and 7 detail pages; TWSE e-document listings for ROC 100–105. See
[`HISTORICAL_PUBLICATION_TIMELINE.md`](HISTORICAL_PUBLICATION_TIMELINE.md).

## Findings from cross-checking sources

1. **TPEx summaries keep pre-restatement figures.**
   - FY2013: O_2013Q4 shows 稅後純益 408,817 and EPS 0.97. The restated XBRL shows 67,393 and 0.13.
   - FY2015: O_2015Q4 shows revenue 61,372,337 and EPS −2.63. Restated: 61,376,037 and −2.62.
   - This matches TPEx's note 「如遇有…重編財務報表，本報表不回溯重新編製」.
2. **The meaning of 稅後純益 changes between files.**
   - O_2013Q4 FY2013 408,817 equals the *consolidated total* (重編前 本期淨利).
   - O_2015Q4 FY2015 −1,060,346 equals the *parent-only* figure (individual notice), not consolidated −1,060,607.
   - So it is kept as `requires_review` and never mapped to `net_income`.
3. **Statement scope follows the accounting framework.**
   - TW-GAAP files (FY2011–2012) carry parent-company (individual) figures. FY2011 revenue 62,420,375 equals the individual notice, not consolidated 71,589,722.
   - IFRS files carry consolidated figures.
   - Scope is assigned only by an exact match to an officially scope-labelled value.
4. **重編前 ≠ first-published.**
   - FY2014 consolidated 重編前 本期淨利 is 416,617 in the 2016 notice.
   - The FY2014 summary file (O_2014Q4) shows 451,927.
   - The FY2015 file's comparative shows 396,380, which equals the individual 重編前 figure.
   - All are preserved. The notice's 重編前 values carry `pre_value_semantics = "as previously reported…"`.
5. **The IFRS transition changed comparatives.**
   - FY2012 revenue is 65,758,524 (TW-GAAP, individual) in O_2012Q4.
   - It is 73,976,695 (consolidated) as the comparative in O_2013Q4.
   - These are separate observations with different frameworks.

## Unavailable / unresolved

| Item | Status |
|---|---|
| Machine-readable original (pre-restatement) statements FY2011–FY2015 | Not available. MOPS `t164sb01` serves only the current (restated) XBRL; TWSE originals are scanned PDFs |
| Original first-publication times (2012–2016) | Not in MOPS material information ROC 101–104 (no annual-report filing notices); archive shows only the 2016-08-25 re-upload |
| Which correction round the restated XBRL/PDF bytes reflect | Unresolved (11-17 opinion correction, 12-05 notes correction, 2017-01-20 FY2014 p.83 correction) |
| FY2016 XBRL publication time | Unresolved; only the PDF upload time (2017-03-22 14:20:15) is verified |
| TPEx summary first-publication times | Unresolved; Wayback Machine CDX has no captures of the 2014/2015 files (2013 query: HTTP 503). Discovery lead only, never evidence |
| Restated individual PDFs (A05, AI6) and pre-restatement individual IFRS PDFs (AI3) | Listed in the archive, not downloaded in Phase 1B (consolidated scope prioritized; FY2011–2012 individual originals downloaded for the GAAP summary cross-check) |

## Phase 2A — FY2017–FY2019 (retrieved 2026-10-11 UTC)

Phase 2A added 21 official sources: 3 MOPS XBRL filings, 9 discovery documents, 6 PDFs and 3 notice details. It
also recorded MOPS conference listings for 2018 and 2019, without downloading any documents. Every Phase 1 source is
unchanged. The exact request log is in `docs/development/HISTORICAL_PHASE2A_FY2017_2019_VALIDATION.md`.

### Complete filings

| FY | Artifact | Scope | Format / taxonomy entry point | Revision | Availability | SHA-256 (prefix) |
|---|---|---|---|---|---|---|
| 2017 | MOPS `t164sb01` XBRL | consolidated | XBRL instance, `tifrs-ci-cr-2017-03-31` | unknown_revision | **unverified** (no upload record for these bytes) | `e9c71a2b` |
| 2017 | TWSE e-book `201704_1785_AI1.pdf` | consolidated | PDF, 8,824,577 B | unknown_revision | **unverified**: listed upload 2018-03-27 16:04:35, but the 更(補)正 column is blank | `0c32ddbd` |
| 2017 | TWSE e-book `201704_1785_AI3.pdf` | individual | PDF, 6,412,782 B | unknown_revision | **unverified** (listed 2018-03-27 16:19:03, blank 更(補)正) | `cb78010a` |
| 2018 | MOPS `t164sb01` XBRL | consolidated | XBRL instance, `tifrs-ci-cr-2018-09-30` | unknown_revision | **unverified**; FY2018 correction notice linked (`unverified_linkage`) | `cdec7a7e` |
| 2018 | TWSE e-book `201804_1785_AI1.pdf` | consolidated | PDF, 6,676,905 B | unknown_revision | **unverified** (listed 2019-03-28 18:32:24, blank 更(補)正; correction notice linked) | `043a676b` |
| 2018 | TWSE e-book `201804_1785_AI3.pdf` | individual | PDF, 6,579,870 B | unknown_revision | **unverified** (listed 2019-03-28 18:33:38, blank 更(補)正; correction notice linked) | `21eaab8b` |
| 2019 | MOPS `t164sb01` **inline XBRL** | consolidated | iXBRL, `tifrs-ci-cr-2019-03-31` | unknown_revision | **unverified** | `4dd3b38a` |
| 2019 | TWSE e-book `201904_1785_AI1.pdf` | consolidated | PDF, 6,731,750 B | unknown_revision | **verified 2020-02-14 14:58:52** (size match, 更(補)正 無) | `059ace3b` |
| 2019 | TWSE e-book `201904_1785_AI3.pdf` | individual | PDF, 6,594,182 B | unknown_revision | **verified 2020-02-14 14:59:25** (size match, 更(補)正 無) | `094137e3` |

All three MOPS filings parsed, each giving 18 facts, with core coverage 17/17. FY2017 and FY2018 are
`validated_with_warnings` only because of the known `eps_unit_declared_as_currency` issue; FY2019's inline XBRL
declares EPS per share correctly.

The FY2019 English translations (`AIA`, `AIC`) were uploaded 2020-06-02. They are listed but not downloaded,
because they are translations.

### Summaries and notices

- **TPEx summaries.** `O_2017Q4`, `O_2018Q4` and `O_2019Q4` were downloaded. Their current-file `Last-Modified` dates
  are 2018-04-02, 2019-04-03 and 2020-04-06, which describe the current files only. The 2018 and 2019 workbooks add
  a 速動 (quick ratio) column; it is ignored, and the column alignment was verified because revenue, operating
  income and EPS equal the XBRL values.
- **MOPS material-information listings** for ROC 107, 108 and 109 contain 48, 45 and 76 rows. No 重編 (restatement)
  of FY2017–FY2019 appears.
- **Details archived (3):**
  - **2018-03-21 19:53:37 #6:** FY2017 board dividend resolution.
  - **2019-02-21 15:29:58 #1:** board resolution to settle the investor-protection centre suit over the misstated
    2011–2015 financials (≤ NT$334,000,000).
  - **2019-05-29 14:18:18 #1:** **correction of FY2018 individual and consolidated financial-report notes**, note 9
    (contingent liabilities / D&O insurance for the settlement); the reports were "重新上傳至公開資訊觀測站"
    (re-uploaded to MOPS). Only note pages are listed, with no amounts, but the event is recorded as
    `financial_report_correction` for 2018FY.

### Findings

- **FY2016 comparative EPS.** The FY2017 filing's own XBRL presents FY2016 basic EPS as **−1.39**; the FY2016 filing
  reported **−1.23**. Net income attributable to owners of the parent is unchanged (−485,453 thousand), so the
  comparative EPS was adjusted retrospectively. The archived evidence does not state why, and this is not treated as
  a restatement of fundamentals. The TPEx FY2017 summary carries the same −1.39 as its prior-year comparative.
- **No restatement found.** No restatement of FY2017–FY2019 was found in the archived listings, so every version is
  `unknown_revision`. That label does not claim "original".

### Unavailable / unresolved (FY2017–FY2019)

| Item | Status |
|---|---|
| XBRL publication times FY2017–FY2019 | Unresolved; there is no upload record for the exact XBRL bytes, so the facts are not point-in-time eligible |
| FY2017/FY2018 PDF availability | Unresolved; the archive's 更(補)正 column is blank (verification requires 無) |
| Whether the FY2018 MOPS XBRL/PDF bytes are the 2019-05-29 re-upload | Unresolved (the correction is note-only according to the notice) |
| Investor-conference documents 2018 (10 listed) and 2019 (4 listed) | Listed by MOPS, not downloaded in Phase 2A (`document_missing`) |

## Phase 2B — FY2020–FY2022 (retrieved 2026-10-11 UTC)

Phase 2B added 27 official sources (24 source documents + 3 XBRL filings):

- 3 MOPS inline-XBRL filings;
- 11 discovery documents: TWSE e-book listings ROC 109–111, MOPS material listings ROC 110–114, and TPEx
  `O_2020Q4`–`O_2022Q4`;
- 6 annual PDFs;
- 7 notice details.

The request log is in `docs/development/HISTORICAL_PHASE2B_FY2020_2022_VALIDATION.md`.

### Complete filings

| FY | Artifact | Scope | Format / entry point | Revision | Availability | SHA-256 (prefix) |
|---|---|---|---|---|---|---|
| 2020 | MOPS `t164sb01` inline XBRL | consolidated | iXBRL, `tifrs-ci-cr-2020-06-30` | unknown_revision | **unverified** (artifact) | `43afc3f3` |
| 2020 | TWSE `202004_1785_AI1.pdf` / `AI3.pdf` | consolidated / individual | PDF (text layer) | unknown_revision | **verified 2021-03-08 17:32:17 / 17:34:10** (更(補)正 無, size match) | `b561ff61` / `0ac777fd` |
| 2021 | MOPS inline XBRL | consolidated | iXBRL, `tifrs-ci-cr-2020-06-30` | unknown_revision | **unverified** | `c82f57f4` |
| 2021 | TWSE `202104_1785_AI1.pdf` / `AI3.pdf` | consolidated / individual | PDF (text layer) | unknown_revision | **verified 2022-03-18 15:30:14 / 15:30:54** | `f2292ead` / `5311b320` |
| 2022 | MOPS inline XBRL | consolidated | iXBRL, `tifrs-ci-cr-2020-06-30` | unknown_revision | **unverified**; FY2022 notes correction linked | `7f4b5fa9` |
| 2022 | TWSE `202204_1785_AI1.pdf` / `AI3.pdf` | consolidated / individual | PDF | unknown_revision | **unverified**: listed 2023-03-22, but the 更(補)正 column is blank; correction linked | `db9eda1d` / `e748d289` |

All three XBRL filings parse to 18 facts, with core coverage 17/17 and status `validated`. EPS is declared per
share. Every metric maps to a primary concept, except the documented capex alias.

### Value-level disclosures (new evidence kind)

Annual consolidated financial-report board-approval notices (MOPS clause 31) state key figures in 仟元:

| Notice | Published (Taipei) | FY | SHA-256 (prefix) | Dates facts |
|---|---|---|---|---|
| `mops:20210305:173820:1` 「本公司民國109年度合併財務報告業經董事會決議通過」 | 2021-03-05 17:38:20 | 2020 | `682aebfd` | 7 |
| `mops:20220316:175938:2` (110年度) | 2022-03-16 17:59:38 | 2021 | `bf4620bb` | 7 |
| `mops:20230302:223839:3` (111年度) | 2023-03-02 22:38:39 | 2022 | `d66622fc` | 7 |

**Matched:** revenue, gross profit, operating income, net income, EPS, total assets and total liabilities, all
exact.

**Not matched (no canonical metric):**

- 稅前淨利 (pre-tax profit);
- 歸屬於母公司業主淨利 (profit attributable to owners of the parent);
- 期末歸屬於母公司業主之權益 (equity attributable to owners of the parent). This differs from total equity: for
  FY2020, 8,220,267 against 8,506,283 thousand.

No equivalent notice exists for FY2016–FY2019. In ROC 106–109 the board notices about the annual meeting carry no
figures (e.g. 2020-02-12).

### Corrections (search window: MOPS ROC 106–114, i.e. 2017–2025)

| Notice | Affects | Content | Effect on values |
|---|---|---|---|
| `mops:20210427:145546:1` | FY2017 individual and consolidated | note 6 investment-property accumulated impairment re-classified (土地 vs 房屋及建築); reports re-uploaded | "並不影響損益". No canonical metric changes |
| `mops:20220602:134747:3` | 2020 Q1–Q3 and 2021 Q1–Q3 interim | disposal gain re-timed from Q4 to Q1 2020 | "對109年度之損益無影響" (annual figures unaffected) |
| `mops:20230411:171742:3` | FY2022 individual and consolidated | related-party note: 9,650 元 corrected to 9,650 千元 | "對損益金額並無影響" |

The 2023-08, 2024 and 2025 corrections concern FY2023+ periods or monthly data and are out of scope. No restatement
(重編) of FY2017–FY2022 was found.

### Unavailable / unresolved (FY2020–FY2022)

| Item | Status |
|---|---|
| XBRL artifact publication times | Unresolved (no upload record). Values are dated at the observation level by the board notices only |
| FY2022 PDF availability | Unverified (blank 更(補)正; corrected 2023-04-11) |
| 11 of 18 facts per year | Not stated by any timestamped official disclosure, so they are not PIT-eligible |

## Phase 2C — FY2023–FY2025 (retrieved 2026-10-11 UTC)

Phase 2C added 22 official sources: 19 source documents and 3 XBRL filings. The source documents are:

- 7 discovery documents: TWSE e-book listings ROC 112–114, MOPS material listing ROC 115 (2026), and TPEx
  `O_2023Q4`–`O_2025Q4`;
- 6 annual PDFs;
- 6 notice details.

MOPS listings ROC 110–114 were already archived in Phase 2B. The correction search window is ROC 106–115, i.e.
through the 2026 listing retrieved on 2026-10-11.

### Complete filings

| FY | Artifact | Scope | Format / entry point | Revision | Availability | SHA-256 (prefix) |
|---|---|---|---|---|---|---|
| 2023 | MOPS `t164sb01` inline XBRL | consolidated | iXBRL, `tifrs-ci-cr-2020-06-30` | unknown_revision | **unverified**; FY2023 notes corrections linked | `d8c75ca3` |
| 2023 | TWSE `202304_1785_AI1.pdf` / `AI3.pdf` | consolidated / individual | PDF | unknown_revision | **unverified**: listed 2024-03-08, but the 更(補)正 column is blank; corrections linked | `a0229838` / `500806fb` |
| 2024 | MOPS inline XBRL | consolidated | iXBRL, `tifrs-ci-cr-2020-06-30` | unknown_revision | **unverified** | `42432af5` |
| 2024 | TWSE `202404_1785_AI1.pdf` / `AI3.pdf` | consolidated / individual | PDF | unknown_revision | **verified 2025-03-12 09:24:33 / 09:24:17** | `dd878791` / `f42c077c` |
| 2025 | MOPS inline XBRL | consolidated | iXBRL, `tifrs-ci-cr-2020-06-30` (audit report 2026-03-26) | unknown_revision | **unverified** | `34336a24` |
| 2025 | TWSE `202504_1785_AI1.pdf` / `AI3.pdf` | consolidated / individual | PDF (text layer) | unknown_revision | **verified 2026-03-26 13:50:14 / 13:50:56** | `fc715140` / `b503c126` |

All three XBRL filings parse to 18 facts, with core coverage 17/17 and status `validated`. The concepts are
identical to FY2020–FY2022, and the accounting identities hold exactly.

### Value-level disclosures

| Notice | Published (Taipei) | FY | Matched facts | Not matched |
|---|---|---|---|---|
| `mops:20240306:170411:3` | 2024-03-06 17:04:11 | 2023 | 7 | — |
| `mops:20250307:180848:5` | 2025-03-07 18:08:48 | 2024 | 7 | — |
| `mops:20260306:184123:3` | 2026-03-06 18:41:23 | 2025 | **5** | total assets and total liabilities (see below) |

**FY2025 discrepancy (recorded, not reconciled).**

- The board-approval notice states total assets **34,436,171** and total liabilities **19,423,635** thousand.
- The filed XBRL and the verified, audited PDF (balance sheet, page 8) state **34,434,450** and **19,421,914**:
  both 1,721 thousand lower, with total equity identical at 15,012,536.
- The notice's figures do not appear anywhere in the filed report.

Under the exact-match rule these two facts are not dated by the notice. The other five metrics match exactly.

### Corrections

| Notice | Affects | Content | Effect |
|---|---|---|---|
| `mops:20240812:034419:2` | FY2023 (112年第四季) consolidated | related-party note 三五: substantive related parties and commitments added | "更補正對本公司損益並無影響". Note-only; no canonical metric changes |
| `mops:20240812:034500:3` | FY2023 individual | related-party note 三二 (same additions) | as above |
| `mops:20250811:143440:2` | 2025 Q2 interim XBRL | auditor-review note amounts for an equity-method investee | "對114年第2季XBRL資訊合併財務損益無影響"; interim, so no annual artifact |

The 2024-08-12 #1 (2023 Q3) and #4 (2024 Q1) corrections are interim; they were identified from the listing titles
only. No restatement (重編) of FY2023–FY2025 was found.
