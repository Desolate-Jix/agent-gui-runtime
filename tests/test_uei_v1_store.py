from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from app.learn.recognition.uei.contracts import UEIValidationError
from tests.uei_v1_helpers import SHA


def minimal_artifact_ref() -> dict[str, object]:
    return {
        "contract_version": "artifact_ref_v1",
        "artifact_id": "artifact/1",
        "artifact_sha256": SHA,
        "media_type": "image/png",
        "byte_length": 1,
        "restricted": False,
        "content_sha256": SHA,
    }


def test_store_returns_verified_ref_and_records_instance_write_order(tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    store = UEIObjectStore(root=tmp_path / "objects")
    ref = store.put(seal_immutable(minimal_artifact_ref()))

    assert store.get(ref, contract_version="artifact_ref_v1")["artifact_id"] == ref["id"]
    assert store.write_order == ("artifact_ref_v1",)
    assert UEIObjectStore(root=tmp_path / "other").write_order == ()


@pytest.mark.parametrize("mutation", [
    lambda value: value.__setitem__("byte_length", 2),
    lambda value: value.__setitem__("content_sha256", "b" * 64),
])
def test_store_rejects_unverified_input_hash(mutation, tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    value = seal_immutable(minimal_artifact_ref())
    mutation(value)

    with pytest.raises(UEIValidationError):
        UEIObjectStore(root=tmp_path / "objects").put(value)


def test_store_rejects_tampered_bytes_hash_id_and_contract(tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    store = UEIObjectStore(root=tmp_path / "objects")
    ref = store.put(seal_immutable(minimal_artifact_ref()))
    path = tmp_path / "objects" / f'{ref["content_sha256"]}.json'
    original = path.read_bytes()

    path.write_bytes(original.replace(b'"artifact/1"', b'"artifact/x"'))
    with pytest.raises(UEIValidationError):
        store.get(ref, contract_version="artifact_ref_v1")
    path.write_bytes(original)

    with pytest.raises(UEIValidationError):
        store.get({"id": ref["id"], "content_sha256": "b" * 64}, contract_version="artifact_ref_v1")
    with pytest.raises(UEIValidationError):
        store.get({"id": "artifact/x", "content_sha256": ref["content_sha256"]}, contract_version="artifact_ref_v1")
    with pytest.raises(UEIValidationError):
        store.get(ref, contract_version="provider_manifest_v1")


def test_store_never_replaces_same_digest_with_different_bytes(tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    store = UEIObjectStore(root=tmp_path / "objects")
    value = seal_immutable(minimal_artifact_ref())
    digest = value["content_sha256"]
    conflicting = canonical_json_bytes({"different": True})
    path = store.root / f"{digest}.json"
    path.write_bytes(conflicting)

    with pytest.raises(UEIValidationError):
        store.put(value)

    assert path.read_bytes() == conflicting
    assert store.write_order == ()


def test_store_cleans_failed_temp_write_and_allows_retry(tmp_path: Path, monkeypatch):
    from app.learn.recognition.uei.store import UEIObjectStore

    store = UEIObjectStore(root=tmp_path / "objects")
    value = seal_immutable(minimal_artifact_ref())

    def fail_after_partial_write(path: Path, contents: bytes) -> None:
        path.write_bytes(contents[:1])
        raise OSError("injected partial write")

    monkeypatch.setattr(store, "_write_temp", fail_after_partial_write, raising=False)
    with pytest.raises(UEIValidationError):
        store.put(value)

    digest = value["content_sha256"]
    assert not (store.root / f"{digest}.json").exists()
    assert list(store.root.glob("*.tmp")) == []
    monkeypatch.undo()
    assert store.put(value)["content_sha256"] == digest


def test_store_accepts_concurrent_identical_puts(tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    store = UEIObjectStore(root=tmp_path / "objects")
    value = seal_immutable(minimal_artifact_ref())
    barrier = Barrier(2)
    results: list[dict[str, str]] = []
    failures: list[BaseException] = []

    def put_value() -> None:
        try:
            barrier.wait()
            results.append(store.put(value))
        except BaseException as error:
            failures.append(error)

    threads = [Thread(target=put_value), Thread(target=put_value)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert results == [results[0], results[0]]
    assert store.write_order == ("artifact_ref_v1",)


def test_store_rejects_non_directory_root_as_structured_error(tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    root = tmp_path / "not-a-directory"
    root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(UEIValidationError):
        UEIObjectStore(root=root)


def test_store_rejects_unhashable_contract_version_as_structured_error(tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    store = UEIObjectStore(root=tmp_path / "objects")
    with pytest.raises(UEIValidationError):
        store.get({"id": "artifact/1", "content_sha256": "a" * 64}, contract_version=[])  # type: ignore[arg-type]


def test_store_rejects_symlink_root_when_supported(tmp_path: Path):
    from app.learn.recognition.uei.store import UEIObjectStore

    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "linked-root"
    try:
        root.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink unsupported: {error}")

    with pytest.raises(UEIValidationError):
        UEIObjectStore(root=root)
