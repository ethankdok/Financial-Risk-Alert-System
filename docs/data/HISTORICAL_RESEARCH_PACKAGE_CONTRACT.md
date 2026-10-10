# Historical Research Package Contract (package schema 1.1)

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
  validation/quality_report.json, checksums.sha256, verify_package.py, provenance.csv (strict)
  contracts/
```

## Strict point-in-time rules

- **Filing artifacts** (and raw bytes) are included only with a verified `available_at` before the cutoff.
- **Source documents** are included only when they are single-publication official notices published before the cutoff: TPEx announcements (date-only, so they count from the next Taipei midnight) and MOPS material-information detail pages. Listings and summary workbooks are current snapshots, so they are never included.
- **Facts** are included when their `effective_available_at` is before the cutoff. If the filing artifact is not itself public before the cutoff, its identity is withheld (`artifact_reference_status = withheld_not_public_at_cutoff`) and `availability_evidence_*` names the disclosure that dates the value. `observation_available_at`, `filing_available_at` and `effective_available_at` are separate fields.
- **Timeline events** are included only when public before the cutoff (`available_from`). Their links reference included artifacts only.
- **Conference documents** are excluded unless their public availability is verified. A cover date or MOPS meeting date is not publication evidence.
- **Coverage, missing-evidence and quality files** are recomputed from the strict subset. Exclusions are reported as aggregate counts only (`manifest.excluded_by_cutoff`).
- **Retrieval timestamps** are written to `validation/provenance.csv`; `data/` contains no post-cutoff date.
- **Contracts** are generic only (`STRICT_FIELD_DEFINITIONS.md`, this contract). Case narrative documents are excluded.

The builder refuses to write a strict ZIP if any post-cutoff date remains in
`data/`. For strict packages, `verify_package.py` independently re-checks:
- no ISO date or timestamp at or after the cutoff in `data/`;
- every `raw_evidence/` file is a `package_raw_path` with pre-cutoff availability;
- no `conference/` content.

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

Output: `{"status": "verified", "mode": "...", "package_schema_version": "1.1", "content_digest": "...", "files_verified": N}`.
