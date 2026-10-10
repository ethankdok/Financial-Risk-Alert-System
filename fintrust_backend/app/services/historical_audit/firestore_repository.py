"""Additive Firestore mirror of the historical research archive.

Collections are namespaced ``<prefix>_<kind>`` (default prefix
``historical_research``) and never touch the production financial collections
(``normalized_financial_facts``, ``companies``, snapshots …). Document ids are the
archive's deterministic ids (``hfv1_…``, ``hff1_…``, ``hpe1_…`` …), so distinct
filing versions can never collapse into one document.

Writes are create-only. An existing document with the same content is
``exists_same``; one that differs only by *filling* an annotation field that is
still unknown (``unknown_revision`` → classified, ``unverified``/null → verified)
is ``filled``; any other difference is a ``conflict`` and is not written.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

RECORD_KINDS = (
    "cases", "filing_versions", "facts", "source_documents", "publication_events", "evidence_links",
    "comparisons", "summary_observations", "observation_availability", "objects", "packages", "sync_runs",
)
ID_FIELDS = {
    "cases": "ticker", "filing_versions": "filing_version_id", "facts": "fact_id",
    "source_documents": "source_document_id", "publication_events": "event_id", "evidence_links": "link_id",
    "comparisons": "comparison_id", "summary_observations": "observation_id",
    "observation_availability": "availability_id", "objects": "object_id", "packages": "content_digest",
    "sync_runs": "run_id",
}
# field → values that may be replaced (by a non-empty value) when a later import learns more.
FILLABLE: dict[str, dict[str, tuple[Any, ...]]] = {
    "filing_versions": {
        "filing_version_type": ("unknown_revision",), "version_type_evidence_json": ("[]",),
        "available_at": (None,), "availability_status": ("unverified",), "availability_basis": (None,),
        "source_published_at": (None,), "verification_evidence_json": (None, "[]"),
    },
    "facts": {"available_at": (None,)},
}
MUTABLE_KINDS = {"sync_runs"}  # operational status documents, not evidence
INTERNAL_FIELDS = ("_record_sha256",)


class FirestoreConflictError(RuntimeError):
    pass


def record_sha256(data: dict[str, Any]) -> str:
    payload = {key: value for key, value in data.items() if key not in INTERNAL_FIELDS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _already_exists(exc: Exception) -> bool:
    return type(exc).__name__ in {"AlreadyExists", "Conflict"} or getattr(exc, "code", None) == 409


class FirestoreHistoricalResearchRepository:
    backend_name = "firestore"

    def __init__(self, client: Any, *, prefix: str = "historical_research") -> None:
        if not prefix.startswith("historical_research"):
            raise ValueError("Firestore prefix must start with 'historical_research'.")
        self.client = client
        self.prefix = prefix

    def collection_name(self, kind: str) -> str:
        if kind not in RECORD_KINDS:
            raise ValueError(f"Unknown record kind {kind}")
        return f"{self.prefix}_{kind}"

    def _ref(self, kind: str, document_id: str):
        if not document_id or "/" in document_id:
            raise ValueError("Unsafe Firestore document id")
        return self.client.collection(self.collection_name(kind)).document(document_id)

    def get(self, kind: str, document_id: str) -> dict[str, Any] | None:
        snapshot = self._ref(kind, document_id).get()
        if not getattr(snapshot, "exists", False):
            return None
        return snapshot.to_dict() or {}

    def write(self, kind: str, data: dict[str, Any]) -> str:
        document_id = str(data[ID_FIELDS[kind]])
        record = {**data, "_record_sha256": record_sha256(data)}
        ref = self._ref(kind, document_id)
        if kind in MUTABLE_KINDS:
            ref.set(record)
            return "written"
        try:
            ref.create(record)
            return "created"
        except Exception as exc:
            if not _already_exists(exc):
                raise
        existing = self.get(kind, document_id) or {}
        if existing.get("_record_sha256") == record["_record_sha256"]:
            return "exists_same"
        fillable = FILLABLE.get(kind, {})
        updates: dict[str, Any] = {}
        for key in set(existing) | set(data):
            if key in INTERNAL_FIELDS or existing.get(key) == data.get(key):
                continue
            if key in fillable and existing.get(key) in fillable[key] and data.get(key) not in (None, ""):
                updates[key] = data[key]
                continue
            raise FirestoreConflictError(f"{kind}/{document_id}: field {key!r} differs from the stored record")
        if not updates:
            return "exists_same"
        merged = {**{k: v for k, v in existing.items() if k not in INTERNAL_FIELDS}, **updates}
        updates["_record_sha256"] = record_sha256(merged)
        ref.update(updates)
        return "filled"

    def list(self, kind: str, *, ticker: str | None = None) -> list[dict[str, Any]]:
        collection = self.client.collection(self.collection_name(kind))
        if ticker is not None:
            try:
                from google.cloud.firestore_v1.base_query import FieldFilter

                query = collection.where(filter=FieldFilter("ticker", "==", ticker))
            except ImportError:  # pragma: no cover - dependency guard
                query = collection.where("ticker", "==", ticker)
        else:
            query = collection
        rows = [document.to_dict() or {} for document in query.stream()]
        return sorted(rows, key=lambda row: str(row.get(ID_FIELDS[kind])))

    def verify_record(self, kind: str, data: dict[str, Any]) -> bool:
        stored = self.get(kind, str(data[ID_FIELDS[kind]]))
        return stored is not None and stored.get("_record_sha256") == record_sha256(
            {k: v for k, v in stored.items() if k not in INTERNAL_FIELDS}) and all(
            stored.get(key) == value for key, value in data.items())


def strip_internal(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k not in INTERNAL_FIELDS} for row in rows]
