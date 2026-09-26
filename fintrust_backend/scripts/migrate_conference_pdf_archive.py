"""Copy a local MOPS conference-PDF archive package to Google Cloud Storage.

Dry-run by default: nothing is written unless --execute is given. Copy-only and
idempotent: objects with the same SHA-256 are skipped, differing objects are
reported as conflicts unless --overwrite is given, and the local archive is
never modified or deleted. Credentials come from Application Default
Credentials (gcloud auth application-default login) or the attached service
identity; no key file is used.

Run from fintrust_backend:
  python -m scripts.migrate_conference_pdf_archive --source-root data/official-ir-pdfs-live-test \\
      --ticker 2330 --year 2025 --bucket <bucket> [--prefix conference-pdf-archive] \\
      [--execute] [--verify] [--overwrite] [--include-review-images] [--offline] [--list]

Exit status: 0 ok, 2 conflicts or upload errors, 3 verification failed, 4 invalid local archive.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.services.conference_pdf_archive_storage import (
    DEFAULT_PREFIX,
    plan_archive_package,
    publish_archive,
    storage_client,
    summarize_objects,
    verify_archive,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-root", type=Path, default=Path("data/official-ir-pdfs"))
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--bucket", default=os.getenv("CONFERENCE_PDF_ARCHIVE_GCS_BUCKET", ""))
    parser.add_argument("--prefix", default=os.getenv("CONFERENCE_PDF_ARCHIVE_GCS_PREFIX", "") or DEFAULT_PREFIX)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "") or None)
    parser.add_argument("--execute", action="store_true", help="actually upload (default is a dry run)")
    parser.add_argument("--verify", action="store_true", help="verify existence, size and SHA-256 of every object")
    parser.add_argument("--overwrite", action="store_true", help="replace destination objects whose SHA-256 differs")
    parser.add_argument("--include-review-images", action="store_true", help="also copy review-only page PNGs")
    parser.add_argument("--offline", action="store_true", help="plan from the local archive only; do not contact GCS")
    parser.add_argument("--list", action="store_true", help="print every planned object")
    args = parser.parse_args()

    directory = args.source_root / args.ticker / str(args.year)
    try:
        portable, artifacts = plan_archive_package(directory, include_review_images=args.include_review_images)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "invalid_local_archive", "error": str(exc)}, ensure_ascii=False))
        return 4

    if args.offline:
        report = {
            "mode": "offline_plan", "ticker": args.ticker, "year": args.year,
            "prefix": f"{args.prefix.strip('/')}/{args.ticker}/{args.year}",
            "planned": len(artifacts), "planned_bytes": sum(len(a.data) for a in artifacts),
            "by_type": {},
            "objects": [{"object": f"{args.prefix.strip('/')}/{args.ticker}/{args.year}/{a.name}",
                         "type": a.artifact_type, "bytes": len(a.data), "action": "upload_planned"} for a in artifacts],
        }
        for artifact in artifacts:
            bucket = report["by_type"].setdefault(artifact.artifact_type, {"count": 0, "bytes": 0})
            bucket["count"] += 1
            bucket["bytes"] += len(artifact.data)
        _print(report, args.list)
        return 0

    if not args.bucket:
        parser.error("--bucket (or CONFERENCE_PDF_ARCHIVE_GCS_BUCKET) is required unless --offline is used")
    client = storage_client(args.project)
    exit_code = 0
    report = publish_archive(
        client=client, bucket=args.bucket, prefix=args.prefix, ticker=args.ticker, year=args.year,
        directory=directory, execute=args.execute, overwrite=args.overwrite,
        include_review_images=args.include_review_images,
    )
    if report["status"] != "ok":
        exit_code = 2
    if args.verify:
        report["verification"] = verify_archive(
            client=client, bucket=args.bucket, prefix=args.prefix, ticker=args.ticker, year=args.year,
            directory=directory, include_review_images=args.include_review_images,
        )
        if report["verification"]["status"] != "ok":
            exit_code = exit_code or 3
    _print(report, args.list)
    return exit_code


def _print(report: dict, list_objects: bool) -> None:
    objects = report.pop("objects", [])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if list_objects:
        for line in summarize_objects({"objects": objects}) if objects and "action" in objects[0] else []:
            print(line)


if __name__ == "__main__":
    raise SystemExit(main())
