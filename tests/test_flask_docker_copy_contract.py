"""Prevent Flask Cloud Run images from omitting imported route modules."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FlaskDockerCopyContractTests(unittest.TestCase):
    def test_all_imported_flask_route_modules_are_copied(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile.flask").read_text(encoding="utf-8")
        imports = set(re.findall(r"^from\s+([a-z_]+_routes)\s+import\s+", app, flags=re.MULTILINE))
        self.assertTrue(imports, "Expected app.py to register separate Flask route modules")
        copy_sources = set()
        for line in dockerfile.splitlines():
            if line.startswith("COPY "):
                parts = line.split()
                copy_sources.update(parts[1:-1])
        missing = sorted(f"{module}.py" for module in imports if f"{module}.py" not in copy_sources)
        self.assertFalse(missing, f"Dockerfile.flask does not copy required Flask modules: {missing}")


if __name__ == "__main__":
    unittest.main()
