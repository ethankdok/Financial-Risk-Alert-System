"""Managed identity regression: simulated verified token claims; no external account or Firestore writes."""
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from flask_data_repository import SqliteFlaskDataRepository, DuplicateRecordError
from member_services import MemberAuthService

class ManagedAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = SqliteFlaskDataRepository(Path(self.tmp.name)/"members.sqlite")
        self.repo.initialize()
        self.service = MemberAuthService(self.repo, app_env="production")
        self.env = patch.dict(os.environ, {"FIREBASE_PROJECT_ID": "test-project"})
        self.env.start()
        self.claims = {"sub":"uid-1","email":"user@example.test","name":"Original",
                       "email_verified":True,"iss":"https://securetoken.google.com/test-project",
                       "aud":"test-project","firebase":{"sign_in_provider":"google.com"}}
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    def login(self, **changes):
        with patch("google.oauth2.id_token.verify_firebase_token", return_value={**self.claims, **changes}):
            return self.service.login_firebase_token("fixture-token")
    def test_same_uid_both_methods_preserve_profile(self):
        a=self.login()
        self.repo.update_member(a["uid"], {"display_name":"Custom"})
        b=self.login(firebase={"sign_in_provider":"password"},name="Changed")
        self.assertEqual(b["uid"],a["uid"])
        self.assertEqual(b["display_name"],"Custom")
        self.assertEqual(len(self.repo.list_members()),1)
    def test_unverified_email_refused(self):
        with self.assertRaises(PermissionError): self.login(email_verified=False)
        self.assertEqual(self.repo.list_members(),[])
    def test_wrong_provider_and_issuer_refused(self):
        with self.assertRaises(PermissionError): self.login(firebase={"sign_in_provider":"anonymous"})
        with self.assertRaises(ValueError): self.login(iss="wrong")
        with self.assertRaises(ValueError): self.login(aud="wrong")
    def test_disabled_and_conflicting_uid_refused(self):
        self.login()
        with self.assertRaises(DuplicateRecordError): self.login(sub="uid-2")
        self.repo.update_member("uid-1", {"account_status":"disabled"})
        with self.assertRaises(PermissionError): self.login()
    def test_local_auth_disabled_in_production(self):
        self.assertFalse(self.service.local_password_enabled())
        with self.assertRaises(RuntimeError): self.service.register_local(email="x@y.test",password="12345678",display_name="X")
