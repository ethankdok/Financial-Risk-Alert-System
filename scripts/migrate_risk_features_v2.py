from __future__ import annotations

import argparse
import ast
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from flask_data_repository import (
    DuplicateRecordError,
    FirestoreFlaskDataRepository,
    FlaskDataRepository,
    SqliteFlaskDataRepository,
)


LEGACY_TO_CANONICAL = {
    "保證報酬": "保證報酬／低風險高報酬",
    "未公開消息": "內線／未公開消息訴求",
    "來源不可驗證": "來源不可驗證",
    "時間急迫": "急迫性／時間壓力",
    "稀缺壓力": "稀缺性訴求",
    "加入／聯絡誘導": "群組／私訊／外部導流",
    "權威訴求": "未驗證權威訴求",
}

NEW_CANONICAL_FEATURES = {"社會認同／從眾訴求"}
CANONICAL_FIELDS = ("name", "dimension", "weight", "keywords", "definition", "explain")
DEFAULT_APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def canonical_risk_features_from_app(app_path: Path = DEFAULT_APP_PATH) -> list[dict[str, Any]]:
    """Read the Phase 4 v2 seed definitions from app.py without importing Flask."""
    tree = ast.parse(app_path.read_text(encoding="utf-8"), filename=str(app_path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "ensure_seed_data":
            for child in ast.walk(node):
                if not isinstance(child, ast.Assign):
                    continue
                if not any(isinstance(target, ast.Name) and target.id == "features" for target in child.targets):
                    continue
                entries = ast.literal_eval(child.value)
                return [
                    {
                        "name": name,
                        "dimension": dimension,
                        "weight": int(weight),
                        "keywords": list(keywords),
                        "definition": definition,
                        "explain": explain,
                    }
                    for name, dimension, weight, keywords, definition, explain in entries
                ]
    raise RuntimeError(f"Cannot find canonical risk feature definitions in {app_path}")


def _system_names(canonical_features: list[dict[str, Any]]) -> set[str]:
    return set(LEGACY_TO_CANONICAL) | {feature["name"] for feature in canonical_features}


def _canonical_by_name(canonical_features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {feature["name"]: deepcopy(feature) for feature in canonical_features}


def _changed_fields(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for field in CANONICAL_FIELDS:
        current_value = list(current.get(field) or []) if field == "keywords" else current.get(field)
        desired_value = list(desired.get(field) or []) if field == "keywords" else desired.get(field)
        if current_value != desired_value:
            changes[field] = desired_value
    return changes


def _public_feature(feature: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": feature.get("id"),
        "name": feature.get("name"),
        "status": feature.get("status"),
    }


def build_migration_plan(
    repository: FlaskDataRepository,
    *,
    app_path: Path = DEFAULT_APP_PATH,
    timestamp: str | None = None,
) -> dict[str, Any]:
    canonical_features = canonical_risk_features_from_app(app_path)
    canonical = _canonical_by_name(canonical_features)
    timestamp = timestamp or now_str()

    current_features = repository.list_risk_features()
    by_name = {feature["name"]: deepcopy(feature) for feature in current_features}
    system_names = _system_names(canonical_features)

    conflicts: list[dict[str, Any]] = []
    update_candidates: list[dict[str, Any]] = []
    create_candidates: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    blocked_canonical_names: set[str] = set()
    planned_update_ids: set[int] = set()

    for legacy_name, canonical_name in LEGACY_TO_CANONICAL.items():
        legacy = by_name.get(legacy_name)
        canonical_existing = by_name.get(canonical_name)
        if legacy and canonical_existing and int(legacy["id"]) != int(canonical_existing["id"]):
            conflicts.append({
                "legacy_name": legacy_name,
                "legacy_id": legacy["id"],
                "canonical_name": canonical_name,
                "canonical_id": canonical_existing["id"],
                "action": "skipped",
            })
            blocked_canonical_names.add(canonical_name)
            continue

        current = legacy or canonical_existing
        if not current:
            continue

        desired = canonical[canonical_name]
        changes = _changed_fields(current, desired)
        if changes:
            fields = {
                **desired,
                "status": current.get("status", "active"),
                "updated_by": current.get("updated_by"),
                "updated_at": timestamp,
            }
            update_candidates.append({
                "id": current["id"],
                "from_name": current["name"],
                "to_name": canonical_name,
                "preserved_status": current.get("status", "active"),
                "preserved_updated_by": current.get("updated_by"),
                "fields": fields,
            })
            planned_update_ids.add(int(current["id"]))
        else:
            verified.append(_public_feature(current))

    for canonical_name, desired in canonical.items():
        if canonical_name in blocked_canonical_names:
            continue
        if canonical_name not in NEW_CANONICAL_FEATURES and canonical_name in LEGACY_TO_CANONICAL.values():
            continue

        current = by_name.get(canonical_name)
        if current:
            changes = _changed_fields(current, desired)
            if changes and int(current["id"]) not in planned_update_ids:
                fields = {
                    **desired,
                    "status": current.get("status", "active"),
                    "updated_by": current.get("updated_by"),
                    "updated_at": timestamp,
                }
                update_candidates.append({
                    "id": current["id"],
                    "from_name": current["name"],
                    "to_name": canonical_name,
                    "preserved_status": current.get("status", "active"),
                    "preserved_updated_by": current.get("updated_by"),
                    "fields": fields,
                })
                planned_update_ids.add(int(current["id"]))
            elif int(current["id"]) not in planned_update_ids:
                verified.append(_public_feature(current))
            continue

        create_candidates.append({
            "name": canonical_name,
            "fields": {
                **desired,
                "status": "active",
                "updated_by": None,
                "updated_at": timestamp,
            },
        })

    unchanged_custom_features = [
        _public_feature(feature)
        for feature in current_features
        if feature["name"] not in system_names
    ]
    final_expected_count = len(current_features) + len(create_candidates)

    return {
        "backend": repository.backend_name,
        "current_feature_count": len(current_features),
        "update_candidates": update_candidates,
        "create_candidates": create_candidates,
        "unchanged_custom_features": unchanged_custom_features,
        "conflicts": conflicts,
        "verified": verified,
        "final_expected_count": final_expected_count,
    }


def apply_migration_plan(repository: FlaskDataRepository, plan: dict[str, Any]) -> dict[str, Any]:
    applied_updates: list[dict[str, Any]] = []
    applied_creates: list[dict[str, Any]] = []

    for candidate in plan["update_candidates"]:
        updated = repository.update_risk_feature(int(candidate["id"]), candidate["fields"])
        if updated is None:
            raise RuntimeError(f"Risk feature disappeared before update: {candidate['id']}")
        applied_updates.append(_public_feature(updated))

    for candidate in plan["create_candidates"]:
        try:
            created = repository.create_risk_feature(candidate["fields"])
        except DuplicateRecordError as exc:
            raise RuntimeError(f"Risk feature already exists during create: {candidate['name']}") from exc
        applied_creates.append(_public_feature(created))

    return {"updates": applied_updates, "creates": applied_creates}


def migrate_risk_features_v2(
    repository: FlaskDataRepository,
    *,
    dry_run: bool = True,
    app_path: Path = DEFAULT_APP_PATH,
    timestamp: str | None = None,
) -> dict[str, Any]:
    plan = build_migration_plan(repository, app_path=app_path, timestamp=timestamp)
    report = {"mode": "dry-run" if dry_run else "execute", **plan}
    if dry_run:
        return report
    report["applied"] = apply_migration_plan(repository, plan)
    return report


def build_repository(args: argparse.Namespace) -> FlaskDataRepository:
    if args.backend == "sqlite":
        repository = SqliteFlaskDataRepository(Path(args.database))
    elif args.backend == "firestore":
        repository = FirestoreFlaskDataRepository(args.project)
    else:
        raise ValueError(f"Unsupported backend: {args.backend}")
    repository.initialize()
    return repository


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Idempotent, non-destructive Risk Features v2 migration."
    )
    parser.add_argument("--backend", choices=("sqlite", "firestore"), default="sqlite")
    parser.add_argument("--database", default="financial_risk.db", help="SQLite database path")
    parser.add_argument("--project", default=None, help="Google Cloud project ID for Firestore")
    parser.add_argument("--app", default=str(DEFAULT_APP_PATH), help="Path to app.py canonical seed source")
    parser.add_argument("--execute", action="store_true", help="Write changes; default is dry-run")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing data")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dry_run = not args.execute
    repository = build_repository(args)
    report = migrate_risk_features_v2(repository, dry_run=dry_run, app_path=Path(args.app))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
