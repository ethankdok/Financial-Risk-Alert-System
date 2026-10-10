# Historical Research Package Contract (package schema 1.0)

A portable ZIP for one historical case. It needs no database, no FinTrust code
and no cloud credentials. Producer: `app/services/historical_audit/research_package.py`
(`python -m scripts.historical_audit_case research-package build …`).

## Layout

```
fintrust_historical_research_dataset/
  README.md                         human summary, consumers, cutoff warning
  manifest.json                     schema version, parameters, counts, completeness, per-file SHA-256
  data/
    financial_facts.csv|json        facts contract v1.2 (see HISTORICAL_FINANCIAL_FACTS_CONTRACT.md)
    filing_versions.csv             every filing artifact: original / restated / unknown_revision, artifact-level availability
    historical_summaries.csv        TPEx summary observations (summary values only; never filings)
    restatement_comparisons.csv     重編前/重編後 rows from official notices
    publication_timeline.csv        official publication events and evidence links
    source_inventory.csv            every archived source with category and SHA-256
    coverage_matrix.csv             per-year coverage and remaining gaps
    missing_evidence.csv            explicitly missing / unverified / failed-integrity items
  raw_evidence/
    financial_filings/<ticker>/<period>/<sha256>.<ext>          XBRL instances, report PDFs
    regulatory_disclosures/<ticker>/<source_key>/<sha256>.<ext>  TPEx/MOPS/TWSE notices and listings
    official_summaries/<ticker>/<source_key>/<sha256>.xls        TPEx 季報 workbooks
    conference_pdfs/<ticker>/<year>/<sha256>.pdf                 only with --include-conference and when archived
  conference/                       only with --include-conference: document index + JSD corpus (text evidence)
  validation/
    quality_report.json             integrity checks, PIT counts, EPS unit and unmapped-concept reports
    checksums.sha256                "<sha256>  <relative path>" for every file except itself and manifest.json
    verify_package.py               standard-library verifier (same code as package_verify.py)
  contracts/                        the data contracts the package was produced under
```

## Rules

- All paths are relative POSIX paths of safe characters. Builder and verifier
  reject absolute paths, drive letters, `..`, backslashes, symlinks and duplicates.
- **Integrity chain:**
  - `manifest.checksums_sha256` is the SHA-256 of `validation/checksums.sha256`;
  - every listed file must match its line;
  - files not listed are rejected;
  - raw evidence is named by its own SHA-256.
- Raw evidence is included only when present locally **and** its bytes re-hash
  to the recorded SHA-256. Otherwise a `missing_evidence.csv` row with
  `missing_locally` or `failed_integrity` is written. Data is never substituted.
- **Reproducibility:**
  - entries are sorted and use a fixed ZIP timestamp (1980-01-01) and mode `0644`;
  - JSON uses sorted keys;
  - `content_digest` (= `checksums_sha256`) is stable across rebuilds of unchanged inputs;
  - only `manifest.generated_at` varies, and the ZIP is byte-identical when `generated_at` is fixed.
- **Evidence types stay separate:**
  - financial facts, filing artifacts, summaries, comparisons, timeline and conference text are distinct files;
  - `filing_version_type` keeps original/restated/unknown;
  - conference text is never mixed into financial data.
- **Completeness:**
  - `manifest.completeness.status` is `partial` whenever any missing-evidence row exists;
  - `conference_evidence` is one of `included`, `not_requested`, `unavailable_for_ticker` or `unavailable_no_archive_configured`.
- Packages contain no credentials, environment files, databases or files outside the evidence archive.

## Verification

```bash
python validation/verify_package.py fintrust_historical_research_dataset.zip
python validation/verify_package.py ./fintrust_historical_research_dataset     # after extraction
```

Output: `{"status": "verified", "package_schema_version": "1.0", "content_digest": "...", "files_verified": N}`;
exit code 1 with an error message otherwise.
