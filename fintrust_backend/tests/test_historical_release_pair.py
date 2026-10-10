"""F2: strict ZIP + audit sidecar release-pair publication (fixture tier, failure injection).

Two real strict packages are built from the synthetic evidence fixture (cutoffs 2016-11-14 and 2017-12-31) and
published into a temporary ``packages/`` directory. Failures are injected with ``mock`` into the publication's
renames; nothing outside the temporary directory is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from unittest import mock

from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder
from scripts import rebuild_historical_packages as release
from tests.test_historical_evidence import EvidenceTestCase

TARGET_NAME = "fintrust_1785_asof_2016-11-14.zip"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleasePairTests(EvidenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_all()
        self.packages = self.root / "packages"
        (self.packages / "previous").mkdir(parents=True)
        self.target = self.packages / TARGET_NAME
        self.audit = self.packages / "fintrust_1785_asof_2016-11-14.audit.json"
        # Release A is published through the normal path.
        zip_a, audit_a = self.stage("2016-11-14")
        release.publish_release(zip_a, audit_a, self.target)
        self.sha_a, self.audit_sha_a = _sha(self.target), _sha(self.audit)
        # Hash-qualified backups of A, as the rebuild script makes them.
        self.backups = {"zip": str(self.packages / "previous" / f"x.{self.sha_a[:12]}.zip"),
                        "audit": str(self.packages / "previous" / f"x.{self.audit_sha_a[:12]}.audit.json")}
        shutil.copy2(self.target, self.backups["zip"])
        shutil.copy2(self.audit, self.backups["audit"])
        # Release B is fully staged.
        self.zip_b, self.audit_b = self.stage("2017-12-31")
        self.sha_b = _sha(self.zip_b)
        self.assertNotEqual(self.sha_a, self.sha_b)

    def stage(self, as_of: str) -> tuple[Path, Path]:
        staged = self.packages / (TARGET_NAME.removesuffix(".zip") + ".new.zip")
        staged_audit = self.packages / (TARGET_NAME.removesuffix(".zip") + ".new.audit.json")
        ResearchPackageBuilder(self.repository, self.archive).build(
            PackageParameters("1785", 2013, 2014, as_of=as_of), staged, audit_path=staged_audit)
        return staged, release.stage_audit(staged_audit, self.target)

    def crash_on(self, failing_destination: Path):
        real_replace = os.replace

        def replace(src, dst):
            if Path(dst) == failing_destination:
                raise OSError("injected crash")
            return real_replace(src, dst)
        return mock.patch.object(release.os, "replace", side_effect=replace)

    def test_published_pair_is_valid(self) -> None:
        binding = release.verify_release_pair(self.target)
        self.assertEqual((binding["package_sha256"], binding["audit_sha256"]), (self.sha_a, self.audit_sha_a))

    def test_crash_between_zip_and_audit_is_detected_and_rolled_forward(self) -> None:
        with self.crash_on(self.audit), self.assertRaises(OSError):
            release.publish_release(self.zip_b, self.audit_b, self.target, self.backups)
        # Interrupted state: new ZIP, old sidecar -> not a valid release.
        self.assertEqual(_sha(self.target), self.sha_b)
        self.assertEqual(json.loads(self.audit.read_text(encoding="utf-8"))["package_sha256"], self.sha_a)
        with self.assertRaisesRegex(release.ReleaseError, "journal present"):
            release.verify_release_pair(self.target)
        result = release.recover_release(self.target)
        self.assertEqual((result["action"], result["package_sha256"]), ("rolled_forward", self.sha_b))
        self.assertFalse(self.zip_b.exists() or self.audit_b.exists())
        self.assertEqual(release.verify_release_pair(self.target)["package_sha256"], self.sha_b)

    def test_crash_before_zip_replacement_rolls_back(self) -> None:
        with self.crash_on(self.target), self.assertRaises(OSError):
            release.publish_release(self.zip_b, self.audit_b, self.target, self.backups)
        result = release.recover_release(self.target)
        self.assertEqual((result["action"], result["package_sha256"]), ("rolled_back", self.sha_a))
        self.assertEqual(_sha(self.audit), self.audit_sha_a)
        self.assertFalse(self.zip_b.exists() or self.audit_b.exists())

    def test_lost_staged_audit_restores_hash_qualified_backup(self) -> None:
        with self.crash_on(self.audit), self.assertRaises(OSError):
            release.publish_release(self.zip_b, self.audit_b, self.target, self.backups)
        self.audit_b.unlink()  # the staged sidecar is gone: roll forward impossible
        result = release.recover_release(self.target)
        self.assertEqual((result["action"], result["package_sha256"]), ("restored_from_backup", self.sha_a))
        self.assertEqual(_sha(self.audit), self.audit_sha_a)

    def test_unrecoverable_without_backup_fails_closed(self) -> None:
        with self.crash_on(self.audit), self.assertRaises(OSError):
            release.publish_release(self.zip_b, self.audit_b, self.target)  # no backups recorded
        self.audit_b.unlink()
        with self.assertRaisesRegex(release.ReleaseError, "cannot recover"):
            release.recover_release(self.target)
        with self.assertRaises(release.ReleaseError):
            release.verify_release_pair(self.target)

    def test_mismatched_pair_without_journal_is_never_accepted(self) -> None:
        shutil.copyfile(self.zip_b, self.target)  # e.g. a manual copy or a pre-journal crash
        with self.assertRaisesRegex(release.ReleaseError, "audit sidecar binds"):
            release.verify_release_pair(self.target)
        with self.assertRaises(release.ReleaseError):
            release.recover_release(self.target)
        self.assertEqual(release.main(["--check-release", "--packages", str(self.packages)]), 1)
        self.audit.unlink()
        with self.assertRaisesRegex(release.ReleaseError, "incomplete release pair"):
            release.verify_release_pair(self.target)

    def test_publish_refuses_an_unbound_staged_sidecar(self) -> None:
        audit = json.loads(self.audit_b.read_text(encoding="utf-8"))
        audit["package_sha256"] = self.sha_a
        self.audit_b.write_text(json.dumps(audit), encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "does not bind the staged ZIP"):
            release.publish_release(self.zip_b, self.audit_b, self.target)
        self.assertEqual(_sha(self.target), self.sha_a)
        self.assertEqual(release.main(["--check-release", "--packages", str(self.packages)]), 0)
