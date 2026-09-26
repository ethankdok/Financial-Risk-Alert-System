# Official conference JSD bridge (Method A)

FinTrust side: official archive → `ConferenceJsdCorpusAdapter` → comparable pair →
`JsdCalibrationRepository` → `JsdBridgeService` → `POST /api/v1/financial/data-shift/analyze`
→ Flask `POST /api/financial/data-shift/analyze` → `result.html` Data Shift section.

Teammate side (unchanged, reference `origin/feature/tsmc-quarterly-corpus` @
`5b914937dc3cb2294851e0386c67270d20547e7e`): `calculate_jsd`,
`calculate_cosine_similarity`, `check_data_quality` in `data_shift.py`, historical
calibration and percentiles in `scripts/calibrate_tsmc_shift.py`, and the combined rule
(JSD ≥ P90 and Cosine ≤ P10). Method B (`taiwan_shift.py`, Chinese monthly groups) is a
separate method and is not used here.

## Calculator

`app/services/jsd_method.py` imports the shared `data_shift.py` (never copied) and checks
its LF-normalized SHA-256 against the reference
(`aa94cf9e…86318b`). A missing or different module fails closed
(`analysis_status = method_unavailable`). Legacy STRUX constants and
`determine_drift_level` are never called by the bridge.

## Calibration profiles

`app/services/jsd_calibration.py` — `JsdCalibrationProfile` (scope: ticker, document
type, language, source family; method: method version, calculator hash, extraction
method, preprocessing version; thresholds; history window; research commit).
A profile applies only to an exact scope match, and only to targets that start after its
history window ends. Storage: `shift_calibrations` in Firestore (production),
`app/calibration_profiles/*.json` (local/tests).

Profiles are produced from a teammate calibration report by
`scripts/import_jsd_calibration_profile.py` (dry-run by default, explicit
preprocessing/extraction/source-family/commit, conflict instead of overwrite).

Imported: `jsdcal-2330-d0bcbeb14e2f72be10a1` — 2330, `full_earnings_transcript`,
`en_may_include_translation`, investor.tsmc.com transcripts, `pypdf_layout_mode
(build_tsmc_corpus.extract_pdf)`, `tsmc-corpus-extract_pdf@5b914937`, 33 history pairs to
2025Q2.

## Golden checks (real TSMC 2025Q3→2025Q4 transcripts, unmodified teammate code)

| | Bridge | Teammate function | Teammate report |
|---|---|---|---|
| JSD | 0.193571 | 0.193571 | 0.193571 |
| Cosine | 0.615582 | 0.615582 | 0.615582 |
| Thresholds / rule / drift | identical | — | 單一指標異常（待觀察） |

## Current coverage

MOPS conference records are `earnings_presentation` / `financial_results_release` with
FinTrust extraction (`mops_conference_pipeline:pypdf_extract_text_per_page`,
`fintrust-conference-document-text-v1`). No calibration profile matches them, so they
return raw JSD / cosine with `calibration.status = unavailable` and no drift level.

## Cloud Run prerequisite (not deployed)

The FastAPI image does not contain `data_shift.py` or its import dependencies
(`pandas`, `scikit-learn`, `Flask` for its module-level `Blueprint`). Until the image adds
them (`COPY data_shift.py` in `Dockerfile.fastapi` plus requirements), the cloud endpoint
fails closed with `method_unavailable`.
