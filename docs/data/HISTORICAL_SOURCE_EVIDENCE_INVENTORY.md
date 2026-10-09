# 1785 光洋科 — Historical Source Evidence Inventory (FY2011–FY2016)

Machine-readable form: `evidence-export --dataset source_inventory` (45 rows:
41 Phase 1B source documents + 4 Phase 1 XBRL instances). Reviewed request plan:
`fintrust_backend/app/services/historical_audit/evidence_plans/1785.json`.
Shareable snapshot: [`../development/evidence/historical_audit_1785_phase1b_evidence.json`](../development/evidence/historical_audit_1785_phase1b_evidence.json).
Raw bytes are kept only in the gitignored archive `fintrust_backend/data/historical_audit/raw/`.
All were retrieved 2026-10-09/10 UTC.

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
