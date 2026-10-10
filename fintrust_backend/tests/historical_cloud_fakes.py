"""In-memory MOCK clients for GCS and Firestore (Phase 1C tests).

They reproduce the semantics the historical cloud code relies on (create-only
preconditions, object metadata, FieldFilter queries) and support failure
injection. Passing tests against them are *mock* results, not cloud E2E.
"""

from __future__ import annotations

import copy
from typing import Any, Callable


class PreconditionFailed(Exception):
    code = 412


class AlreadyExists(Exception):
    code = 409


class ServiceUnavailable(Exception):
    code = 503


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket, self.name = bucket, name
        self.metadata: dict[str, str] | None = None
        self.size: int | None = None
        self.generation: int | None = None

    def upload_from_string(self, data: bytes, content_type: str, timeout: float, if_generation_match: int | None = None):
        self.bucket.client.calls.append(("upload", self.name))
        if self.bucket.client.fail_upload and self.bucket.client.fail_upload(self.name):
            raise ServiceUnavailable("injected upload interruption")
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise PreconditionFailed(self.name)
        self.bucket.objects[self.name] = {"data": bytes(data), "metadata": dict(self.metadata or {}),
                                          "content_type": content_type, "generation": len(self.bucket.objects) + 1}

    def download_as_bytes(self, timeout: float) -> bytes:
        stored = self.bucket.objects[self.name]
        data = stored["data"]
        if self.bucket.client.corrupt_download and self.bucket.client.corrupt_download(self.name):
            return data + b"corrupted"
        return data


class FakeBucket:
    def __init__(self, client: "FakeGcsClient", name: str) -> None:
        self.client, self.name = client, name
        self.objects: dict[str, dict[str, Any]] = client.buckets.setdefault(name, {})

    def get_blob(self, name: str, timeout: float = 0):
        stored = self.objects.get(name)
        if stored is None:
            return None
        blob = FakeBlob(self, name)
        blob.metadata, blob.size, blob.generation = dict(stored["metadata"]), len(stored["data"]), stored["generation"]
        return blob

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeGcsClient:
    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, dict[str, Any]]] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_upload: Callable[[str], bool] | None = None
        self.corrupt_download: Callable[[str], bool] | None = None

    def bucket(self, name: str) -> FakeBucket:
        return FakeBucket(self, name)


class _Snapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._data)


class FakeDocument:
    def __init__(self, store: "FakeFirestoreClient", collection: str, document_id: str) -> None:
        self.store, self.collection, self.id = store, collection, document_id

    def _check(self, operation: str) -> None:
        if self.store.fail_write and self.store.fail_write(self.collection, self.id, operation):
            raise ServiceUnavailable(f"injected Firestore {operation} failure")

    def create(self, data: dict[str, Any]) -> None:
        self._check("create")
        documents = self.store.data.setdefault(self.collection, {})
        if self.id in documents:
            raise AlreadyExists(self.id)
        documents[self.id] = copy.deepcopy(data)

    def set(self, data: dict[str, Any]) -> None:
        self._check("set")
        self.store.data.setdefault(self.collection, {})[self.id] = copy.deepcopy(data)

    def update(self, data: dict[str, Any]) -> None:
        self._check("update")
        self.store.data[self.collection][self.id].update(copy.deepcopy(data))

    def get(self) -> _Snapshot:
        return _Snapshot(self.store.data.get(self.collection, {}).get(self.id))


class FakeQuery:
    def __init__(self, store: "FakeFirestoreClient", collection: str, predicate=None) -> None:
        self.store, self.collection, self.predicate = store, collection, predicate

    def where(self, field_path=None, op_string=None, value=None, *, filter=None) -> "FakeQuery":
        if filter is not None:
            field_path, op_string, value = filter.field_path, filter.op_string, filter.value
        assert op_string == "=="
        return FakeQuery(self.store, self.collection, lambda doc: doc.get(field_path) == value)

    def stream(self):
        for document_id, data in sorted(self.store.data.get(self.collection, {}).items()):
            if self.predicate is None or self.predicate(data):
                yield FakeDocument(self.store, self.collection, document_id).get()


class FakeCollection(FakeQuery):
    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self.store, self.collection, document_id)


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {}
        self.fail_write: Callable[[str, str, str], bool] | None = None

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, name)
