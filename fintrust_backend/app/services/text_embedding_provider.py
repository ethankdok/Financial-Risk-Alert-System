from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class EmbeddingProviderMetadata:
    provider: str
    model: str | None
    dimension: int | None
    status: str
    latency_ms: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: list[list[float]]
    metadata: EmbeddingProviderMetadata


@runtime_checkable
class TextEmbeddingProvider(Protocol):
    provider_name: str
    model: str

    @property
    def configured(self) -> bool: ...

    def health(self) -> dict[str, Any]: ...

    def embed_sentences(self, sentences: list[str]) -> EmbeddingBatchResult: ...


class DisabledTextEmbeddingProvider:
    provider_name = "disabled"
    model = ""

    @property
    def configured(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": False,
            "model": None,
            "dimension": None,
            "status": "not_configured",
        }

    def embed_sentences(self, sentences: list[str]) -> EmbeddingBatchResult:
        return EmbeddingBatchResult(
            vectors=[],
            metadata=EmbeddingProviderMetadata(
                provider=self.provider_name,
                model=None,
                dimension=None,
                status="not_configured",
            ),
        )


class GeminiTextEmbeddingProvider:
    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        client: Any | None = None,
        batch_size: int | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        raw_model = model if model is not None else os.getenv("TEXT_EMBEDDING_MODEL", "")
        self.model = (raw_model or "gemini-embedding-001").strip()
        raw_dimension = dimension if dimension is not None else os.getenv("TEXT_EMBEDDING_DIMENSION", "").strip()
        self.dimension = int(raw_dimension) if raw_dimension else None
        self.batch_size = batch_size or int(os.getenv("TEXT_EMBEDDING_BATCH_SIZE", "16"))
        self._client = client
        self._root_client: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self.model)

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": self.configured,
            "model": self.model,
            "dimension": self.dimension,
            "batch_size": self.batch_size,
            "status": "configured" if self.configured else "not_configured",
        }

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._root_client = genai.Client(api_key=self._api_key)
            self._client = self._root_client
        return self._client

    def _embed_chunk(self, chunk: list[str]) -> list[list[float]]:
        client = self._get_client()
        config: dict[str, Any] = {}
        if self.dimension is not None:
            config["output_dimensionality"] = self.dimension
        response = client.models.embed_content(
            model=self.model,
            contents=chunk,
            config=config or None,
        )
        embeddings = getattr(response, "embeddings", None)
        if embeddings is None and isinstance(response, dict):
            embeddings = response.get("embeddings")
        vectors: list[list[float]] = []
        for item in embeddings or []:
            values = getattr(item, "values", None)
            if values is None and isinstance(item, dict):
                values = item.get("values")
            vectors.append([float(value) for value in values or []])
        return vectors

    def embed_sentences(self, sentences: list[str]) -> EmbeddingBatchResult:
        clean = [sentence for sentence in sentences if sentence.strip()]
        if not self.configured:
            return EmbeddingBatchResult(
                vectors=[],
                metadata=EmbeddingProviderMetadata(
                    provider=self.provider_name,
                    model=self.model,
                    dimension=self.dimension,
                    status="not_configured",
                ),
            )
        started = time.perf_counter()
        try:
            vectors: list[list[float]] = []
            for index in range(0, len(clean), self.batch_size):
                vectors.extend(self._embed_chunk(clean[index : index + self.batch_size]))
            latency_ms = int((time.perf_counter() - started) * 1000)
            dimension = len(vectors[0]) if vectors else self.dimension
            return EmbeddingBatchResult(
                vectors=vectors,
                metadata=EmbeddingProviderMetadata(
                    provider=self.provider_name,
                    model=self.model,
                    dimension=dimension,
                    status="completed",
                    latency_ms=latency_ms,
                ),
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return EmbeddingBatchResult(
                vectors=[],
                metadata=EmbeddingProviderMetadata(
                    provider=self.provider_name,
                    model=self.model,
                    dimension=self.dimension,
                    status="failed",
                    latency_ms=latency_ms,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(dot / (left_norm * right_norm))


def create_text_embedding_provider() -> TextEmbeddingProvider:
    provider = os.getenv("TEXT_EMBEDDING_PROVIDER", "").strip().lower()
    if provider in {"", "disabled", "none", "prototype_baseline"}:
        return DisabledTextEmbeddingProvider()
    if provider == "gemini":
        return GeminiTextEmbeddingProvider()
    return DisabledTextEmbeddingProvider()
