"""Private object storage. Files are never served from a public path: every download goes
through an authenticated API endpoint that checks workspace membership first.

P0 ships a local-disk backend (content-addressed by workspace/project/sha256). A Supabase
Storage backend can implement the same interface; it is not implemented yet (see README).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from app.core.config import get_settings


class LocalStorage:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or get_settings().storage_dir).resolve()

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root) + os.sep):
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)  # atomic
        return key

    def get(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()


def get_storage() -> LocalStorage:
    return LocalStorage()


def document_key(workspace_id: uuid.UUID, project_id: uuid.UUID, sha256: str, ext: str) -> str:
    return f"ws/{workspace_id}/projects/{project_id}/documents/{sha256}{ext}"


def export_key(workspace_id: uuid.UUID, project_id: uuid.UUID, export_id: uuid.UUID) -> str:
    return f"ws/{workspace_id}/projects/{project_id}/exports/{export_id}.pdf"
