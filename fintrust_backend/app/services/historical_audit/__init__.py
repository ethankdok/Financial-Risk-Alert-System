"""Historical audit-case ingestion (Phase 1).

An isolated, version-aware archive of official historical financial filings for
case-based research. Nothing in this package writes to the production analysis
repository, the latest snapshots, Firestore, the scheduler or the AI layer; it
persists only into its own SQLite database and raw evidence archive.
"""
