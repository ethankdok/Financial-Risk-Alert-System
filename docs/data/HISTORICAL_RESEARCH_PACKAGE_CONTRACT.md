# Historical Research Package Contract (package schema 1.2)

A portable ZIP for one historical case. It needs no database, no FinTrust code
and no cloud credentials. Producer: `app/services/historical_audit/research_package.py`
(`python -m scripts.historical_audit_case research-package build …`).

## Two modes (`manifest.mode`)

| Mode | Built with | Contains | `suitable_for_historical_backtest` |
|---|---|---|---|
| `retrospective` | no `--as-of` | Everything currently recovered, including later restatements, later disclosures, current archival copies and conference documents | `false` |
| `strict_point_in_time` | `--as-of YYYY-MM-DD` (end of that day, Asia/Taipei; or an ISO timestamp) | Only evidence **verifiably public before the cutoff**, in every file | `true` |

An `as_of` always produces a strict package. Combining `retrospective` with
`as_of` is refused, because that combination was the schema-1.0 leak.

## Layout

```
fintrust_historical_research_dataset/
  README.md, manifest.json
  data/
    financial_facts.csv|json        facts contract v1.3
    filing_versions.csv
    historical_summaries.csv, restatement_comparisons.csv, publication_timeline.csv
    source_inventory.csv, coverage_matrix.csv, missing_evidence.csv
    conference_documents.csv        retrospective + --include-conference
    conference_text_corpus.csv      archival page-order text (not the JSD contract)
    conference_jsd_corpus.csv       rows the unchanged JSD adapter marks jsd_ready (header kept when empty)
    conference_page_index.csv       per page: text_status (text_extracted | low_text_coverage | image_or_scanned | failed_or_empty)
    conference_quality_report.csv
    conference_coverage.csv         year-by-year MOPS listing status, research_role, listing SHA-256
  conference/pages/<sha256>.pages.json   sanitized per-page JSON (no local paths)
  conference/text/<sha256>.txt
  raw_evidence/
    financial_filings/<ticker>/<period>/<sha256>.<ext>
    regulatory_disclosures/<ticker>/<source_key>/<sha256>.<ext>
    official_summaries/<ticker>/<source_key>/<sha256>.xls          (retrospective only)
    conference_pdfs/<ticker>/<year>/<sha256>.pdf                    (retrospective only)
  validation/quality_report.json, checksums.sha256, verify_package.py
  contracts/
```

A strict package is accompanied by a reviewer-only sidecar `<package>.audit.json` written next to the ZIP
(never inside it). See *Model-facing vs reviewer-only metadata* below.

## Strict point-in-time rules

- **Filing artifacts** (and raw bytes) are included only with a verified `available_at` before the cutoff.
- **Source documents** are included only when they are single-publication official notices published before the cutoff: TPEx announcements (date-only, so they count from the next Taipei midnight) and MOPS material-information detail pages. Listings and summary workbooks are current snapshots, so they are never included.
- **Facts** are included when their `effective_available_at` is before the cutoff. If the filing artifact is not itself public before the cutoff, its identity is withheld (`artifact_reference_status = withheld_not_public_at_cutoff`) and `availability_evidence_*` names the disclosure that dates the value. `observation_available_at`, `filing_available_at` and `effective_available_at` are separate fields.
- **Timeline events** are included only when public before the cutoff (`available_from`). Their links reference included artifacts only.
- **Conference documents** are excluded unless their public availability is verified. A cover date or MOPS meeting date is not publication evidence.
- **Summary observations** (TPEx summary values) are kept only when (a) the report's fiscal year ended before the
  cutoff and (b) a contemporaneous official disclosure published before the cutoff states the identical value for the
  same metric, fiscal year, statement scope, accounting framework and restatement side (a report whose fiscal year
  ended before the disclosure must match the *as previously reported* side; a later report must match the restated
  side). Kept rows become `evidence_type = official_disclosed_observation`, `completeness = disclosed_value_only`;
  the workbook reference (`source_url`, `content_hash`, `retrieved_at`) is withheld
  (`source_reference_status = workbook_withheld_not_public_at_cutoff`) and `pit_evidence_*` names the disclosure.
- **Coverage and quality files** are recomputed from the strict subset. `data/missing_evidence.csv` is header-only:
  exclusion counts describe the *current* archive and are reviewer-only metadata.
- **Contracts** are generic only (`STRICT_FIELD_DEFINITIONS.md`, this contract). Case narrative documents are excluded.

### Model-facing vs reviewer-only metadata (schema 1.2)

Everything inside a strict ZIP is model-facing and describes only what was public before the cutoff:

- `manifest.generated_at` is `null`; the manifest has no exclusion counts (only the allow-listed keys);
- there is no retrieval provenance file and no archive-wide exclusion count anywhere in the ZIP;
- every model-facing timestamp is expressed in Asia/Taipei (`+08:00`); `manifest.cutoff_taipei` and
  `manifest.cutoff_utc` state the same exclusive cutoff;
- filing (`filing_available_at`), observation (`observation_available_at`), disclosure (`disclosed_at`,
  `document_available_at`), effective (`effective_available_at`) and event (`available_from`) times are separate fields.

The reviewer-only sidecar `<package>.audit.json` holds the modern verification metadata: generation time, cutoff and
parameters, archive-wide exclusion counts (including conference documents), the row-level summary review (decision
per summary row) and raw-evidence retrieval provenance. It is bound to the ZIP by `package_sha256`, `content_digest` and `package_file` (the two files form one release and are
published together through a journaled, recoverable step) and is **not a
research input**.

### Strict verification (fails closed)

The builder runs the full verifier before writing anything. `verify_package.py` independently re-checks a strict package:

1. the manifest carries only allow-listed keys and no generation time;
2. no ISO date or timestamp at or after the cutoff, and no non-Taipei timestamp, in any model-facing file;
3. every filing version and source-inventory document is verifiably public before the cutoff;
4. every `raw_evidence/` file is the `package_raw_path` of an admissible artifact or notice; no conference content;
5. every SHA-256 referenced by a model-facing file resolves to included evidence;
6. every fact is point-in-time eligible before the cutoff; a withheld artifact has no identity fields, a
   `restatement_disclosure` reference that resolves to an included notice published no later than the stated
   availability, and equal observation and effective times; a verified artifact is an included filing version;
7. every summary row is an `official_disclosed_observation` with no workbook reference and an ended report period,
   and is **re-derived from the included raw notice** rather than trusted from producer flags: the verifier parses the
   MOPS notice itself (its own 序號/發言日期/發言時間, its subject's 個體/合併 scope, and the 重編前/重編後 tables in
   仟元 with ROC-year columns) and requires the row's metric (fixed label table), fiscal year, period/role structure,
   accounting framework, scope, unit (TWD thousand, normalized TWD), amount, `pit_evidence_ref`/`_url`/`_label`, the
   exact restatement side(s) stating the amount, and the side a report of that period must carry to agree, plus a
   matching `restatement_comparisons` row; an unparseable notice fails closed;
8. every restatement comparison is re-read from its included notice: announcement identity and time, scope, unit and
   both pre/post amounts must equal what the notice states;
9. timeline events are public before the cutoff and link only included filing versions;
10. `financial_facts.csv` equals `financial_facts.json`, and manifest counts equal row counts.

## Integrity and reproducibility (both modes)

- **Safe paths only.** Absolute paths, `..`, backslashes, symlinks and duplicates are rejected, and extraction happens only after full verification.
- **Integrity chain.** `manifest.checksums_sha256` is the SHA-256 of `validation/checksums.sha256`, which covers every file except itself and the manifest. Raw evidence is named by its SHA-256 and is included only when it re-hashes to the recorded value. Otherwise it gets a `missing_evidence.csv` row.
- **Reproducibility.**
  - Entries are sorted and use a fixed ZIP time, and JSON has sorted keys.
  - `content_digest` does not depend on `generated_at`.
  - The bytes of the embedded verifier follow the checkout's line endings.

## Verification

```bash
python validation/verify_package.py fintrust_historical_research_dataset.zip
python validation/verify_package.py ./fintrust_historical_research_dataset
```

Output: `{"status": "verified", "mode": "...", "package_schema_version": "1.2", "content_digest": "...", "files_verified": N}`.

## Schema history

- 1.0: initial portable package.
- 1.1: strict point-in-time mode; facts contract v1.3 (`observation_available_at`, `filing_available_at`, `artifact_reference_status`).
- 1.2 (additive): summary contract 1.1 (`observation_origin`, `scope_inference_basis`, `pit_evidence_*`,
  `side_consistency`, `source_reference_status`; `statement_scope_basis` states that a row's scope was inferred from
  the report row's revenue); strict reclassification of summaries; `manifest.cutoff_taipei`; reviewer-only audit
  sidecar; no modern metadata in strict ZIPs; semantic strict verifier. Retrospective packages are unchanged apart
  from the additive summary fields.
