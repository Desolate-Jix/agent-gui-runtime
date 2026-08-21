from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.agent.desktop_backend import BackendDispatchReceipt
from app.agent.runtime_contracts import RuntimeResultReceiptV1


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _workflow() -> dict[str, object]:
    return {
        "workflow_id": "workflow.seek.portfolio",
        "asset_id": "asset.seek.portfolio",
        "asset_content_sha256": SHA_A,
        "source_workflow_sha256": SHA_B,
        "reviewed_revision_hash": SHA_C,
    }


def _receipt_payload(outcome: str = "DISPATCHED") -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "runtime_result_receipt_v1",
        "receipt_id": "receipt:runtime:1",
        "issued_at": "2026-08-22T01:02:03Z",
        "session_id": "session-1",
        "observation_id": "observation-1",
        "intent_id": "intent.open-detail",
        "workflow": _workflow(),
        "action": {
            "action_id": "transition.open-detail",
            "semantic_action": "open_detail",
        },
        "outcome": "DISPATCHED",
        "reason_code": "verification_pending",
        "attempt_count": 1,
        "gate_status": "allowed",
        "dispatch_status": "dispatched",
        "effect_status": "not_evaluated",
        "destination_status": "not_evaluated",
        "evidence": {
            "state_resolution_ref": "state-resolution:1",
            "selection_ref": "selection:1",
            "candidate_ref": "candidate:1",
            "gate_decision_ref": "gate:1",
            "backend_receipt_ref": "backend-receipt:1",
            "verification_ref": None,
            "trace_refs": ["trace:1"],
        },
        "next_observation_id": None,
        "safe_stop": {
            "required": True,
            "reason_code": "verification_pending",
        },
        "artifact_is_authorization": False,
    }
    if outcome == "BLOCKED":
        payload.update(
            outcome="BLOCKED",
            reason_code="pre_click_rejected",
            attempt_count=0,
            gate_status="blocked",
            dispatch_status="not_started",
        )
        payload["evidence"]["backend_receipt_ref"] = None
        payload["safe_stop"] = {
            "required": True,
            "reason_code": "pre_click_rejected",
        }
    elif outcome == "EXECUTION_FAILED":
        payload.update(
            outcome="EXECUTION_FAILED",
            reason_code="backend_failed",
            dispatch_status="not_started",
        )
        payload["safe_stop"] = {
            "required": True,
            "reason_code": "backend_failed",
        }
    elif outcome == "INDETERMINATE":
        payload.update(
            outcome="INDETERMINATE",
            reason_code="backend_result_lost",
            dispatch_status="indeterminate",
            effect_status="indeterminate",
            destination_status="indeterminate",
        )
        payload["safe_stop"] = {
            "required": True,
            "reason_code": "backend_result_lost",
        }
    return payload


def _receipt(outcome: str = "DISPATCHED") -> RuntimeResultReceiptV1:
    return RuntimeResultReceiptV1.model_validate(_receipt_payload(outcome))


def _backend(
    status: str = "dispatched",
    reason_code: str = "none",
) -> BackendDispatchReceipt:
    return BackendDispatchReceipt(
        receipt_ref="backend-receipt:1",
        status=status,
        reason_code=reason_code,
    )


@pytest.mark.parametrize(
    "outcome,backend",
    [
        ("BLOCKED", None),
        ("DISPATCHED", _backend()),
    ],
)
def test_store_reloads_validated_receipt_after_restart(
    tmp_path: Path,
    outcome: str,
    backend: BackendDispatchReceipt | None,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    first = RuntimeReceiptStore(project_root=tmp_path)
    ref = first.put(_receipt(outcome), backend_receipt=backend)

    restarted = RuntimeReceiptStore(project_root=tmp_path)
    record = restarted.get(ref)
    by_id = restarted.load_by_receipt_id(_receipt(outcome).receipt_id)

    assert record.runtime_receipt == _receipt(outcome)
    assert by_id == record
    assert record.backend_receipt == backend
    assert ref == {
        "receipt_id": _receipt(outcome).receipt_id,
        "content_sha256": record.content_sha256,
    }
    pointer_name = hashlib.sha256(_receipt(outcome).receipt_id.encode("utf-8")).hexdigest()
    assert (restarted.root / "receipt-ids" / f"{pointer_name}.json").is_file()
    assert not (restarted.root / "receipt-ids" / "receipt:runtime:1.json").exists()


@pytest.mark.parametrize(
    "outcome,backend,match",
    [
        ("DISPATCHED", None, "backend receipt is required"),
        ("BLOCKED", _backend(), "cannot have a backend receipt"),
        (
            "DISPATCHED",
            BackendDispatchReceipt(
                receipt_ref="backend-receipt:wrong",
                status="dispatched",
                reason_code="none",
            ),
            "reference mismatch",
        ),
        ("DISPATCHED", _backend("not_started", "backend_failed"), "status mismatch"),
        ("DISPATCHED", _backend("dispatched", "backend_failed"), "reason mismatch"),
        ("EXECUTION_FAILED", _backend(), "status mismatch"),
        ("EXECUTION_FAILED", _backend("not_started", "none"), "reason mismatch"),
        ("INDETERMINATE", _backend(), "status mismatch"),
    ],
)
def test_store_rejects_missing_or_mismatched_backend_receipt(
    tmp_path: Path,
    outcome: str,
    backend: BackendDispatchReceipt | None,
    match: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    with pytest.raises(RuntimeReceiptStoreError, match=match):
        RuntimeReceiptStore(project_root=tmp_path).put(
            _receipt(outcome),
            backend_receipt=backend,
        )


@pytest.mark.parametrize(
    "outcome,backend",
    [
        ("EXECUTION_FAILED", _backend("not_started", "backend_failed")),
        ("INDETERMINATE", _backend("indeterminate", "backend_result_lost")),
    ],
)
def test_store_accepts_backend_failure_and_indeterminate_pairings(
    tmp_path: Path,
    outcome: str,
    backend: BackendDispatchReceipt,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeReceiptStore(project_root=tmp_path)
    record = store.get(store.put(_receipt(outcome), backend_receipt=backend))

    assert record.backend_receipt == backend


def test_execution_failed_backend_not_started_reason_remains_reloadable(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    payload = _receipt_payload("EXECUTION_FAILED")
    payload["reason_code"] = "backend_not_started"
    payload["safe_stop"] = {
        "required": True,
        "reason_code": "backend_not_started",
    }
    receipt = RuntimeResultReceiptV1.model_validate(payload)
    backend = _backend("not_started", "backend_failed")
    store = RuntimeReceiptStore(project_root=tmp_path)

    record = store.get(store.put(receipt, backend_receipt=backend))

    assert record.runtime_receipt.reason_code == "backend_not_started"
    assert record.backend_receipt == backend


def test_store_rejects_non_backend_receipt_object_with_structured_error(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    with pytest.raises(RuntimeReceiptStoreError, match="invalid backend receipt"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            _receipt(),
            backend_receipt={"receipt_ref": "backend-receipt:1"},  # type: ignore[arg-type]
        )


def test_same_receipt_is_idempotent_but_conflicting_identity_never_overwrites(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    first = store.put(_receipt(), backend_receipt=_backend())
    assert store.put(_receipt(), backend_receipt=_backend()) == first
    pointer_path = store.root / "receipt-ids" / (
        hashlib.sha256(_receipt().receipt_id.encode("utf-8")).hexdigest() + ".json"
    )
    committed_pointer = pointer_path.read_bytes()

    changed = _receipt_payload()
    changed["issued_at"] = "2026-08-22T01:02:04Z"
    with pytest.raises(RuntimeReceiptStoreError, match="receipt identity conflict"):
        store.put(RuntimeResultReceiptV1.model_validate(changed), backend_receipt=_backend())

    assert pointer_path.read_bytes() == committed_pointer
    assert store.get(first).runtime_receipt.issued_at == "2026-08-22T01:02:03Z"


@pytest.mark.parametrize("target", ["object", "pointer"])
def test_store_rejects_tampered_object_or_pointer(tmp_path: Path, target: str) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    ref = store.put(_receipt(), backend_receipt=_backend())
    if target == "object":
        path = store.root / "objects" / f'{ref["content_sha256"]}.json'
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        pointer_name = hashlib.sha256(ref["receipt_id"].encode("utf-8")).hexdigest()
        path = store.root / "receipt-ids" / f"{pointer_name}.json"
        pointer = json.loads(path.read_text(encoding="utf-8"))
        pointer["content_sha256"] = "f" * 64
        path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(RuntimeReceiptStoreError):
        store.load_by_receipt_id(ref["receipt_id"])


def test_exact_get_requires_matching_canonical_receipt_identity_pointer(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    ref = store.put(_receipt(), backend_receipt=_backend())
    pointer_path = store._pointer_path(ref["receipt_id"])
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["content_sha256"] = "f" * 64
    pointer_path.write_text(
        json.dumps(
            pointer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeReceiptStoreError, match="pointer|identity"):
        store.get(ref)


def test_failed_partial_object_write_is_cleaned_and_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)

    def fail_after_partial_write(path: Path, contents: bytes) -> None:
        path.write_bytes(contents[:1])
        raise OSError("injected partial write")

    monkeypatch.setattr(store, "_write_temp", fail_after_partial_write)
    with pytest.raises(RuntimeReceiptStoreError, match="write failed"):
        store.put(_receipt(), backend_receipt=_backend())
    assert list(store.root.rglob("*.tmp")) == []
    assert list((store.root / "receipt-ids").glob("*.json")) == []

    monkeypatch.undo()
    ref = store.put(_receipt(), backend_receipt=_backend())
    assert store.get(ref).runtime_receipt.receipt_id == _receipt().receipt_id


def test_orphan_object_after_pointer_failure_is_reused_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    original_publish = store._publish_temp
    publish_count = 0

    def fail_pointer_publish(temporary: Path, target: Path, contents: bytes) -> bool:
        nonlocal publish_count
        publish_count += 1
        if target.parent.name == "receipt-ids":
            raise OSError("injected pointer failure")
        return original_publish(temporary, target, contents)

    monkeypatch.setattr(store, "_publish_temp", fail_pointer_publish)
    with pytest.raises(RuntimeReceiptStoreError, match="write failed"):
        store.put(_receipt(), backend_receipt=_backend())
    assert len(list((store.root / "objects").glob("*.json"))) == 1
    assert list((store.root / "receipt-ids").glob("*.json")) == []

    monkeypatch.undo()
    ref = store.put(_receipt(), backend_receipt=_backend())
    assert store.get(ref).backend_receipt == _backend()
    assert publish_count == 2


def test_durable_publish_failure_before_identity_commit_keeps_orphan_nonauthoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    original_publish = store._durable_publish_no_replace

    def fail_identity_commit(temporary: Path, target: Path) -> None:
        if target.parent == store.receipt_ids_root:
            raise OSError("injected durable identity commit failure")
        original_publish(temporary, target)

    monkeypatch.setattr(store, "_durable_publish_no_replace", fail_identity_commit)
    with pytest.raises(RuntimeReceiptStoreError, match="write failed"):
        store.put(_receipt(), backend_receipt=_backend())

    objects = list(store.objects_root.glob("*.json"))
    assert len(objects) == 1
    assert list(store.receipt_ids_root.glob("*.json")) == []
    with pytest.raises(RuntimeReceiptStoreError):
        store.load_by_receipt_id(_receipt().receipt_id)
    exact_ref = {
        "receipt_id": _receipt().receipt_id,
        "content_sha256": objects[0].stem,
    }
    with pytest.raises(RuntimeReceiptStoreError, match="pointer|identity"):
        store.get(exact_ref)

    monkeypatch.undo()
    committed_ref = store.put(_receipt(), backend_receipt=_backend())
    assert committed_ref == exact_ref
    assert store.get(committed_ref).runtime_receipt == _receipt()


@pytest.mark.parametrize(
    "use_windows,expected_helper",
    [
        (True, "windows"),
        (False, "posix"),
    ],
)
def test_durable_publish_selects_platform_specific_no_replace_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_windows: bool,
    expected_helper: str,
) -> None:
    import app.agent.runtime_receipt_store as receipt_store_module
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeReceiptStore(project_root=tmp_path)
    calls: list[str] = []

    def publish(label: str, temporary: Path, target: Path) -> None:
        calls.append(label)
        # 测试替身仍使用 no-replace hard link，保留并发冲突语义。
        os.link(temporary, target)

    monkeypatch.setattr(receipt_store_module, "_IS_WINDOWS", use_windows)
    monkeypatch.setattr(
        receipt_store_module,
        "_publish_windows_no_replace_write_through",
        lambda temporary, target: publish("windows", temporary, target),
        raising=False,
    )
    monkeypatch.setattr(
        receipt_store_module,
        "_publish_posix_no_replace_durable",
        lambda temporary, target: publish("posix", temporary, target),
        raising=False,
    )

    store.put(_receipt(), backend_receipt=_backend())

    assert calls == [expected_helper, expected_helper]


def test_concurrent_identical_puts_converge(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeReceiptStore(project_root=tmp_path)
    barrier = Barrier(4)
    results: list[dict[str, str]] = []
    failures: list[BaseException] = []

    def put() -> None:
        try:
            barrier.wait()
            results.append(store.put(_receipt(), backend_receipt=_backend()))
        except BaseException as exc:
            failures.append(exc)

    threads = [Thread(target=put) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(results) == 4
    assert all(result == results[0] for result in results)
    assert len(list((store.root / "objects").glob("*.json"))) == 1
    assert len(list((store.root / "receipt-ids").glob("*.json"))) == 1


def test_concurrent_conflicting_receipt_id_has_one_winner(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    barrier = Barrier(2)
    results: list[dict[str, str]] = []
    failures: list[BaseException] = []
    payloads = [_receipt_payload(), deepcopy(_receipt_payload())]
    payloads[1]["issued_at"] = "2026-08-22T01:02:04Z"

    def put(payload: dict[str, object]) -> None:
        try:
            barrier.wait()
            results.append(
                store.put(
                    RuntimeResultReceiptV1.model_validate(payload),
                    backend_receipt=_backend(),
                )
            )
        except BaseException as exc:
            failures.append(exc)

    threads = [Thread(target=put, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeReceiptStoreError)
    assert "receipt identity conflict" in str(failures[0])
    assert store.get(results[0]).runtime_receipt.issued_at in {
        "2026-08-22T01:02:03Z",
        "2026-08-22T01:02:04Z",
    }


def test_store_rejects_symlink_redirection_outside_fixed_root(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    external = tmp_path / "external"
    external.mkdir()
    runtime_state = tmp_path / "runtime_state"
    runtime_state.mkdir()
    root = runtime_state / "runtime-receipts-v1"
    try:
        root.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(RuntimeReceiptStoreError, match="redirection|reparse"):
        RuntimeReceiptStore(project_root=tmp_path)
