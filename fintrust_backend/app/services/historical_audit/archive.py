"""Content-addressed raw evidence archive.

Original bytes are written once under their SHA-256 and never modified; every
retrieval appends a metadata line so repeated downloads of identical content
remain traceable without duplicating the artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_EXTENSIONS = {
    "xbrl_instance": ".xml",
    "inline_xbrl": ".html",
    "zip": ".zip",
    "pdf": ".pdf",
    "xls": ".xls",
    "html": ".html",
}


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ArchivedArtifact:
    content_hash: str
    path: Path
    relative_path: str
    newly_written: bool


class RawEvidenceArchive:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, ticker: str, period: str, content_hash: str, detected_format: str | None) -> Path:
        extension = _EXTENSIONS.get(detected_format or "", ".bin")
        return self.root / ticker / period / f"{content_hash}{extension}"

    def store(
        self,
        *,
        ticker: str,
        period: str,
        content: bytes,
        detected_format: str | None,
        retrieval: dict[str, Any],
    ) -> ArchivedArtifact:
        content_hash = sha256_hex(content)
        for segment in (ticker, *period.split("/")):
            if not segment or segment in {".", ".."} or "\\" in segment or ":" in segment:
                raise ValueError(f"Unsafe archive path segment: {segment!r}")
        path = self.path_for(ticker, period, content_hash, detected_format)
        if self.root.resolve() not in path.resolve().parents:
            raise ValueError("Archive path escapes the archive root.")
        path.parent.mkdir(parents=True, exist_ok=True)
        newly_written = False
        if path.exists():
            if sha256_hex(path.read_bytes()) != content_hash:
                raise RuntimeError(f"Archived artifact {path} no longer matches its SHA-256; refusing to overwrite evidence.")
        else:
            temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
            newly_written = True
        log_line = json.dumps({"content_hash": content_hash, **retrieval}, ensure_ascii=False, sort_keys=True, default=str)
        with path.with_name(f"{content_hash}.retrievals.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(log_line + "\n")
        return ArchivedArtifact(
            content_hash=content_hash,
            path=path,
            relative_path=path.relative_to(self.root).as_posix(),
            newly_written=newly_written,
        )

    def read(self, relative_path: str) -> bytes:
        path = (self.root / relative_path).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Archive path escapes the archive root.")
        content = path.read_bytes()
        if sha256_hex(content) != path.stem.split(".")[0]:
            raise RuntimeError(f"Archived artifact {relative_path} failed SHA-256 verification.")
        return content
