# 1785 光洋科 — Historical Publication Timeline (Phase 1B, extended in Phase 2A)

All times are Asia/Taipei (UTC+8). Each entry comes from an archived official
document (SHA-256 in [`HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md`](HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md)).
The machine-readable timeline (548 events: 359 from Phase 1B, plus 189 for 2017–2020 added in Phase 2A) is exported with
`evidence-export --dataset publication_timeline`.

## Timestamp semantics

| Field | Meaning | Used for point-in-time? |
|---|---|---|
| fiscal period | the reporting period (e.g. `2014FY`) | never |
| audit-report date | `tifrs-ar:ReviewAuditDate` inside a filing (`document_dated_at`) | never (lower bound only) |
| board approval / 事實發生日 | date stated in a notice | never |
| MOPS 發言日期 + 發言時間 | second-precision time the MOPS system published a company disclosure | yes, for the values disclosed in that notice |
| TWSE e-document 上傳日期 | second-precision upload time of a named archive file | yes, for that exact file only when its size matches and no 更(補)正 is recorded |
| TPEx 發文日期 | date-only regulator announcement | counts as public from **00:00 of the next Taipei day** (no verified intraday time) |
| `retrieved_at` | when FinTrust downloaded the bytes (2026) | never |

A period-level announcement is never propagated to every version of that
period. Links are typed `verified_linkage`, `period_level_only`,
`unverified_linkage` or `conflicting_evidence` (`publication_evidence_links`).

## Key events

| Time (Taipei) | Source | Event | Periods / scope | Linkage to archived artifacts |
|---|---|---|---|---|
| 2016-03-31 17:00–18:50 | MOPS 重大訊息 (listing) | Board meeting; FY2015 revenue self-reported vs audited adjustment | 2015FY | none (listing title only) |
| 2016-05-13 (date) | [TPEx 證櫃監字第10502004811號](https://www.tpex.org.tw/storage/eb_data/10505/10502004811.htm) | Former chairman/CFO admitted improper accounting (「致有財務報表不實表達之情事」); trading suspended from 2016-05-17 | — | none |
| 2016-08-19 17:10:05 | MOPS 重大訊息 seq 1 | 「公告重編本公司100年至104年間各受影響季度之財報」 (restatement required; differences 「尚待清查中」) | 2011–2015 | none |
| 2016-08-25 16:13:45–16:21:05 | TWSE e-document archive | Pre-restatement annual reports (re)uploaded, labelled 「此檔案為重編前之財報」 | FY2011–FY2015, consolidated + individual | **verified_linkage** for each downloaded original PDF (size match, 更(補)正 無). Conservative: the reports were first published in 2012–2016 at unverified times |
| **2016-11-13 21:25:31** | MOPS 重大訊息 seq 2 | 「本公司重編100年至104年各期個體財務報告說明」 with 重編前/重編後 tables | FY2011–FY2015 individual | values → `restatement_comparisons` (verified) |
| **2016-11-13 21:26:22** | MOPS 重大訊息 seq 3 | 「本公司重編100年至104年各期合併財務報告說明」 with 重編前/重編後 tables | FY2011–FY2015 consolidated | values → `restatement_comparisons`; 27 restated XBRL facts with identical values become PIT-eligible here (observation level) |
| 2016-11-14 15:16:56–16:55:37 | TWSE e-document archive | Restated annual reports uploaded (「重編」) | FY2011–FY2015 | `period_level_only`: later correction notices may have replaced the files |
| 2016-11-14 (stated) / 2016-11-15 (notice date) | [TPEx 證櫃監字第10502013431號](https://www.tpex.org.tw/storage/eb_data/10511/10502013431.htm) | 「業於105年11月14日公告並申報…重編之100年至104年之年度財務報告」; interim restatements still overdue | 2011–2015, both scopes | `period_level_only` to restated XBRL/PDF versions |
| 2016-11-17 18:22:26 | MOPS 重大訊息 seq 2 | Auditor opinions for FY2011–FY2015 corrected to add 「欲強調某一事項」 | 2011–2015 | `unverified_linkage`. The archived FY2013–FY2015 XBRL **contains** the emphasis flag, so it is not the uncorrected 11-14 upload |
| 2016-12-03 14:08–14:13 | MOPS 重大訊息 | Restated interim reports 100Q1 … 104Q3 explained | interim periods | not in Phase 1B scope (annual only) |
| 2016-12-05 17:43:16 | MOPS 重大訊息 seq 2 | 「公告更正…100至101年各年度母公司及合併財報、102至104年各年度個體及合併財報…」: notes/schedules corrected; e-books re-uploaded | 2011–2015, both scopes | `unverified_linkage` (archived bytes may be this re-upload) |
| 2016-12-05 (stated) / 2016-12-29 (notice date) | [TPEx 證櫃監字第10502015021號](https://www.tpex.org.tw/storage/eb_data/10512/10502015021.htm) | 「12月5日完成100年至104年之財務報告重編及更(補)正公告申報」; cites 「104年度重編後財務報告所示每股虧損2.62元」; trading resumes 2017-01-03 | 2011–2015 | `unverified_linkage` |
| 2017-01-20 14:31:27 | MOPS 重大訊息 seq 1 | 「公告更正本公司103年度重編後合併財報第83頁」 (FY2013 重編前 and impact amounts mistyped); report re-uploaded | 2014FY consolidated | `unverified_linkage` |
| 2017-03-21 19:19:45 | MOPS 重大訊息 seq 1 | Board resolution, no dividend (FY2016 audit-report date is also 2017-03-21) | 2016FY context | none |
| **2017-03-22 14:20:15** | TWSE e-document archive | FY2016 consolidated report uploaded (更(補)正 無) | 2016FY consolidated | **verified_linkage** for the PDF. `period_level_only` for the FY2016 XBRL, a different artifact |
| 2018-03-21 19:53:37 | MOPS 重大訊息 seq 6 | FY2017 board dividend resolution (cash dividend 0); the FY2017 audit-report date is 2018-03-21 | 2017FY context | none |
| 2018-03-27 16:04:35 / 16:19:03 | TWSE e-document archive | FY2017 consolidated (`AI1`) and individual (`AI3`) reports uploaded; the 更(補)正 column is **blank** | 2017FY | `period_level_only`; upload time **not verified** for these bytes (verification requires 無) |
| 2019-02-21 15:29:58 | MOPS 重大訊息 seq 1 | Board resolves to settle the investor-protection centre suit over the misstated 2011–2015 financials (≤ NT$334,000,000) | case context | none |
| 2019-03-28 18:32:24 / 18:33:38 | TWSE e-document archive | FY2018 consolidated and individual reports uploaded; 更(補)正 **blank** | 2018FY | `period_level_only` |
| 2019-05-29 14:18:18 | MOPS 重大訊息 seq 1 | 「加強補充本公司107年度個體、合併財報…附註」: note 9 (contingent liabilities / D&O insurance) corrected; reports re-uploaded to MOPS | 2018FY, both scopes | `unverified_linkage` to the FY2018 XBRL and both PDFs (the archived bytes may be the re-upload). Note-only, with no amounts listed |
| **2020-02-14 14:58:52 / 14:59:25** | TWSE e-document archive | FY2019 consolidated and individual reports uploaded (更(補)正 無; the audit-report date is 2020-02-12) | 2019FY | **verified_linkage** for both PDFs. `period_level_only` for the FY2019 inline XBRL |
| 2020-06-02 15:20:36 / 15:20:50 | TWSE e-document archive | FY2019 English translations uploaded | 2019FY | not downloaded |

## What is and is not established

- **Established, with exact timestamps:** official restated (重編後) and
  as-previously-reported (重編前) summary figures for FY2011–FY2015 became public
  on 2016-11-13 at 21:25:31 (individual) and 21:26:22 (consolidated).
- **Established for exact files:** the archived pre-restatement PDFs existed in
  the official archive from 2016-08-25, and the FY2016 PDF from 2017-03-22 14:20:15.
- **Not established:**
  - the upload time of the exact XBRL bytes now served by MOPS `t164sb01`;
  - which correction round (11-17, 12-05, 2017-01-20) the archived restated PDF/XBRL bytes reflect;
  - the original 2012–2016 publication times of the pre-restatement reports;
  - when the TPEx summary files were first published (their `Last-Modified`
    headers, 2016-07-25 and 2017-05-24, describe the current files only).

### FY2017–FY2019 (Phase 2A)

- **Established:**
  - the exact FY2019 PDFs were public from 2020-02-14 14:58:52 (consolidated) and 14:59:25 (individual);
  - the FY2018 report notes were corrected and re-uploaded on 2019-05-29.
- **Not established:**
  - when the exact XBRL bytes for FY2017–FY2019 were published, so no FY2017–FY2019 fact is point-in-time eligible;
  - whether the FY2017/FY2018 PDFs are the listed uploads (the 更(補)正 column is blank);
  - whether the FY2018 artifacts are the corrected re-upload.
- **Not a publication time:** the fiscal-year end and the audit-report dates (2018-03-21, 2019-03-26, 2020-02-12)
  are lower bounds only, never publication times.

