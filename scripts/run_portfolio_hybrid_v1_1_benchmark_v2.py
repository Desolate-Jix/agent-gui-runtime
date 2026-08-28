from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterator, Mapping, Sequence
import uuid

from app.learn.hybrid.benchmark_v2_runtime import (
    get_production_benchmark_v2_runtime,
)


_LEDGER_CONTRACT = "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2"
_ATTEMPT_CONTRACT = "benchmark_v2_runner_attempt_ref_v1"
_ATTEMPT_PAYLOAD_CONTRACT = "benchmark_v2_runner_regression_attempt_payload_v1"
_CLEANUP_PAYLOAD_CONTRACT = "benchmark_v2_runner_cleanup_payload_v1"
_RESULT_PAYLOAD_CONTRACT = "benchmark_v2_runner_result_payload_v1"
_ACTUAL_RESULT_CONTRACT = "benchmark_v2_runner_actual_result_v2"
_PRE_RESULT_REF_CONTRACT = "benchmark_v2_runner_ledger_pre_result_ref_v1"
_CLEANUP_RECEIPT_CONTRACT = "benchmark_v2_attempt_cleanup_receipt_v1"
_ZERO_SHA256 = "0" * 64
_PROVIDERS = ("omni", "qwen", "vista")
_ZERO_COUNTS = {
    "service_operations": 0,
    "windows": 0,
    "providers": 0,
    "listeners": 0,
    "leases": 0,
}
_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_sha256(value: Mapping[str, object]) -> str:
    body = {name: deepcopy(item) for name, item in value.items() if name != "content_sha256"}
    return hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _seal(value: Mapping[str, object]) -> dict[str, object]:
    result = deepcopy(dict(value))
    result["content_sha256"] = _content_sha256(result)
    return result


def _sealed_mapping(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = deepcopy(dict(value))
    digest = result.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{name} content SHA is invalid")
    if _content_sha256(result) != digest:
        raise ValueError(f"{name} content SHA differs")
    return result


def _content_ref(value: object, *, name: str) -> dict[str, str]:
    sealed = _sealed_mapping(value, name=name)
    return {"content_sha256": str(sealed["content_sha256"])}


def _write_json(path: Path, value: Mapping[str, object], *, create_only: bool) -> None:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if create_only else "wb"
    with destination.open(mode) as stream:
        stream.write(_canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_json_create_or_identical(
    path: Path, value: Mapping[str, object]
) -> None:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = _canonical_bytes(value) + b"\n"
    try:
        with destination.open("xb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        with destination.open("r+b") as stream:
            if stream.read() != expected:
                raise ValueError(
                    f"existing {destination.name} differs from authoritative bytes"
                )
            stream.flush()
            os.fsync(stream.fileno())


def _file_ref(path: Path, value: Mapping[str, object]) -> dict[str, object]:
    resolved = Path(path).resolve()
    return {
        "path": str(resolved),
        "file_sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "content_sha256": str(value["content_sha256"]),
    }


def _read_ledger(path: Path) -> list[dict[str, object]]:
    ledger = Path(path).resolve()
    if not ledger.exists():
        return []
    ledger_bytes = ledger.read_bytes()
    if not ledger_bytes:
        return []
    if not ledger_bytes.endswith(b"\n"):
        raise ValueError("attempt ledger JSONL is torn or not canonical")
    raw_lines = ledger_bytes.split(b"\n")[:-1]
    if not raw_lines or any(not raw for raw in raw_lines):
        raise ValueError("attempt ledger JSONL is not canonical")
    result: list[dict[str, object]] = []
    previous = _ZERO_SHA256
    for sequence, raw in enumerate(raw_lines):
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("attempt ledger JSONL is not canonical") from error
        if (
            not isinstance(value, Mapping)
            or _canonical_bytes(value) != raw
            or set(value) != {"contract_version", "event", "event_sha256"}
            or value.get("contract_version") != _LEDGER_CONTRACT
        ):
            raise ValueError("attempt ledger envelope is invalid")
        event = value.get("event")
        if (
            not isinstance(event, Mapping)
            or set(event)
            != {
                "partition",
                "sequence",
                "event_type",
                "previous_envelope_sha256",
                "event_payload",
            }
            or event.get("partition") != "regression"
            or event.get("event_type")
            not in {"regression_attempt", "cleanup", "result"}
            or isinstance(event.get("sequence"), bool)
            or not isinstance(event.get("sequence"), int)
            or event.get("sequence") != sequence
            or event.get("previous_envelope_sha256") != previous
            or value.get("event_sha256")
            != hashlib.sha256(_canonical_bytes(event)).hexdigest()
        ):
            raise ValueError("attempt ledger hash chain is invalid")
        payload = event.get("event_payload")
        _validate_event_payload(payload, event_type=str(event["event_type"]))
        previous = hashlib.sha256(_canonical_bytes(value)).hexdigest()
        result.append(deepcopy(dict(value)))
    _validate_ledger_records(result, raw_lines=raw_lines)
    return result


def _validate_event_payload(value: object, *, event_type: str) -> dict[str, object]:
    payload = _sealed_mapping(value, name="attempt ledger event payload")
    if payload.get("artifact_is_authorization") is not False or payload.get(
        "execute_binding_enabled"
    ) is not False:
        raise ValueError("attempt ledger event payload safety differs")
    attempt = _validate_attempt_ref(payload.get("attempt_ref"))
    if event_type == "regression_attempt":
        expected = {
            "contract_version",
            "attempt_ref",
            "attempt_dir",
            "mode",
            "provider_id",
            "status",
            "output_ref",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        if (
            set(payload) != expected
            or payload.get("contract_version") != _ATTEMPT_PAYLOAD_CONTRACT
            or payload.get("status") not in {"opened", "body_complete"}
        ):
            raise ValueError("regression attempt payload is invalid")
        if payload["status"] == "opened" and payload.get("output_ref") is not None:
            raise ValueError("opened regression attempt already has output")
        if payload["status"] == "body_complete":
            _validate_output_ref(payload.get("output_ref"))
    elif event_type == "cleanup":
        expected = {
            "contract_version",
            "attempt_ref",
            "attempt_dir",
            "mode",
            "provider_id",
            "status",
            "cleanup_receipt_ref",
            "resource_counts",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        if (
            set(payload) != expected
            or payload.get("contract_version") != _CLEANUP_PAYLOAD_CONTRACT
            or payload.get("status") != "terminal"
            or payload.get("resource_counts") != _ZERO_COUNTS
            or not isinstance(payload.get("resource_counts"), Mapping)
            or any(
                isinstance(count, bool) or not isinstance(count, int) or count != 0
                for count in payload["resource_counts"].values()
            )
        ):
            raise ValueError("cleanup payload is invalid")
        _validate_output_ref(payload.get("cleanup_receipt_ref"))
    elif event_type == "result":
        expected = {
            "contract_version",
            "attempt_ref",
            "attempt_dir",
            "mode",
            "provider_id",
            "status",
            "output_ref",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        if (
            set(payload) != expected
            or payload.get("contract_version") != _RESULT_PAYLOAD_CONTRACT
            or payload.get("status") != "terminal"
        ):
            raise ValueError("result payload is invalid")
        _validate_output_ref(payload.get("output_ref"))
    else:
        raise ValueError("attempt ledger event type is invalid")
    if (
        payload.get("attempt_dir") != str(Path(str(payload.get("attempt_dir"))).resolve())
        or payload.get("mode") != attempt.get("mode")
        or payload.get("provider_id") != attempt.get("provider_id")
    ):
        raise ValueError("attempt ledger payload lineage differs")
    return payload


def _validate_attempt_ref(value: object) -> dict[str, object]:
    attempt = _sealed_mapping(value, name="attempt ref")
    expected = {
        "contract_version",
        "attempt_id",
        "partition",
        "mode",
        "provider_id",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        set(attempt) != expected
        or attempt.get("contract_version") != _ATTEMPT_CONTRACT
        or not isinstance(attempt.get("attempt_id"), str)
        or not str(attempt["attempt_id"]).startswith("attempt-")
        or attempt.get("partition") != "regression"
        or attempt.get("mode")
        not in {"actual_models", "cancel_probe", "timeout_probe"}
        or (
            attempt.get("mode") == "actual_models"
            and attempt.get("provider_id") is not None
        )
        or (
            attempt.get("mode") != "actual_models"
            and attempt.get("provider_id") not in _PROVIDERS
        )
        or attempt.get("artifact_is_authorization") is not False
        or attempt.get("execute_binding_enabled") is not False
    ):
        raise ValueError("attempt ledger attempt ref contract differs")
    return attempt


def _validate_output_ref(value: object) -> dict[str, object]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"path", "file_sha256", "content_sha256"}
        or value.get("path") != str(Path(str(value.get("path"))).resolve())
        or any(
            not isinstance(value.get(name), str) or len(str(value[name])) != 64
            for name in ("file_sha256", "content_sha256")
        )
    ):
        raise ValueError("attempt output ref is invalid")
    return deepcopy(dict(value))


def _read_exact_json_ref(
    value: object,
    *,
    expected_path: Path,
    name: str,
) -> dict[str, object]:
    reference = _validate_output_ref(value)
    resolved = Path(expected_path).resolve()
    if reference["path"] != str(resolved) or not resolved.is_file():
        raise ValueError(f"{name} does not reference the fixed file")
    sealed = _read_canonical_json_file(resolved, name=name)
    raw = resolved.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["file_sha256"]:
        raise ValueError(f"{name} file bytes differ")
    if sealed["content_sha256"] != reference["content_sha256"]:
        raise ValueError(f"{name} content SHA differs")
    return sealed


def _read_canonical_json_file(path: Path, *, name: str) -> dict[str, object]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise ValueError(f"{name} fixed file is missing")
    raw = resolved.read_bytes()
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise ValueError(f"{name} file is not canonical JSON")
    body = raw[:-1]
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} file is not canonical JSON") from error
    if not isinstance(decoded, Mapping) or _canonical_bytes(decoded) != body:
        raise ValueError(f"{name} file is not canonical JSON")
    return _sealed_mapping(decoded, name=name)


def _ledger_pre_result_ref(
    *,
    attempt_ref: Mapping[str, object],
    cleanup_envelope: Mapping[str, object],
    raw_prefix: bytes,
) -> dict[str, object]:
    sequence = cleanup_envelope.get("event", {}).get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("cleanup terminal sequence is invalid")
    return {
        "contract_version": _PRE_RESULT_REF_CONTRACT,
        "id": "runner-ledger-pre-result/"
        + hashlib.sha256(
            b"benchmark-v2-runner-ledger-pre-result\0" + raw_prefix
        ).hexdigest(),
        "attempt_ref": deepcopy(dict(attempt_ref)),
        "terminal_sequence": sequence,
        "terminal_envelope_sha256": hashlib.sha256(
            _canonical_bytes(cleanup_envelope)
        ).hexdigest(),
        "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
    }


def _validate_actual_result(
    value: Mapping[str, object],
    *,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    body_ref: Mapping[str, object],
    cleanup_ref: Mapping[str, object],
    expected_pre_result_ref: Mapping[str, object],
) -> None:
    expected = {
        "contract_version",
        "attempt_ref",
        "attempt_dir",
        "body_ref",
        "cleanup_receipt_ref",
        "attempt_ledger_pre_result_ref",
        "screen_group_count",
        "status",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        set(value) != expected
        or value.get("contract_version") != _ACTUAL_RESULT_CONTRACT
        or value.get("attempt_ref") != dict(attempt_ref)
        or value.get("attempt_dir") != str(Path(attempt_dir).resolve())
        or value.get("body_ref") != dict(body_ref)
        or value.get("cleanup_receipt_ref") != dict(cleanup_ref)
        or value.get("attempt_ledger_pre_result_ref")
        != dict(expected_pre_result_ref)
        or isinstance(value.get("screen_group_count"), bool)
        or value.get("screen_group_count") != 12
        or value.get("status") != "terminal"
        or value.get("artifact_is_authorization") is not False
        or value.get("execute_binding_enabled") is not False
    ):
        raise ValueError("actual result lineage is invalid")


def _validate_probe_result(
    value: Mapping[str, object],
    *,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    body_ref: Mapping[str, object],
    cleanup_ref: Mapping[str, object],
) -> None:
    expected = {
        "contract_version",
        "attempt_ref",
        "attempt_dir",
        "provider_id",
        "probe_kind",
        "body_ref",
        "cleanup_receipt_ref",
        "status",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        set(value) != expected
        or value.get("contract_version") != "benchmark_v2_runner_probe_result_v1"
        or value.get("attempt_ref") != dict(attempt_ref)
        or value.get("attempt_dir") != str(Path(attempt_dir).resolve())
        or value.get("provider_id") != attempt_ref.get("provider_id")
        or value.get("probe_kind") not in {"cancel", "timeout"}
        or value.get("body_ref")
        != {"content_sha256": body_ref.get("content_sha256")}
        or value.get("cleanup_receipt_ref")
        != {"content_sha256": cleanup_ref.get("content_sha256")}
        or value.get("status") != "terminal"
        or value.get("artifact_is_authorization") is not False
        or value.get("execute_binding_enabled") is not False
    ):
        raise ValueError("probe result lineage is invalid")


def _validate_ledger_records(
    records: Sequence[Mapping[str, object]],
    *,
    raw_lines: Sequence[bytes],
) -> None:
    if len(records) != len(raw_lines):
        raise ValueError("attempt ledger record bytes differ")
    attempts: dict[str, dict[str, object]] = {}
    attempt_ids: dict[str, str] = {}
    attempt_dirs: dict[str, str] = {}
    for envelope in records:
        event = envelope["event"]
        payload = event["event_payload"]
        attempt = payload["attempt_ref"]
        attempt_key = str(attempt["content_sha256"])
        attempt_id = str(attempt["attempt_id"])
        attempt_dir = str(Path(str(payload["attempt_dir"])).resolve())
        if Path(attempt_dir).name != attempt_id:
            raise ValueError("attempt ledger directory lineage differs")
        prior_attempt_key = attempt_ids.setdefault(attempt_id, attempt_key)
        prior_dir_key = attempt_dirs.setdefault(attempt_dir, attempt_key)
        if prior_attempt_key != attempt_key or prior_dir_key != attempt_key:
            raise ValueError("attempt ledger cross-attempt lineage differs")

        event_type = str(event["event_type"])
        status = str(payload["status"])
        current = attempts.get(attempt_key)
        if current is None:
            if event_type != "regression_attempt" or status != "opened":
                raise ValueError("attempt ledger state starts before opened")
            attempts[attempt_key] = {
                "attempt_ref": deepcopy(dict(attempt)),
                "attempt_dir": attempt_dir,
                "mode": payload["mode"],
                "provider_id": payload["provider_id"],
                "state": "opened",
                "body_ref": None,
                "cleanup_ref": None,
                "cleanup_envelope": None,
                "had_body": False,
            }
            continue
        if (
            current["attempt_ref"] != dict(attempt)
            or current["attempt_dir"] != attempt_dir
            or current["mode"] != payload["mode"]
            or current["provider_id"] != payload["provider_id"]
        ):
            raise ValueError("attempt ledger lineage differs")
        state = current["state"]
        if event_type == "regression_attempt":
            if status != "body_complete" or state != "opened":
                raise ValueError("attempt ledger duplicate or reordered state")
            body_ref = _validate_output_ref(payload["output_ref"])
            _read_exact_json_ref(
                body_ref,
                expected_path=Path(attempt_dir) / "body.json",
                name="actual body",
            )
            current["body_ref"] = body_ref
            current["had_body"] = True
            current["state"] = "body_complete"
            continue
        if event_type == "cleanup":
            if state not in {"opened", "body_complete"}:
                raise ValueError("attempt ledger duplicate or reordered cleanup")
            cleanup_ref = _validate_output_ref(payload["cleanup_receipt_ref"])
            cleanup = _read_exact_json_ref(
                cleanup_ref,
                expected_path=Path(attempt_dir) / "cleanup.json",
                name="cleanup receipt",
            )
            cleanup = _validate_cleanup_receipt(
                cleanup,
                attempt_ref=attempt,
                require_effect_refs=bool(current["had_body"]),
            )
            if payload.get("resource_counts") != cleanup.get("resource_counts"):
                raise ValueError(
                    "attempt ledger cleanup counts differ from authoritative receipt"
                )
            current["cleanup_ref"] = cleanup_ref
            current["cleanup_envelope"] = deepcopy(dict(envelope))
            current["state"] = "cleanup"
            continue
        if event_type != "result" or state != "cleanup" or not current["had_body"]:
            raise ValueError("attempt ledger duplicate or reordered result")
        result_ref = _validate_output_ref(payload["output_ref"])
        result = _read_exact_json_ref(
            result_ref,
            expected_path=Path(attempt_dir) / "result.json",
            name="runner result",
        )
        cleanup_sequence = int(current["cleanup_envelope"]["event"]["sequence"])
        raw_prefix = b"".join(raw + b"\n" for raw in raw_lines[: cleanup_sequence + 1])
        expected_pre_result_ref = _ledger_pre_result_ref(
            attempt_ref=attempt,
            cleanup_envelope=current["cleanup_envelope"],
            raw_prefix=raw_prefix,
        )
        if current["mode"] == "actual_models":
            _validate_actual_result(
                result,
                attempt_ref=attempt,
                attempt_dir=Path(attempt_dir),
                body_ref=current["body_ref"],
                cleanup_ref=current["cleanup_ref"],
                expected_pre_result_ref=expected_pre_result_ref,
            )
        else:
            _validate_probe_result(
                result,
                attempt_ref=attempt,
                attempt_dir=Path(attempt_dir),
                body_ref=current["body_ref"],
                cleanup_ref=current["cleanup_ref"],
            )
        current["state"] = "result"


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    lock_path = Path(str(Path(path).resolve()) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.path.getsize(lock_path) == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _append_ledger_event(
    path: Path,
    *,
    event_type: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    ledger = Path(path).resolve()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with _ledger_lock(ledger):
        chain = _read_ledger(ledger)
        previous = (
            _ZERO_SHA256
            if not chain
            else hashlib.sha256(_canonical_bytes(chain[-1])).hexdigest()
        )
        event = {
            "partition": "regression",
            "sequence": len(chain),
            "event_type": event_type,
            "previous_envelope_sha256": previous,
            "event_payload": deepcopy(dict(payload)),
        }
        _validate_event_payload(event["event_payload"], event_type=event_type)
        wrapped = {
            "contract_version": _LEDGER_CONTRACT,
            "event": event,
            "event_sha256": hashlib.sha256(_canonical_bytes(event)).hexdigest(),
        }
        next_raw = _canonical_bytes(wrapped)
        _validate_ledger_records(
            [*chain, wrapped],
            raw_lines=[*(_canonical_bytes(item) for item in chain), next_raw],
        )
        with ledger.open("ab") as stream:
            stream.write(next_raw + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        reloaded = _read_ledger(ledger)
        if not reloaded or reloaded[-1] != wrapped:
            raise ValueError("attempt ledger reload differs after append")
        return wrapped


def _attempt_payload(
    *,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    status: str,
    output_ref: Mapping[str, object] | None,
) -> dict[str, object]:
    return _seal(
        {
            "contract_version": _ATTEMPT_PAYLOAD_CONTRACT,
            "attempt_ref": deepcopy(dict(attempt_ref)),
            "attempt_dir": str(Path(attempt_dir).resolve()),
            "mode": attempt_ref["mode"],
            "provider_id": attempt_ref["provider_id"],
            "status": status,
            "output_ref": deepcopy(dict(output_ref)) if output_ref is not None else None,
            **_SAFETY,
        }
    )


def _cleanup_payload(
    *,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    cleanup_receipt_ref: Mapping[str, object],
    resource_counts: Mapping[str, int],
) -> dict[str, object]:
    return _seal(
        {
            "contract_version": _CLEANUP_PAYLOAD_CONTRACT,
            "attempt_ref": deepcopy(dict(attempt_ref)),
            "attempt_dir": str(Path(attempt_dir).resolve()),
            "mode": attempt_ref["mode"],
            "provider_id": attempt_ref["provider_id"],
            "status": "terminal",
            "cleanup_receipt_ref": deepcopy(dict(cleanup_receipt_ref)),
            "resource_counts": deepcopy(dict(resource_counts)),
            **_SAFETY,
        }
    )


def _result_payload(
    *,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    output_ref: Mapping[str, object],
) -> dict[str, object]:
    return _seal(
        {
            "contract_version": _RESULT_PAYLOAD_CONTRACT,
            "attempt_ref": deepcopy(dict(attempt_ref)),
            "attempt_dir": str(Path(attempt_dir).resolve()),
            "mode": attempt_ref["mode"],
            "provider_id": attempt_ref["provider_id"],
            "status": "terminal",
            "output_ref": deepcopy(dict(output_ref)),
            **_SAFETY,
        }
    )


def _pre_result_ref_from_ledger(
    ledger_path: Path,
    *,
    attempt_ref: Mapping[str, object],
) -> dict[str, object]:
    ledger = Path(ledger_path).resolve()
    chain = _read_ledger(ledger)
    raw_lines = ledger.read_bytes().split(b"\n")[:-1]
    cleanup_envelope: Mapping[str, object] | None = None
    for envelope in chain:
        event = envelope["event"]
        payload = event["event_payload"]
        if (
            payload.get("attempt_ref") == dict(attempt_ref)
            and event.get("event_type") == "cleanup"
        ):
            if cleanup_envelope is not None:
                raise ValueError("attempt ledger has duplicate cleanup")
            cleanup_envelope = envelope
    if cleanup_envelope is None:
        raise ValueError("attempt ledger cleanup is unavailable")
    sequence = int(cleanup_envelope["event"]["sequence"])
    raw_prefix = b"".join(raw + b"\n" for raw in raw_lines[: sequence + 1])
    return _ledger_pre_result_ref(
        attempt_ref=attempt_ref,
        cleanup_envelope=cleanup_envelope,
        raw_prefix=raw_prefix,
    )


def _append_result_file_event(
    *,
    ledger_path: Path,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    result: Mapping[str, object],
) -> None:
    result_path = Path(attempt_dir).resolve() / "result.json"
    _write_json(result_path, result, create_only=True)
    _append_ledger_event(
        ledger_path,
        event_type="result",
        payload=_result_payload(
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
            output_ref=_file_ref(result_path, result),
        ),
    )


def _reserve_attempt(
    *,
    ledger_path: Path,
    output_root: Path,
    mode: str,
    provider_id: str | None,
) -> tuple[dict[str, object], Path]:
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    attempt_id = "attempt-" + uuid.uuid4().hex
    attempt_dir = root / attempt_id
    attempt_dir.mkdir()
    attempt = _seal(
        {
            "contract_version": _ATTEMPT_CONTRACT,
            "attempt_id": attempt_id,
            "partition": "regression",
            "mode": mode,
            "provider_id": provider_id,
            **_SAFETY,
        }
    )
    try:
        _append_ledger_event(
            ledger_path,
            event_type="regression_attempt",
            payload=_attempt_payload(
                attempt_ref=attempt,
                attempt_dir=attempt_dir,
                status="opened",
                output_ref=None,
            ),
        )
    except BaseException:
        try:
            attempt_dir.rmdir()
        except OSError:
            pass
        raise
    return attempt, attempt_dir


def _require_zero_counts(runtime: object) -> dict[str, int]:
    raw = runtime.resource_counts()
    if (
        not isinstance(raw, Mapping)
        or set(raw) != set(_ZERO_COUNTS)
        or any(isinstance(value, bool) or not isinstance(value, int) or value != 0 for value in raw.values())
    ):
        raise RuntimeError("benchmark runtime cleanup did not reach stable zero")
    return deepcopy(_ZERO_COUNTS)


def _validate_cleanup_receipt(
    value: object,
    *,
    attempt_ref: Mapping[str, object],
    require_effect_refs: bool,
) -> dict[str, object]:
    receipt = _sealed_mapping(value, name="cleanup receipt")
    expected = {
        "contract_version",
        "attempt_ref",
        "reason",
        "service_terminal_ref",
        "window_cleanup_ref",
        "provider_cleanup_refs",
        "resource_counts",
        "cleanup_status",
        "lost_response_policy",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        set(receipt) != expected
        or receipt.get("contract_version") != _CLEANUP_RECEIPT_CONTRACT
        or receipt.get("attempt_ref") != dict(attempt_ref)
        or not isinstance(receipt.get("reason"), str)
        or not str(receipt["reason"]).strip()
        or receipt.get("cleanup_status") != "stable_zero"
        or receipt.get("lost_response_policy")
        != "fresh_reconcile_safe_stop_no_blind_retry"
        or receipt.get("artifact_is_authorization") is not False
        or receipt.get("execute_binding_enabled") is not False
        or receipt.get("resource_counts") != _ZERO_COUNTS
        or not isinstance(receipt.get("provider_cleanup_refs"), list)
    ):
        raise ValueError("authoritative cleanup receipt is invalid")
    service_ref = receipt["service_terminal_ref"]
    window_ref = receipt["window_cleanup_ref"]
    provider_refs = receipt["provider_cleanup_refs"]
    counts = receipt["resource_counts"]
    if (
        not isinstance(counts, Mapping)
        or set(counts) != set(_ZERO_COUNTS)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value != 0
            for value in counts.values()
        )
    ):
        raise ValueError("authoritative cleanup receipt resource counts are invalid")
    if service_ref is not None:
        _sealed_mapping(service_ref, name="cleanup receipt service terminal ref")
    if window_ref is not None:
        _sealed_mapping(window_ref, name="cleanup receipt window ref")
    for provider_ref in provider_refs:
        _sealed_mapping(provider_ref, name="cleanup receipt provider ref")
    if require_effect_refs and (
        service_ref is None or window_ref is None or not provider_refs
    ):
        raise ValueError("authoritative cleanup receipt required refs are missing")
    return receipt


def _finish_attempt(
    runtime: object,
    *,
    ledger_path: Path,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    reason: str,
    require_effect_refs: bool,
) -> dict[str, object]:
    cleanup_path = Path(attempt_dir).resolve() / "cleanup.json"
    existing_cleanup: dict[str, object] | None = None
    cleanup_reason = reason
    if cleanup_path.exists():
        try:
            existing_cleanup = _validate_cleanup_receipt(
                _read_canonical_json_file(cleanup_path, name="cleanup receipt"),
                attempt_ref=attempt_ref,
                require_effect_refs=require_effect_refs,
            )
        except ValueError:
            existing_cleanup = None
        else:
            cleanup_reason = str(existing_cleanup["reason"])
    cleanup = _validate_cleanup_receipt(
        runtime.cleanup_attempt(
            attempt=deepcopy(dict(attempt_ref)), reason=cleanup_reason
        ),
        attempt_ref=attempt_ref,
        require_effect_refs=require_effect_refs,
    )
    counts = _require_zero_counts(runtime)
    if cleanup.get("resource_counts") != counts:
        raise ValueError(
            "authoritative cleanup receipt counts differ from fresh runtime state"
        )
    if existing_cleanup is not None and cleanup != existing_cleanup:
        raise ValueError(
            "fresh cleanup reconciliation differs from existing authoritative receipt"
        )
    _write_json_create_or_identical(cleanup_path, cleanup)
    cleanup_ref = _file_ref(cleanup_path, cleanup)
    _append_ledger_event(
        ledger_path,
        event_type="cleanup",
        payload=_cleanup_payload(
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
            cleanup_receipt_ref=cleanup_ref,
            resource_counts=counts,
        ),
    )
    return cleanup


def _validate_actual_group(
    value: object,
    *,
    attempt_ref: Mapping[str, object],
    provider_corpus_ref: object,
) -> tuple[dict[str, object], tuple[str, str], set[str]]:
    group = _sealed_mapping(value, name="actual screen group")
    screen_group = group.get("screen_group")
    case_refs = group.get("case_refs")
    group_corpus_ref = group.get("provider_corpus_ref")
    corpus_lineage_fields = {
        "relative_path",
        "file_sha256",
        "content_sha256",
        "source_parent_ref",
    }
    corpus_lineage_matches = bool(
        isinstance(group_corpus_ref, Mapping)
        and isinstance(provider_corpus_ref, Mapping)
        and corpus_lineage_fields.issubset(group_corpus_ref)
        and corpus_lineage_fields.issubset(provider_corpus_ref)
        and all(
            group_corpus_ref.get(name) == provider_corpus_ref.get(name)
            for name in corpus_lineage_fields
        )
    )
    if (
        not isinstance(screen_group, str)
        or not screen_group
        or group.get("partition") != "regression"
        or group.get("attempt_ref") != dict(attempt_ref)
        or not corpus_lineage_matches
        or not isinstance(case_refs, list)
        or len(case_refs) != 5
    ):
        raise ValueError("actual runner requires 12 unique regression screen groups")
    case_ids: set[str] = set()
    for case_ref in case_refs:
        if (
            not isinstance(case_ref, Mapping)
            or set(case_ref) != {"case_id", "case_content_sha256"}
            or not isinstance(case_ref.get("case_id"), str)
            or not case_ref["case_id"]
            or not isinstance(case_ref.get("case_content_sha256"), str)
            or len(str(case_ref["case_content_sha256"])) != 64
        ):
            raise ValueError("actual runner requires 12 unique regression screen groups")
        case_ids.add(str(case_ref["case_id"]))
    if len(case_ids) != 5:
        raise ValueError("actual runner requires 12 unique regression screen groups")
    return (
        group,
        (screen_group, str(group["content_sha256"])),
        case_ids,
    )


def _validate_actual_projection(
    value: object, *, group: Mapping[str, object]
) -> dict[str, object]:
    projection = _sealed_mapping(value, name="actual screen-group projection")
    screen_ref = {
        "id": str(group["screen_group"]),
        "content_sha256": str(group["content_sha256"]),
    }
    shared = projection.get("shared_parent_refs")
    rows = projection.get("rows")
    arm_ids = {
        "qwen_only",
        "omni_only_discovery",
        "omni_to_qwen",
        "omni_to_qwen_vista",
    }
    case_refs = {
        str(item["case_id"]): dict(item) for item in group["case_refs"]
    }
    if (
        projection.get("contract_version")
        != "benchmark_v2_actual_screen_group_projection_v1"
        or projection.get("partition") != "regression"
        or projection.get("screen_group") != group["screen_group"]
        or projection.get("request_ref") != group.get("request_ref")
        or not isinstance(shared, Mapping)
        or shared.get("screen_group_ref") != screen_ref
        or not isinstance(rows, list)
        or len(rows) != 20
        or projection.get("artifact_is_authorization") is not False
        or projection.get("execute_binding_enabled") is not False
    ):
        raise ValueError("actual screen-group projection lineage is invalid")
    observed: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("actual screen-group projection lineage is invalid")
        case_ref = row.get("case_ref")
        row_shared = row.get("shared_parent_refs")
        case_id = case_ref.get("case_id") if isinstance(case_ref, Mapping) else None
        arm_id = row.get("arm_id")
        if (
            case_id not in case_refs
            or dict(case_ref) != case_refs[case_id]
            or arm_id not in arm_ids
            or not isinstance(row_shared, Mapping)
            or row_shared.get("screen_group_ref") != screen_ref
        ):
            raise ValueError("actual screen-group projection lineage is invalid")
        observed.add((str(case_id), str(arm_id)))
    expected = {(case_id, arm_id) for case_id in case_refs for arm_id in arm_ids}
    if observed != expected:
        raise ValueError("actual screen-group projection lineage is invalid")
    return projection


def _run_actual(args: argparse.Namespace, runtime: object) -> dict[str, object]:
    if args.partition != "regression":
        raise ValueError("Task 9 actual execution is regression-only; holdout is not authorized")
    manifest = runtime.load_provider_manifest(path=Path(args.provider_manifest))
    attempt, attempt_dir = _reserve_attempt(
        ledger_path=Path(args.attempt_ledger),
        output_root=Path(args.output_root),
        mode="actual_models",
        provider_id=None,
    )
    primary: BaseException | None = None
    body: dict[str, object] | None = None
    cleanup: dict[str, object] | None = None
    try:
        projections: list[dict[str, object]] = []
        group_identities: set[tuple[str, str]] = set()
        screen_group_ids: set[str] = set()
        case_ids: set[str] = set()
        provider_corpus_ref = manifest.get("provider_corpus_ref")
        if not isinstance(provider_corpus_ref, Mapping):
            raise ValueError("provider manifest corpus lineage is unavailable")
        owner = runtime.prepare_screen_groups(
            provider_manifest=manifest,
            partition="regression",
            attempt_ref=deepcopy(attempt),
            attempt_dir=attempt_dir,
        )
        with owner as groups:
            for raw_group in groups:
                provider_group, identity, group_case_ids = _validate_actual_group(
                    raw_group,
                    attempt_ref=attempt,
                    provider_corpus_ref=provider_corpus_ref,
                )
                if (
                    identity in group_identities
                    or identity[0] in screen_group_ids
                    or case_ids.intersection(group_case_ids)
                    or len(group_identities) >= 12
                ):
                    raise ValueError(
                        "actual runner requires 12 unique regression screen groups"
                    )
                group_identities.add(identity)
                screen_group_ids.add(identity[0])
                case_ids.update(group_case_ids)
                projection = _validate_actual_projection(
                    runtime.run_actual_screen_group(
                        provider_group=provider_group,
                        attempt_ref=deepcopy(attempt),
                        attempt_dir=attempt_dir,
                    ),
                    group=provider_group,
                )
                projections.append(projection)
        if (
            len(group_identities) != 12
            or len(screen_group_ids) != 12
            or len(case_ids) != 60
        ):
            raise ValueError("actual runner requires 12 unique regression screen groups")
        body = _seal(
            {
                "contract_version": "benchmark_v2_runner_actual_body_v1",
                "attempt_ref": deepcopy(attempt),
                "partition": "regression",
                "screen_group_results": projections,
                "body_status": "complete",
                **_SAFETY,
            }
        )
        body_path = attempt_dir / "body.json"
        _write_json(body_path, body, create_only=True)
        _append_ledger_event(
            Path(args.attempt_ledger),
            event_type="regression_attempt",
            payload=_attempt_payload(
                attempt_ref=attempt,
                attempt_dir=attempt_dir,
                status="body_complete",
                output_ref=_file_ref(body_path, body),
            ),
        )
    except BaseException as error:
        primary = error
    try:
        cleanup = _finish_attempt(
            runtime,
            ledger_path=Path(args.attempt_ledger),
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            reason="benchmark_v2_actual_runner_finished",
            require_effect_refs=body is not None,
        )
    except BaseException as cleanup_error:
        if primary is not None:
            raise BaseExceptionGroup(
                "benchmark actual body and cleanup failed",
                [primary, cleanup_error],
            )
        raise
    if primary is not None:
        raise primary
    if body is None or cleanup is None:
        raise RuntimeError("benchmark actual attempt did not produce complete evidence")
    body_path = attempt_dir / "body.json"
    cleanup_path = attempt_dir / "cleanup.json"
    result = _seal(
        {
            "contract_version": _ACTUAL_RESULT_CONTRACT,
            "attempt_ref": deepcopy(attempt),
            "attempt_dir": str(attempt_dir.resolve()),
            "body_ref": _file_ref(body_path, body),
            "cleanup_receipt_ref": _file_ref(cleanup_path, cleanup),
            "attempt_ledger_pre_result_ref": _pre_result_ref_from_ledger(
                Path(args.attempt_ledger), attempt_ref=attempt
            ),
            "screen_group_count": len(body["screen_group_results"]),
            "status": "terminal",
            **_SAFETY,
        }
    )
    _append_result_file_event(
        ledger_path=Path(args.attempt_ledger),
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
        result=result,
    )
    return result


def _run_one_probe(
    *,
    runtime: object,
    manifest: Mapping[str, object],
    provider_id: str,
    probe_kind: str,
    ledger_path: Path,
    output_root: Path,
) -> dict[str, object]:
    mode = f"{probe_kind}_probe"
    attempt, attempt_dir = _reserve_attempt(
        ledger_path=ledger_path,
        output_root=output_root,
        mode=mode,
        provider_id=provider_id,
    )
    primary: BaseException | None = None
    body: dict[str, object] | None = None
    cleanup: dict[str, object] | None = None
    try:
        context = _sealed_mapping(
            runtime.begin_probe(
                provider_id=provider_id,
                probe_kind=probe_kind,
                provider_manifest=manifest,
                attempt_ref=deepcopy(attempt),
                attempt_dir=attempt_dir,
            ),
            name="probe context",
        )
        request = _sealed_mapping(
            runtime.read_server_journal(probe_context=deepcopy(context)),
            name="request-in-flight journal",
        )
        if request.get("request_state") != "request_in_flight":
            raise RuntimeError("benchmark probe request is not in flight")
        trigger = _sealed_mapping(
            runtime.trigger_probe(
                probe_context=deepcopy(context),
                probe_kind=probe_kind,
                request_in_flight_journal=deepcopy(request),
            ),
            name="probe trigger receipt",
        )
        body = _seal(
            {
                "contract_version": "benchmark_v2_runner_probe_body_v1",
                "attempt_ref": deepcopy(attempt),
                "partition": "regression",
                "provider_id": provider_id,
                "probe_kind": probe_kind,
                "probe_context_ref": _content_ref(context, name="probe context"),
                "request_in_flight_ref": _content_ref(
                    request, name="request-in-flight journal"
                ),
                "trigger_receipt_ref": _content_ref(
                    trigger, name="probe trigger receipt"
                ),
                "body_status": "complete",
                **_SAFETY,
            }
        )
        body_path = attempt_dir / "body.json"
        _write_json(body_path, body, create_only=True)
        _append_ledger_event(
            ledger_path,
            event_type="regression_attempt",
            payload=_attempt_payload(
                attempt_ref=attempt,
                attempt_dir=attempt_dir,
                status="body_complete",
                output_ref=_file_ref(body_path, body),
            ),
        )
    except BaseException as error:
        primary = error
    try:
        cleanup = _finish_attempt(
            runtime,
            ledger_path=ledger_path,
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            reason=f"benchmark_v2_{probe_kind}_probe_finished",
            require_effect_refs=body is not None,
        )
    except BaseException as cleanup_error:
        if primary is not None:
            raise BaseExceptionGroup(
                "benchmark probe body and cleanup failed",
                [primary, cleanup_error],
            )
        raise
    if primary is not None:
        raise primary
    if body is None or cleanup is None:
        raise RuntimeError("benchmark probe attempt did not produce complete evidence")
    result = _seal(
        {
            "contract_version": "benchmark_v2_runner_probe_result_v1",
            "attempt_ref": deepcopy(attempt),
            "attempt_dir": str(attempt_dir),
            "provider_id": provider_id,
            "probe_kind": probe_kind,
            "body_ref": _content_ref(body, name="probe body"),
            "cleanup_receipt_ref": _content_ref(cleanup, name="cleanup receipt"),
            "status": "terminal",
            **_SAFETY,
        }
    )
    _append_result_file_event(
        ledger_path=ledger_path,
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
        result=result,
    )
    return result


def _run_probes(args: argparse.Namespace, runtime: object, *, probe_kind: str) -> dict[str, object]:
    if args.partition != "regression":
        raise ValueError("benchmark lifecycle probes are forbidden for holdout")
    providers = _parse_providers(args.providers)
    manifest = runtime.load_provider_manifest(path=Path(args.provider_manifest))
    attempts = [
        _run_one_probe(
            runtime=runtime,
            manifest=manifest,
            provider_id=provider,
            probe_kind=probe_kind,
            ledger_path=Path(args.attempt_ledger),
            output_root=Path(args.output_root),
        )
        for provider in providers
    ]
    result = _seal(
        {
            "contract_version": "benchmark_v2_runner_probe_summary_v1",
            "partition": "regression",
            "probe_kind": probe_kind,
            "attempts": attempts,
            **_SAFETY,
        }
    )
    _write_json(
        Path(args.output_root) / f"{probe_kind}-probes.json",
        result,
        create_only=False,
    )
    return result


def _parse_providers(raw: str) -> tuple[str, ...]:
    providers = tuple(part.strip() for part in str(raw or "").split(",") if part.strip())
    if (
        not providers
        or len(set(providers)) != len(providers)
        or any(provider not in _PROVIDERS for provider in providers)
    ):
        raise ValueError("providers must be a unique comma-separated subset of omni,qwen,vista")
    return providers


def _open_attempts(path: Path, *, partition: str) -> list[dict[str, object]]:
    if partition != "regression":
        raise ValueError("Task 9 open-attempt cleanup is regression-only")
    chain = _read_ledger(path)
    attempts: dict[str, dict[str, object]] = {}
    terminal: set[str] = set()
    for envelope in chain:
        event = envelope["event"]
        payload = event["event_payload"]
        attempt = payload["attempt_ref"]
        digest = str(attempt["content_sha256"])
        if event["event_type"] == "regression_attempt":
            current = attempts.get(digest)
            candidate = {
                "attempt_ref": deepcopy(dict(attempt)),
                "attempt_dir": Path(str(payload["attempt_dir"])),
                "mode": payload["mode"],
                "provider_id": payload["provider_id"],
                "body_complete": payload["status"] == "body_complete",
            }
            if current is not None:
                stable_current = {
                    name: value for name, value in current.items() if name != "body_complete"
                }
                stable_candidate = {
                    name: value
                    for name, value in candidate.items()
                    if name != "body_complete"
                }
                if stable_current != stable_candidate:
                    raise ValueError("attempt ledger rebinds one attempt")
                candidate["body_complete"] = bool(
                    current["body_complete"] or candidate["body_complete"]
                )
            attempts[digest] = candidate
        else:
            terminal.add(digest)
    return [value for digest, value in attempts.items() if digest not in terminal]


def _cleanup_open_attempts(args: argparse.Namespace, runtime: object) -> dict[str, object]:
    if args.partition != "regression":
        raise ValueError("Task 9 open-attempt cleanup is regression-only")
    ledger_root = Path(args.ledger_root).resolve()
    cleaned_refs: list[dict[str, str]] = []
    for ledger in sorted(ledger_root.rglob("*.jsonl")) if ledger_root.exists() else []:
        for item in _open_attempts(ledger, partition="regression"):
            attempt = item["attempt_ref"]
            _finish_attempt(
                runtime,
                ledger_path=ledger,
                attempt_ref=attempt,
                attempt_dir=item["attempt_dir"],
                reason="benchmark_v2_cleanup_open_attempt",
                require_effect_refs=bool(item["body_complete"]),
            )
            cleaned_refs.append({"content_sha256": str(attempt["content_sha256"])})
    counts = _require_zero_counts(runtime)
    result = _seal(
        {
            "contract_version": "benchmark_v2_runner_cleanup_summary_v1",
            "partition": "regression",
            "cleaned_attempt_count": len(cleaned_refs),
            "cleaned_attempt_refs": cleaned_refs,
            "resource_counts": counts,
            **_SAFETY,
        }
    )
    _write_json(
        Path(args.output_root) / "cleanup-open-attempts.json",
        result,
        create_only=False,
    )
    return result


def _dry_run(args: argparse.Namespace, runtime: object) -> dict[str, object]:
    loaded = runtime.load_provider_manifest(path=Path(args.provider_manifest))
    if not isinstance(loaded, Mapping):
        raise ValueError("provider manifest must be an object")
    manifest_ref = {
        "content_sha256": hashlib.sha256(_canonical_bytes(dict(loaded))).hexdigest()
    }
    result = _seal(
        {
            "contract_version": "benchmark_v2_runner_dry_run_v1",
            "partition": args.partition,
            "provider_manifest_ref": manifest_ref,
            "provider_dispatch_count": 0,
            "dry_run": True,
            **_SAFETY,
        }
    )
    _write_json(Path(args.output), result, create_only=False)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Portfolio Hybrid v1.1 Benchmark-v2")
    parser.add_argument("--provider-manifest")
    parser.add_argument("--partition", choices=("regression", "holdout"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--actual-models", action="store_true")
    action.add_argument("--run-cancel-probe", action="store_true")
    action.add_argument("--run-timeout-probe", action="store_true")
    action.add_argument("--cleanup-open-attempts", action="store_true")
    action.add_argument("--cleanup-only", action="store_true")
    parser.add_argument("--providers")
    parser.add_argument("--attempt-ledger")
    parser.add_argument("--ledger-root")
    parser.add_argument("--output")
    parser.add_argument("--output-root")
    parser.add_argument("--holdout-authorization")
    return parser


def _require(args: argparse.Namespace, *names: str) -> None:
    missing = [name for name in names if not getattr(args, name)]
    if missing:
        raise ValueError("missing required runner arguments: " + ", ".join(missing))


def _reject(args: argparse.Namespace, *names: str) -> None:
    present = [name for name in names if getattr(args, name)]
    if present:
        raise ValueError("runner arguments are not valid for this action: " + ", ".join(present))


def run_cli(argv: Sequence[str]) -> dict[str, object]:
    args = _parser().parse_args(list(argv))
    runtime = get_production_benchmark_v2_runtime()
    if args.dry_run:
        _require(args, "provider_manifest", "partition", "output")
        _reject(
            args,
            "providers",
            "attempt_ledger",
            "ledger_root",
            "output_root",
            "holdout_authorization",
        )
        return _dry_run(args, runtime)
    if args.actual_models:
        _require(args, "provider_manifest", "partition", "attempt_ledger", "output_root")
        _reject(args, "providers", "ledger_root", "output", "holdout_authorization")
        return _run_actual(args, runtime)
    if args.run_cancel_probe or args.run_timeout_probe:
        _require(
            args,
            "provider_manifest",
            "partition",
            "providers",
            "attempt_ledger",
            "output_root",
        )
        _reject(args, "ledger_root", "output", "holdout_authorization")
        return _run_probes(
            args,
            runtime,
            probe_kind="cancel" if args.run_cancel_probe else "timeout",
        )
    if args.cleanup_open_attempts:
        _require(args, "partition", "ledger_root", "output_root")
        _reject(
            args,
            "provider_manifest",
            "providers",
            "attempt_ledger",
            "output",
            "holdout_authorization",
        )
        return _cleanup_open_attempts(args, runtime)
    if args.cleanup_only:
        raise ValueError("holdout cleanup-only requires the Task 13 authorization boundary")
    raise RuntimeError("runner action selection is unreachable")


def main(argv: Sequence[str] | None = None) -> int:
    result = run_cli(sys.argv[1:] if argv is None else argv)
    sys.stdout.buffer.write(_canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
