"""Phase 1 explicit offline primary-evidence byte archive.

The user supplies already downloaded official PDF/HTML/TXT bytes. This tool
records content digests and the claimed source URL without pretending that
copying a local file proves provenance, court finality or earliest discovery.
It never downloads and never generates an approved ML label.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

from .phase1_case_registry import validate

ALLOWED_EXTENSIONS = {".html", ".htm", ".pdf", ".txt"}
MAX_EVIDENCE_BYTES = 20 * 1024 * 1024


def stage_evidence(seed_file, source_id, local_file, output):
    data = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    cases = validate(data)
    ref = None
    cid = None
    for case in cases:
        for evidence in case["sources"]:
            if evidence["source_id"] == source_id:
                ref, cid = evidence, case["case_id"]
    if ref is None or cid is None:
        raise ValueError("source_id_not_in_reviewed_case_seed")
    if ref["kind"] == "SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE":
        raise ValueError("secondary_news_not_eligible_for_primary_evidence_archive")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", source_id):
        raise ValueError("bad_source_id_for_file")
    src = Path(local_file)
    if src.is_symlink() or not src.is_file():
        raise ValueError("missing_or_symlinked_evidence_file")
    if src.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("unsupported_evidence_extension")
    if not 0 < src.stat().st_size <= MAX_EVIDENCE_BYTES:
        raise ValueError("bad_evidence_size")
    raw = src.read_bytes()
    suffix = src.suffix.lower()
    digest = hashlib.sha256(raw).hexdigest()
    target = Path(output) / cid
    target.mkdir(parents=True, exist_ok=True)
    destination = target / (source_id + suffix)
    provenance = target / (source_id + ".json")
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError("blocked_existing_archive_mismatch")
        if not provenance.is_file():
            raise ValueError("existing_archive_missing_provenance")
        stored = json.loads(provenance.read_text(encoding="utf-8"))
        if stored.get("archive_sha256") != digest or stored.get("source_id") != source_id:
            raise ValueError("provenance_contract_mismatch")
        return stored
    if provenance.exists():
        raise ValueError("orphaned_evidence_provenance")
    record = {
        "status": "BYTES_ARCHIVED_ORIGINAL_SOURCE_IDENTITY_NOT_VERIFIED",
        "case_id": cid, "source_id": source_id, "claimed_source_url": ref["url"],
        "source_kind": ref["kind"], "source_document_date": ref["source_document_date"],
        "archive_sha256": digest, "archived_byte_size": len(raw),
        "local_file": str(destination),
        "independently_verified_original_source": False,
        "source_publication_time_verified": False,
        "affected_period_reviewed": False,
        "human_method_approval": False,
        "training_label_admitted": False,
        "normal_label_created": False,
        "network_requests": 0, "production_db_writes": 0,
        "note": ("Files manually supplied offline. The copied bytes are hashed, "
                 "but site provenance, judicial findings, original disclosure "
                 "time and financial filing version still require review.")
    }
    destination.write_bytes(raw)
    provenance.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return record


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline safe source-bytes archive; never an approved ML label")
    p.add_argument("--seed-file", default=str(Path(__file__).with_name("phase1_case_sources_seed.json")))
    p.add_argument("--source-id", required=True)
    p.add_argument("--local-file", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    print(json.dumps(stage_evidence(args.seed_file, args.source_id,
                                    args.local_file, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
