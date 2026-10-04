"""Storage for original resume files. Every file is encrypted before it is written.

FileStore is the interface. LocalEncryptedFileStore writes to local disk for development; an
object storage implementation can replace it later without changing callers. A ref looks like
"local:resumes/<org>/<resume>.pdf" and is what Resume.file_ref stores.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from strong_worker.inputs.settings import InputsSettings

log = logging.getLogger(__name__)

LOCAL_SCHEME = "local:"
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+)*$")


class StorageError(RuntimeError):
    pass


class FileStore(Protocol):
    async def put(self, key: str, data: bytes) -> str: ...

    async def get(self, ref: str) -> bytes: ...

    async def delete(self, ref: str) -> None: ...


class LocalEncryptedFileStore:
    def __init__(self, root: Path, key: bytes) -> None:
        self.root = root
        self._fernet = Fernet(key)

    async def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        token = self._fernet.encrypt(data)
        await asyncio.to_thread(_write, path, token)
        return LOCAL_SCHEME + key

    async def get(self, ref: str) -> bytes:
        token = await asyncio.to_thread(self._path(self._key(ref)).read_bytes)
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise StorageError(f"Cannot decrypt {ref}: wrong key or damaged file") from exc

    async def delete(self, ref: str) -> None:
        await asyncio.to_thread(self._path(self._key(ref)).unlink, True)

    @staticmethod
    def _key(ref: str) -> str:
        if not ref.startswith(LOCAL_SCHEME):
            raise StorageError(f"Not a local storage ref: {ref}")
        return ref.removeprefix(LOCAL_SCHEME)

    def _path(self, key: str) -> Path:
        if not _SAFE_KEY.match(key) or ".." in key:
            raise StorageError(f"Unsafe storage key: {key}")
        return self.root / (key + ".enc")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def build_file_store(settings: InputsSettings) -> LocalEncryptedFileStore:
    """Local encrypted store. The key comes from INPUTS_STORAGE_KEY. In dev and test only, a
    missing key is created once in the storage folder so the stack starts without setup."""
    root = settings.resolved_storage_dir
    if settings.inputs_storage_key is not None:
        key = settings.inputs_storage_key.get_secret_value().encode()
    elif settings.env in {"dev", "test"}:
        key_file = root / ".dev-storage-key"
        if not key_file.exists():
            root.mkdir(parents=True, exist_ok=True)
            key_file.write_bytes(Fernet.generate_key())
            log.warning("INPUTS_STORAGE_KEY is not set; created a dev-only key in %s", key_file)
        key = key_file.read_bytes().strip()
    else:
        raise StorageError("INPUTS_STORAGE_KEY must be set outside dev and test")
    return LocalEncryptedFileStore(root, key)
