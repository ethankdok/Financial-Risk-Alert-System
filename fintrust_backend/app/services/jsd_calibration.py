"""Versioned JSD calibration profiles and their repositories.

A profile is the validated, scoped form of a calibration result produced by the
teammate-owned research method. Thresholds are data loaded from a profile,
never constants in code. A profile applies only to an exact scope: ticker,
document type, language, extraction method, preprocessing version, method
version and calculator module hash. There is no industry-wide profile.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

PROFILE_SCHEMA = "fintrust.jsd_calibration_profile.v1"
FIRESTORE_COLLECTION = "shift_calibrations"  # teammate collection name; profiles are a superset of its fields


class ProfileScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(pattern=r"^\d{4,6}$")
    company: str = ""
    industry: str
    document_type: str
    language: str
    source_family: str


class ProfileMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method_version: str
    calculator_module_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_method: str
    preprocessing_version: str
    tokenizer: str
    tfidf: str
    jsd_log_base: int
    comparison: str
    minimum_history_pairs: int


class ProfileThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jsd_p90: float
    jsd_p95: float
    cosine_p10: float
    cosine_p05: float


class ProfileCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history_pair_count: int
    history_pairs: list[dict[str, Any]] = Field(default_factory=list)
    history_latest_period: str | None = None
    thresholds: ProfileThresholds | None = None
    calibrated_for_target: dict[str, str] | None = None


class JsdCalibrationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["fintrust.jsd_calibration_profile.v1"] = PROFILE_SCHEMA
    calibration_id: str
    scope: ProfileScope
    method: ProfileMethod
    calibration: ProfileCalibration
    decision_rule: dict[str, str]
    source_document_hashes: list[str]
    source_research_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: str
    imported_at: str | None = None
    status: Literal["active", "insufficient_history", "retired"]
    warnings: list[str] = Field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.status == "active" and self.calibration.thresholds is not None


def calibration_id_for(scope: ProfileScope, method: ProfileMethod, history_latest_period: str | None) -> str:
    """Deterministic id: the same scope, method and history window always map to one profile."""
    key = "|".join([
        scope.ticker, scope.document_type, scope.language, scope.source_family, method.method_version,
        method.calculator_module_sha256, method.extraction_method, method.preprocessing_version,
        history_latest_period or "none",
    ])
    return f"jsdcal-{scope.ticker}-{hashlib.sha256(key.encode()).hexdigest()[:20]}"


def _quarter_index(period: str) -> int:
    return int(period[:4]) * 4 + int(period[-1]) - 1


def matches(profile: JsdCalibrationProfile, *, ticker: str, document_type: str, language: str,
            extraction_method: str, preprocessing_version: str, method_version: str,
            calculator_module_sha256: str, target_period_1: str) -> bool:
    history_end = profile.calibration.history_latest_period
    return (
        profile.usable
        and profile.scope.ticker == ticker
        and profile.scope.document_type == document_type
        and profile.scope.language == language
        and profile.method.extraction_method == extraction_method
        and profile.method.preprocessing_version == preprocessing_version
        and profile.method.method_version == method_version
        and profile.method.calculator_module_sha256 == calculator_module_sha256
        # History must end before the target pair starts (no target leakage).
        and history_end is not None and _quarter_index(history_end) < _quarter_index(target_period_1)
    )


class JsdCalibrationRepository(Protocol):
    backend_name: str

    def list_profiles(self, ticker: str) -> list[JsdCalibrationProfile]: ...

    def find_matching_profile(self, **scope: Any) -> JsdCalibrationProfile | None: ...


class _MatchingMixin:
    def find_matching_profile(self, **scope: Any) -> JsdCalibrationProfile | None:
        candidates = [profile for profile in self.list_profiles(scope["ticker"]) if matches(profile, **scope)]
        if not candidates:
            return None
        # Most recent history window first (closest calibration to the target).
        return max(candidates, key=lambda profile: _quarter_index(profile.calibration.history_latest_period))


class JsonJsdCalibrationRepository(_MatchingMixin):
    """Directory of validated profile JSON files (local development and tests)."""

    backend_name = "json"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def list_profiles(self, ticker: str) -> list[JsdCalibrationProfile]:
        if not self.directory.is_dir():
            return []
        profiles = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                profile = JsdCalibrationProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue  # an invalid file is never used
            if profile.scope.ticker == ticker:
                profiles.append(profile)
        return profiles


class FirestoreJsdCalibrationRepository(_MatchingMixin):
    backend_name = "firestore"

    def __init__(self, project_id: str | None = None, client: Any | None = None) -> None:
        self._project_id = project_id
        self._client = client

    def _db(self) -> Any:
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=self._project_id) if self._project_id else firestore.Client()
        return self._client

    def list_profiles(self, ticker: str) -> list[JsdCalibrationProfile]:
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            documents = (self._db().collection(FIRESTORE_COLLECTION)
                         .where(filter=FieldFilter("schema_version", "==", PROFILE_SCHEMA))
                         .where(filter=FieldFilter("scope.ticker", "==", ticker)).stream())
        except Exception:
            return []
        profiles = []
        for document in documents:
            try:
                profiles.append(JsdCalibrationProfile.model_validate(firestore_to_profile(document.to_dict())))
            except Exception:
                continue
        return profiles


def profile_to_firestore(profile: JsdCalibrationProfile) -> dict[str, Any]:
    """Profile document; also carries the teammate collection's top-level keys."""
    data = profile.model_dump(mode="json")
    data.update(ticker=profile.scope.ticker, industry=profile.scope.industry)
    return data


def firestore_to_profile(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data)
    data.pop("ticker", None)
    data.pop("industry", None)
    return data


DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[1] / "calibration_profiles"


def build_jsd_calibration_repository() -> JsdCalibrationRepository:
    """JSD_CALIBRATION_BACKEND=json|firestore; defaults follow DATASTORE_BACKEND."""
    backend = os.getenv("JSD_CALIBRATION_BACKEND", "").strip().lower()
    if not backend:
        backend = "firestore" if os.getenv("DATASTORE_BACKEND", "").strip().lower() == "firestore" else "json"
    if backend == "firestore":
        return FirestoreJsdCalibrationRepository(os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    if backend != "json":
        raise ValueError(f"Unsupported JSD_CALIBRATION_BACKEND: {backend}")
    return JsonJsdCalibrationRepository(os.getenv("JSD_CALIBRATION_PROFILE_DIR", "") or DEFAULT_PROFILE_DIR)
