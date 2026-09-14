from __future__ import annotations

from copy import deepcopy
import unittest

from scripts.migrate_risk_features_v2 import (
    LEGACY_TO_CANONICAL,
    canonical_risk_features_from_app,
    migrate_risk_features_v2,
)


class FakeRiskFeatureRepository:
    backend_name = "fake"

    def __init__(self, rows):
        self.rows = [deepcopy(row) for row in rows]
        self.updates = []
        self.creates = []

    def list_risk_features(self, *, active_only: bool = False):
        rows = [deepcopy(row) for row in self.rows]
        if active_only:
            rows = [row for row in rows if row.get("status") == "active"]
        rows.sort(key=lambda row: int(row["id"]), reverse=True)
        return rows

    def update_risk_feature(self, feature_id: int, fields):
        for row in self.rows:
            if int(row["id"]) == int(feature_id):
                row.update(deepcopy(fields))
                row["id"] = feature_id
                self.updates.append((feature_id, deepcopy(fields)))
                return deepcopy(row)
        return None

    def create_risk_feature(self, payload):
        next_id = max((int(row["id"]) for row in self.rows), default=0) + 1
        row = {**deepcopy(payload), "id": next_id}
        self.rows.append(row)
        self.creates.append(deepcopy(row))
        return deepcopy(row)


CANONICAL = canonical_risk_features_from_app()
CANONICAL_BY_NAME = {feature["name"]: feature for feature in CANONICAL}
LEGACY_NAMES = list(LEGACY_TO_CANONICAL)


def legacy_feature(feature_id: int, name: str, *, status: str = "active", updated_by=7):
    return {
        "id": feature_id,
        "name": name,
        "dimension": "legacy dimension",
        "weight": 1,
        "keywords": ["legacy keyword"],
        "definition": "legacy definition",
        "explain": "legacy explain",
        "status": status,
        "updated_by": updated_by,
        "updated_at": "old-time",
    }


class RiskFeaturesV2MigrationTests(unittest.TestCase):
    def test_legacy_seven_system_features_upgrade_to_v2(self) -> None:
        rows = [
            legacy_feature(index + 1, name, status="inactive" if index == 2 else "active")
            for index, name in enumerate(LEGACY_NAMES)
        ]
        repo = FakeRiskFeatureRepository(rows)

        report = migrate_risk_features_v2(repo, dry_run=False, timestamp="new-time")
        by_name = {row["name"]: row for row in repo.rows}

        self.assertEqual(report["conflicts"], [])
        self.assertEqual(len(report["update_candidates"]), 7)
        for legacy_name, canonical_name in LEGACY_TO_CANONICAL.items():
            with self.subTest(legacy_name=legacy_name):
                upgraded = by_name[canonical_name]
                desired = CANONICAL_BY_NAME[canonical_name]
                self.assertEqual(upgraded["id"], rows[LEGACY_NAMES.index(legacy_name)]["id"])
                self.assertEqual(upgraded["dimension"], desired["dimension"])
                self.assertEqual(upgraded["weight"], desired["weight"])
                self.assertEqual(upgraded["keywords"], desired["keywords"])
                self.assertEqual(upgraded["definition"], desired["definition"])
                self.assertEqual(upgraded["explain"], desired["explain"])
                self.assertEqual(upgraded["updated_by"], 7)
                self.assertEqual(upgraded["updated_at"], "new-time")

        self.assertEqual(by_name["來源不可驗證"]["status"], "inactive")

    def test_missing_eighth_feature_is_created_once_and_rerun_is_idempotent(self) -> None:
        rows = [
            {
                **deepcopy(CANONICAL_BY_NAME[canonical_name]),
                "id": index + 1,
                "status": "active",
                "updated_by": 3,
                "updated_at": "existing",
            }
            for index, canonical_name in enumerate(LEGACY_TO_CANONICAL.values())
        ]
        repo = FakeRiskFeatureRepository(rows)

        first = migrate_risk_features_v2(repo, dry_run=False, timestamp="first")
        second = migrate_risk_features_v2(repo, dry_run=False, timestamp="second")

        social_rows = [
            row for row in repo.rows
            if row["name"] == "社會認同／從眾訴求"
        ]
        self.assertEqual(len(social_rows), 1)
        self.assertEqual(first["create_candidates"][0]["name"], "社會認同／從眾訴求")
        self.assertEqual(second["create_candidates"], [])
        self.assertEqual(second["update_candidates"], [])

    def test_custom_feature_is_preserved_without_mutation(self) -> None:
        custom = legacy_feature(99, "管理員自訂特徵", status="inactive", updated_by=12)
        repo = FakeRiskFeatureRepository([
            custom,
            {
                **deepcopy(CANONICAL_BY_NAME["社會認同／從眾訴求"]),
                "id": 100,
                "status": "active",
                "updated_by": 1,
                "updated_at": "existing",
            },
        ])

        report = migrate_risk_features_v2(repo, dry_run=False, timestamp="new-time")

        self.assertIn({"id": 99, "name": "管理員自訂特徵", "status": "inactive"}, report["unchanged_custom_features"])
        self.assertEqual(repo.rows[0], custom)

    def test_legacy_and_canonical_collision_reports_conflict_and_skips_pair(self) -> None:
        repo = FakeRiskFeatureRepository([
            legacy_feature(1, "保證報酬", status="inactive"),
            {
                **deepcopy(CANONICAL_BY_NAME["保證報酬／低風險高報酬"]),
                "id": 2,
                "status": "active",
                "updated_by": 8,
                "updated_at": "existing",
            },
        ])
        before = deepcopy(repo.rows)

        report = migrate_risk_features_v2(repo, dry_run=False, timestamp="new-time")

        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["conflicts"][0]["legacy_name"], "保證報酬")
        self.assertEqual(repo.rows[0], before[0])
        self.assertEqual(repo.rows[1], before[1])
        self.assertFalse(any(update[0] in {1, 2} for update in repo.updates))

    def test_exact_canonical_feature_is_not_duplicated(self) -> None:
        repo = FakeRiskFeatureRepository([
            {
                **deepcopy(CANONICAL_BY_NAME["社會認同／從眾訴求"]),
                "id": 1,
                "status": "active",
                "updated_by": 4,
                "updated_at": "existing",
            }
        ])

        report = migrate_risk_features_v2(repo, dry_run=False, timestamp="new-time")

        self.assertEqual(report["create_candidates"], [])
        self.assertEqual(len([row for row in repo.rows if row["name"] == "社會認同／從眾訴求"]), 1)

    def test_dry_run_does_not_write_datastore(self) -> None:
        rows = [legacy_feature(index + 1, name) for index, name in enumerate(LEGACY_NAMES)]
        repo = FakeRiskFeatureRepository(rows)
        before = deepcopy(repo.rows)

        report = migrate_risk_features_v2(repo, dry_run=True, timestamp="dry")

        self.assertEqual(len(report["update_candidates"]), 7)
        self.assertEqual(len(report["create_candidates"]), 1)
        self.assertEqual(repo.rows, before)
        self.assertEqual(repo.updates, [])
        self.assertEqual(repo.creates, [])


if __name__ == "__main__":
    unittest.main()
