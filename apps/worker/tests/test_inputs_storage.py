"""Original resume files are stored encrypted through the storage interface."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from strong_worker.inputs.settings import InputsSettings
from strong_worker.inputs.storage import (
    LocalEncryptedFileStore,
    StorageError,
    build_file_store,
)

SECRET = b"Avery Quinlan, 555-0100, Senior Software Engineer"


async def test_round_trip_and_encrypted_at_rest(store: LocalEncryptedFileStore) -> None:
    ref = await store.put("resumes/org-1/res-1.pdf", SECRET)
    assert ref == "local:resumes/org-1/res-1.pdf"
    on_disk = (store.root / "resumes/org-1/res-1.pdf.enc").read_bytes()
    assert SECRET not in on_disk
    assert b"Avery" not in on_disk
    assert await store.get(ref) == SECRET

    await store.delete(ref)
    assert not (store.root / "resumes/org-1/res-1.pdf.enc").exists()


async def test_wrong_key_cannot_read(tmp_path: Path) -> None:
    writer = LocalEncryptedFileStore(tmp_path, Fernet.generate_key())
    ref = await writer.put("resumes/a/b.txt", SECRET)
    reader = LocalEncryptedFileStore(tmp_path, Fernet.generate_key())
    with pytest.raises(StorageError, match="decrypt"):
        await reader.get(ref)


@pytest.mark.parametrize(
    "key", ["../escape.txt", "resumes/../../x", "/abs/path", "resumes//x", "resumes/a b"]
)
async def test_unsafe_keys_are_rejected(store: LocalEncryptedFileStore, key: str) -> None:
    with pytest.raises(StorageError):
        await store.put(key, b"x")


async def test_other_ref_schemes_are_rejected(store: LocalEncryptedFileStore) -> None:
    with pytest.raises(StorageError, match="Not a local"):
        await store.get("s3://bucket/key")


async def test_dev_creates_a_key_once(tmp_path: Path) -> None:
    settings = InputsSettings(env="dev", inputs_storage_dir=tmp_path, inputs_storage_key=None)
    first = build_file_store(settings)
    ref = await first.put("resumes/o/r.txt", SECRET)
    second = build_file_store(settings)
    assert await second.get(ref) == SECRET


def test_prod_requires_a_key(tmp_path: Path) -> None:
    settings = InputsSettings(env="prod", inputs_storage_dir=tmp_path, inputs_storage_key=None)
    with pytest.raises(StorageError, match="INPUTS_STORAGE_KEY"):
        build_file_store(settings)
    key = Fernet.generate_key().decode()
    keyed = InputsSettings(env="prod", inputs_storage_dir=tmp_path, inputs_storage_key=key)
    assert isinstance(build_file_store(keyed), LocalEncryptedFileStore)
