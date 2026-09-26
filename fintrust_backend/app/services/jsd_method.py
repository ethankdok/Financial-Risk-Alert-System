"""Thin loader for the teammate-owned JSD / cosine calculator (Method A).

The calculator is the shared ``data_shift.py`` module (earnings-call style
pairwise JSD with the original STRUX English tokenizer and per-pair TF-IDF
cosine). It is imported, never copied or edited. The module's content hash is
checked against the frozen research reference so a profile calibrated with one
calculator version is never evaluated with another.

Only ``calculate_jsd``, ``calculate_cosine_similarity`` and
``check_data_quality`` are used. The legacy STRUX runtime constants and
``determine_drift_level`` in the same module are never called by the official
bridge.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

# Frozen research reference (origin/feature/tsmc-quarterly-corpus).
METHOD_VERSION = "earnings-en-full-pairwise-tfidf-v1"
SOURCE_RESEARCH_COMMIT = "5b914937dc3cb2294851e0386c67270d20547e7e"
# SHA-256 of data_shift.py at the reference commit, with line endings normalized to LF.
REFERENCE_MODULE_SHA256 = "aa94cf9ed19bcd30ad0666ecddf3c7c5ea10a17868f66bf389278a649f86318b"
TOKENIZER = "Original STRUX English tokenizer (data_shift.tokenize)"
TFIDF = "TF-IDF fit independently on each pair (data_shift.calculate_cosine_similarity)"
JSD_LOG_BASE = 2


class MethodUnavailable(RuntimeError):
    """The shared calculator cannot be loaded or differs from the frozen reference."""


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _candidate_paths() -> list[Path]:
    configured = os.getenv("JSD_METHOD_MODULE_PATH", "").strip()
    here = Path(__file__).resolve()
    paths = [Path(configured)] if configured else []
    # Repository root in development; /app next to the FastAPI app in the container.
    paths += [here.parents[3] / "data_shift.py", here.parents[2] / "data_shift.py"]
    return paths


@dataclass(frozen=True)
class JsdCalculator:
    module: ModuleType
    module_sha256: str

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "method_version": METHOD_VERSION,
            "calculator_module_sha256": self.module_sha256,
            "source_research_commit": SOURCE_RESEARCH_COMMIT,
            "tokenizer": TOKENIZER,
            "tfidf": TFIDF,
            "jsd_log_base": JSD_LOG_BASE,
        }

    def data_quality(self, text_1: str, text_2: str) -> dict[str, Any]:
        return self.module.check_data_quality(text_1, text_2)

    def metrics(self, text_1: str, text_2: str) -> dict[str, float]:
        return {
            "jsd": round(float(self.module.calculate_jsd(text_1, text_2)), 6),
            "cosine_similarity": round(float(self.module.calculate_cosine_similarity(text_1, text_2)), 6),
        }


_CACHE: dict[str, JsdCalculator] = {}


def load_calculator(path: Path | None = None) -> JsdCalculator:
    candidates = [path] if path else _candidate_paths()
    module_path = next((item for item in candidates if item and item.is_file()), None)
    if module_path is None:
        raise MethodUnavailable("data_shift.py (JSD method module) was not found")
    digest = normalized_sha256(module_path)
    if digest != REFERENCE_MODULE_SHA256:
        raise MethodUnavailable("JSD method module differs from the frozen research reference")
    key = str(module_path.resolve())
    if key not in _CACHE:
        spec = importlib.util.spec_from_file_location("fintrust_jsd_method_module", module_path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ImportError as exc:
            raise MethodUnavailable(f"JSD method dependencies missing: {exc.name}") from exc
        sys.modules.setdefault("fintrust_jsd_method_module", module)
        _CACHE[key] = JsdCalculator(module=module, module_sha256=digest)
    return _CACHE[key]
