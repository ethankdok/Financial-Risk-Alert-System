"""Phase 3 research layer over the approved historical audit archive.

Pure, deterministic, Decimal-only computations that sit between ``historical_audit.research_access.ResearchBackend``
and the research API/UI. Nothing in this package writes to the official historical tables; derived results are
persisted only through ``result_store`` (append-only, separate storage).

Every computation carries one explicit ``AnalysisMode`` (see ``modes``); there is no default mode and no fallback from
strict point-in-time input to full retrospective data.
"""

RESEARCH_LAYER_VERSION = "1.0.0"
