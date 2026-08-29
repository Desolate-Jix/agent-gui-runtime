"""Partitioned Benchmark-v2 ledgers and production holdout claim facade."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

from app.learn.hybrid.benchmark_v2_durable_claim import (
    IDENTITY,
    SAFETY,
    _claim_with_backend,
    _file_anchor_exact,
    _ledger_mutex_name,
    _named_mutex,
    _production_backend,
    _production_ledger_root_is_exact,
    _recover_with_backend,
    _test_backend,
    _verify_claim_anchors_read_only,
    authorization_envelope,
    canonical_bytes,
    claim_id,
)


_ZERO = "0" * 64
_AUTHORITY_PROJECTION_SPECS = {
    "benchmark_v2_holdout_authorization_public_projection_v1": (
        "holdout-authorization-public-projection"
    ),
    "benchmark_v2_holdout_claim_public_projection_v1": (
        "holdout-claim-public-projection"
    ),
    "benchmark_v2_holdout_file_anchor_public_projection_v1": (
        "holdout-file-anchor-public-projection"
    ),
    "benchmark_v2_holdout_registry_anchor_public_projection_v1": (
        "holdout-registry-anchor-public-projection"
    ),
}

_HOLDOUT_ATTEMPT_ENVELOPE = "benchmark_v2_holdout_attempt_event_envelope_v1"
_HOLDOUT_ATTEMPT_KINDS = (
    "opened",
    "body_complete",
    "cleanup",
    "result",
    "recovery_cleanup",
)
_HOLDOUT_PAYLOAD_FIELDS = {
    "opened": {"contract_version", "attempt_ref", "attempt_dir", "status", "safety", "content_sha256"},
    "body_complete": {"contract_version", "attempt_ref", "attempt_dir", "status", "body_file_ref", "safety", "content_sha256"},
    "cleanup": {"contract_version", "attempt_ref", "attempt_dir", "status", "cleanup_receipt_ref", "resource_counts", "safety", "content_sha256"},
    "result": {"contract_version", "attempt_ref", "attempt_dir", "status", "result_file_ref", "attempt_ledger_pre_result_ref", "safety", "content_sha256"},
    "recovery_cleanup": {"contract_version", "attempt_ref", "attempt_dir", "status", "cleanup_receipt_ref", "resource_counts", "recovery_reason", "safety", "content_sha256"},
}
_ZERO_RESOURCE_COUNTS = {
    "service_operations": 0,
    "windows": 0,
    "providers": 0,
    "listeners": 0,
    "leases": 0,
}
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUTHORIZED_HOLDOUT_OUTPUT_ROOT_TOKEN = "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout"
AUTHORIZED_HOLDOUT_OUTPUT_ROOT = (_PROJECT_ROOT / AUTHORIZED_HOLDOUT_OUTPUT_ROOT_TOKEN).resolve()


def _seal_authority_projection(
    *, contract_version: str, semantic_fields: Mapping[str, object]
) -> dict[str, object]:
    prefix = _AUTHORITY_PROJECTION_SPECS.get(contract_version)
    if prefix is None:
        raise ValueError("unknown holdout authority projection contract")
    semantic_payload = {
        "contract_version": contract_version,
        **dict(semantic_fields),
    }
    semantic_sha256 = hashlib.sha256(
        contract_version.encode("utf-8")
        + b"\0"
        + canonical_bytes(semantic_payload)
    ).hexdigest()
    without_content = {
        "contract_version": contract_version,
        "artifact_id": f"{prefix}/{semantic_sha256}",
        **dict(semantic_fields),
    }
    projection = {
        **without_content,
        "content_sha256": hashlib.sha256(canonical_bytes(without_content)).hexdigest(),
    }
    return {
        "ref": {
            "id": projection["artifact_id"],
            "content_sha256": projection["content_sha256"],
        },
        "canonical_bytes_b64": base64.b64encode(canonical_bytes(projection)).decode(
            "ascii"
        ),
    }


def _chain(path: Path) -> list[dict[str, object]]:
    path = Path(path)
    if not path.exists():
        return []
    result: list[dict[str, object]] = []
    previous = _ZERO
    raw_lines = path.read_bytes().splitlines()
    for sequence, line in enumerate(raw_lines):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("ledger JSONL is not canonical") from error
        if (
            canonical_bytes(value) != line
            or set(value) != {"contract_version", "event", "event_sha256"}
            or value["contract_version"]
            != "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v1"
        ):
            raise ValueError("ledger envelope invalid")
        event = value["event"]
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
            or event["sequence"] != sequence
            or event["previous_envelope_sha256"] != previous
            or value["event_sha256"]
            != hashlib.sha256(canonical_bytes(event)).hexdigest()
        ):
            raise ValueError("ledger hash chain invalid")
        previous = hashlib.sha256(canonical_bytes(value)).hexdigest()
        result.append(value)
    return result


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    with _named_mutex(_ledger_mutex_name(Path(path))):
        yield


def _append_locked(
    path: Path,
    event: Mapping[str, object],
    *,
    failpoint: str | None = None,
) -> dict[str, object]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    chain = _chain(path)
    previous = (
        _ZERO if not chain else hashlib.sha256(canonical_bytes(chain[-1])).hexdigest()
    )
    body = dict(event)
    if body.get("sequence") != len(chain) or body.get("previous_envelope_sha256") != previous:
        raise ValueError("ledger append predecessor invalid")
    wrapped = {
        "contract_version": "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v1",
        "event": body,
        "event_sha256": hashlib.sha256(canonical_bytes(body)).hexdigest(),
    }
    raw = canonical_bytes(wrapped) + b"\n"
    with path.open("ab") as stream:
        if failpoint == "after_half_write":
            stream.write(raw[: len(raw) // 2])
            stream.flush()
            os._exit(94)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    reloaded = _chain(path)
    if not reloaded or reloaded[-1] != wrapped:
        raise ValueError("ledger reload mismatch")
    return wrapped


def _append(path: Path, event: Mapping[str, object]) -> dict[str, object]:
    with _ledger_lock(path):
        return _append_locked(path, event)


def _append_for_test(
    path: Path, event: Mapping[str, object], *, failpoint: str | None = None
) -> dict[str, object]:
    resolved = Path(path).resolve()
    parts = tuple(part.casefold() for part in resolved.parts)
    required = ("agentguiruntime", "tests", "portfoliohybridbenchmarkv2")
    if not any(parts[index : index + 3] == required for index in range(len(parts) - 2)):
        raise ValueError("test ledger path is not isolated")
    with _ledger_lock(resolved):
        return _append_locked(resolved, event, failpoint=failpoint)


def _canonical_absolute(path: Path, *, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or str(candidate) != os.path.abspath(str(candidate)):
        raise ValueError(f"{label} is not canonical absolute")
    resolved = candidate.resolve(strict=False)
    if resolved != candidate:
        raise ValueError(f"{label} contains an alias or reparse path")
    current = candidate
    while current != current.parent:
        if current.exists() and current.is_symlink():
            raise ValueError(f"{label} contains an alias or reparse path")
        current = current.parent
    return candidate


def holdout_attempt_events_path(*, ledger_root: Path) -> Path:
    """返回唯一的 holdout attempt ledger 路径，不创建或修复文件。"""

    root = _canonical_absolute(Path(ledger_root), label="holdout ledger root")
    return root / "holdout" / "attempt-events.jsonl"


def _sha256_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sealed_exact(value: object, *, fields: set[str], contract: str, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is not an object")
    body = dict(value)
    content = body.pop("content_sha256", None)
    if (
        set(value) != fields
        or body.get("contract_version") != contract
        or not _sha256_text(content)
        or content != hashlib.sha256(canonical_bytes(body)).hexdigest()
    ):
        raise ValueError(f"{label} contract or content hash is invalid")
    return dict(value)


def _native_authorization_ref(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("holdout authorization ref is invalid")
    result = dict(value)
    if (
        set(result) != {"authorization_id", "envelope_sha256", "fixed_authorization_path"}
        or not isinstance(result.get("authorization_id"), str)
        or not result["authorization_id"]
        or not _sha256_text(result.get("envelope_sha256"))
        or not isinstance(result.get("fixed_authorization_path"), str)
        or not result["fixed_authorization_path"]
    ):
        raise ValueError("holdout authorization ref is invalid")
    _canonical_absolute(Path(result["fixed_authorization_path"]), label="holdout authorization path")
    return result


def _native_claim_ref(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("holdout claim ref is invalid")
    result = dict(value)
    if (
        set(result) != {"id", "envelope_sha256"}
        or not isinstance(result.get("id"), str)
        or not result["id"]
        or not _sha256_text(result.get("envelope_sha256"))
    ):
        raise ValueError("holdout claim ref is invalid")
    return result


def _verified_attempt_authority(
    *, backend: object, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str]
) -> dict[str, object]:
    authorization = _native_authorization_ref(authorization_ref)
    claim = _native_claim_ref(claim_ref)
    path = Path(authorization["fixed_authorization_path"])
    try:
        raw = path.read_bytes()
        wrapped = json.loads(raw.decode("utf-8"))
        candidate, digest = authorization_envelope(wrapped["payload"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("holdout attempt authorization anchor is invalid") from error
    if canonical_bytes(wrapped) != raw or wrapped != candidate or digest != authorization["envelope_sha256"]:
        raise ValueError("holdout attempt authorization anchor differs")
    verified = _verify_claim_anchors_read_only(
        backend=backend,
        authorization=wrapped["payload"],
        authorization_ref=authorization,
        ledger_root=Path(backend.ledger_root),
    )
    if verified.get("claim_ref") != claim:
        raise ValueError("holdout attempt claim anchor differs")
    output_root = (
        AUTHORIZED_HOLDOUT_OUTPUT_ROOT
        if getattr(backend, "test_capability", None) is None
        else Path(backend.file_root).parent / "HoldoutOutput"
    )
    attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + str(verified["claim_id"])
            + "\0"
            + authorization["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    return {
        "authorization_ref": authorization,
        "claim_ref": claim,
        "attempt_id": attempt_id,
        "attempt_dir": str((output_root / attempt_id).resolve()),
    }


def _derive_holdout_cleanup_authority(
    *,
    backend: object,
    authorization_ref: Mapping[str, str],
) -> dict[str, object]:
    authorization = _native_authorization_ref(authorization_ref)
    path = Path(authorization["fixed_authorization_path"])
    try:
        raw = path.read_bytes()
        wrapped = json.loads(raw.decode("utf-8"))
        candidate, digest = authorization_envelope(wrapped["payload"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("holdout cleanup authorization anchor is invalid") from error
    if canonical_bytes(wrapped) != raw or wrapped != candidate or digest != authorization["envelope_sha256"]:
        raise ValueError("holdout cleanup authorization anchor differs")
    verified = _verify_claim_anchors_read_only(
        backend=backend,
        authorization=wrapped["payload"],
        authorization_ref=authorization,
        ledger_root=Path(backend.ledger_root),
    )
    claim_ref = verified.get("claim_ref")
    if not isinstance(claim_ref, Mapping):
        raise ValueError("holdout cleanup claim anchor is invalid")
    authority = _verified_attempt_authority(
        backend=backend,
        authorization_ref=authorization,
        claim_ref=claim_ref,
    )
    if authority["attempt_id"] != verified.get("attempt_id"):
        raise ValueError("holdout cleanup attempt identity differs")
    attempt_ref_without_content = {
        "contract_version": "benchmark_v2_holdout_attempt_ref_v1",
        "attempt_id": authority["attempt_id"],
        "authorization_ref": dict(authority["authorization_ref"]),
        "claim_ref": dict(authority["claim_ref"]),
        "partition": "holdout",
        "mode": "actual_models",
        "provider_id": None,
        "safety": dict(SAFETY),
    }
    attempt_ref = {
        **attempt_ref_without_content,
        "content_sha256": hashlib.sha256(
            canonical_bytes(attempt_ref_without_content)
        ).hexdigest(),
    }
    return {
        "authorization_ref": dict(authority["authorization_ref"]),
        "claim_ref": dict(authority["claim_ref"]),
        "attempt_ref": attempt_ref,
        "attempt_dir": str(authority["attempt_dir"]),
    }


def _derive_holdout_cleanup_authority_read_only(
    *, ledger_root: Path, authorization_ref: Mapping[str, str]
) -> dict[str, object]:
    backend = _production_backend()
    if (
        not _production_ledger_root_is_exact(Path(ledger_root))
        or Path(ledger_root) != Path(backend.ledger_root)
    ):
        raise ValueError("production holdout cleanup ledger root is fixed")
    _validate_production_authorization_ref(backend, authorization_ref)
    return _derive_holdout_cleanup_authority(
        backend=backend,
        authorization_ref=authorization_ref,
    )


def _derive_holdout_cleanup_authority_for_test(
    *, backend: object, authorization_ref: Mapping[str, str]
) -> dict[str, object]:
    if getattr(backend, "test_capability", None) is None:
        raise ValueError("explicit test backend capability required")
    exact = _test_backend(
        file_root=Path(backend.file_root),
        registry_root=str(backend.registry_root),
        ledger_root=Path(backend.ledger_root),
        capability=str(backend.test_capability),
    )
    if exact != backend:
        raise ValueError("test holdout backend differs from exact reconstruction")
    return _derive_holdout_cleanup_authority(
        backend=exact,
        authorization_ref=authorization_ref,
    )


def _holdout_attempt_ref(
    value: object, *, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str]
) -> dict[str, object]:
    result = _sealed_exact(
        value,
        fields={"contract_version", "attempt_id", "authorization_ref", "claim_ref", "partition", "mode", "provider_id", "safety", "content_sha256"},
        contract="benchmark_v2_holdout_attempt_ref_v1",
        label="holdout attempt ref",
    )
    if (
        not _sha256_text(result.get("attempt_id"))
        or result.get("authorization_ref") != dict(authorization_ref)
        or result.get("claim_ref") != dict(claim_ref)
        or result.get("partition") != "holdout"
        or result.get("mode") != "actual_models"
        or result.get("provider_id") is not None
        or result.get("safety") != SAFETY
    ):
        raise ValueError("holdout attempt ref binding is invalid")
    return result


def _private_file_ref(value: object, *, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is invalid")
    result = dict(value)
    if (
        set(result) != {"path", "file_sha256", "content_sha256"}
        or not isinstance(result.get("path"), str)
        or not _sha256_text(result.get("file_sha256"))
        or not _sha256_text(result.get("content_sha256"))
    ):
        raise ValueError(f"{label} is invalid")
    _canonical_absolute(Path(result["path"]), label=label)
    return result


def _validated_private_json_file(
    ref: Mapping[str, str], *, contract: str, fields: set[str], label: str
) -> dict[str, object]:
    path = Path(ref["path"])
    try:
        info = path.stat()
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{label} is missing") from error
    reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not path.is_file()
        or path.is_symlink()
        or reparse
        or info.st_nlink != 1
        or path.resolve(strict=True) != path
        or hashlib.sha256(raw).hexdigest() != ref["file_sha256"]
    ):
        raise ValueError(f"{label} is not an exact ordinary file")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} JSON is invalid") from error
    body = _sealed_exact(value, fields=fields, contract=contract, label=label)
    if canonical_bytes(body) != raw or body["content_sha256"] != ref["content_sha256"]:
        raise ValueError(f"{label} bytes or content ref differs")
    return body


def _content_ref(value: object, *, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is invalid")
    result = dict(value)
    if set(result) != {"content_sha256"} or not _sha256_text(result.get("content_sha256")):
        raise ValueError(f"{label} is invalid")
    return result


def _holdout_payload(
    event_kind: str,
    value: object,
    *,
    authorization_ref: Mapping[str, str],
    claim_ref: Mapping[str, str],
) -> dict[str, object]:
    if event_kind not in _HOLDOUT_ATTEMPT_KINDS:
        raise ValueError("holdout attempt event kind is invalid")
    contract = f"benchmark_v2_holdout_attempt_{event_kind}_payload_v1"
    payload = _sealed_exact(
        value,
        fields=_HOLDOUT_PAYLOAD_FIELDS[event_kind],
        contract=contract,
        label="holdout attempt payload",
    )
    attempt = _holdout_attempt_ref(
        payload.get("attempt_ref"),
        authorization_ref=authorization_ref,
        claim_ref=claim_ref,
    )
    attempt_dir = payload.get("attempt_dir")
    if (
        not isinstance(attempt_dir, str)
        or _canonical_absolute(Path(attempt_dir), label="holdout attempt directory") != Path(attempt_dir)
        or payload.get("status") != event_kind
        or payload.get("safety") != SAFETY
    ):
        raise ValueError("holdout attempt payload binding is invalid")
    if event_kind == "body_complete":
        file_ref = _private_file_ref(payload.get("body_file_ref"), label="holdout body file ref")
        if Path(file_ref["path"]) != Path(attempt_dir) / "body.json":
            raise ValueError("holdout body file path is not fixed")
    elif event_kind in {"cleanup", "recovery_cleanup"}:
        _content_ref(payload.get("cleanup_receipt_ref"), label="holdout cleanup receipt ref")
        counts = payload.get("resource_counts")
        if (
            counts != _ZERO_RESOURCE_COUNTS
            or not isinstance(counts, Mapping)
            or any(isinstance(value, bool) or not isinstance(value, int) for value in counts.values())
        ):
            raise ValueError("holdout cleanup is not stable-zero")
        if event_kind == "recovery_cleanup" and payload.get("recovery_reason") != "cleanup_only_after_interrupted_holdout_attempt":
            raise ValueError("holdout recovery reason is invalid")
    elif event_kind == "result":
        file_ref = _private_file_ref(payload.get("result_file_ref"), label="holdout result file ref")
        if Path(file_ref["path"]) != Path(attempt_dir) / "result.json":
            raise ValueError("holdout result file path is not fixed")
        pre_result = payload.get("attempt_ledger_pre_result_ref")
        if not isinstance(pre_result, Mapping) or set(pre_result) != {
            "contract_version", "id", "attempt_ref", "terminal_sequence", "terminal_envelope_sha256", "prefix_sha256"
        } or pre_result.get("contract_version") != "benchmark_v2_holdout_attempt_ledger_pre_result_ref_v1" or pre_result.get("attempt_ref") != attempt or not isinstance(pre_result.get("terminal_sequence"), int) or isinstance(pre_result.get("terminal_sequence"), bool) or not _sha256_text(pre_result.get("terminal_envelope_sha256")) or not _sha256_text(pre_result.get("prefix_sha256")):
            raise ValueError("holdout pre-result ref is invalid")
    return payload


def _assert_derived_attempt(payload: Mapping[str, object], authority: Mapping[str, object]) -> None:
    attempt = payload.get("attempt_ref")
    if (
        not isinstance(attempt, Mapping)
        or attempt.get("attempt_id") != authority["attempt_id"]
        or attempt.get("authorization_ref") != authority["authorization_ref"]
        or attempt.get("claim_ref") != authority["claim_ref"]
        or payload.get("attempt_dir") != authority["attempt_dir"]
    ):
        raise ValueError("holdout attempt identity or directory is not authority-derived")


def _holdout_attempt_mutex_name(path: Path) -> str:
    canonical = _canonical_absolute(Path(path), label="holdout attempt events path")
    return "Local\\portfolio-hybrid-v1-1-benchmark-v2-holdout-attempt-" + hashlib.sha256(
        str(canonical).encode("utf-8")
    ).hexdigest()


def _read_holdout_attempt_chain(
    path: Path, *, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str]
) -> list[dict[str, object]]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw == b"":
        raise ValueError("holdout attempt ledger existing file is empty")
    if b"\r" in raw:
        raise ValueError("holdout attempt ledger must use LF-only JSONL")
    if raw and not raw.endswith(b"\n"):
        raise ValueError("holdout attempt ledger is partial")
    result: list[dict[str, object]] = []
    previous = _ZERO
    state: str | None = None
    expected_attempt: object = None
    expected_dir: object = None
    transitions = {
        None: {"opened"},
        "opened": {"body_complete", "recovery_cleanup"},
        "body_complete": {"cleanup", "recovery_cleanup"},
        "cleanup": {"result"},
        "result": set(),
        "recovery_cleanup": set(),
    }
    for sequence, line in enumerate(raw.splitlines()):
        try:
            envelope = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("holdout attempt ledger JSONL is not canonical") from error
        if (
            canonical_bytes(envelope) != line
            or not isinstance(envelope, Mapping)
            or set(envelope) != {"contract_version", "event", "event_sha256"}
            or envelope.get("contract_version") != _HOLDOUT_ATTEMPT_ENVELOPE
        ):
            raise ValueError("holdout attempt envelope is invalid")
        event = envelope.get("event")
        if not isinstance(event, Mapping) or set(event) != {"partition", "sequence", "event_kind", "previous_envelope_sha256", "event_payload"}:
            raise ValueError("holdout attempt event is invalid")
        kind = event.get("event_kind")
        if (
            event.get("partition") != "holdout"
            or isinstance(event.get("sequence"), bool)
            or not isinstance(event.get("sequence"), int)
            or event.get("sequence") != sequence
            or event.get("previous_envelope_sha256") != previous
            or kind not in transitions[state]
            or envelope.get("event_sha256") != hashlib.sha256(canonical_bytes(event)).hexdigest()
        ):
            raise ValueError("holdout attempt hash chain or transition is invalid")
        payload = _holdout_payload(str(kind), event.get("event_payload"), authorization_ref=authorization_ref, claim_ref=claim_ref)
        if expected_attempt is None:
            expected_attempt, expected_dir = payload["attempt_ref"], payload["attempt_dir"]
        elif payload["attempt_ref"] != expected_attempt or payload["attempt_dir"] != expected_dir:
            raise ValueError("holdout attempt chain binding differs")
        previous = hashlib.sha256(canonical_bytes(envelope)).hexdigest()
        state = str(kind)
        result.append(dict(envelope))
    return result


def _classify_holdout_attempt_events_structure(path: Path) -> str:
    ledger = Path(path)
    if not ledger.exists():
        return "missing"
    try:
        raw = ledger.read_bytes()
    except OSError as error:
        raise RuntimeError("cleanup_indeterminate") from error
    if not raw or b"\r" in raw:
        return "noncanonical"
    if not raw.endswith(b"\n"):
        return "partial"
    lines = raw.split(b"\n")[:-1]
    if not lines or any(not line for line in lines):
        return "noncanonical"

    def reject_nonfinite_json(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    previous = _ZERO
    for sequence, line in enumerate(lines):
        try:
            envelope = json.loads(
                line.decode("utf-8"),
                parse_constant=reject_nonfinite_json,
            )
            canonical = canonical_bytes(envelope)
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return "noncanonical"
        if (
            not isinstance(envelope, Mapping)
            or canonical != line
            or set(envelope) != {"contract_version", "event", "event_sha256"}
            or envelope.get("contract_version") != _HOLDOUT_ATTEMPT_ENVELOPE
        ):
            return "noncanonical"
        event = envelope.get("event")
        if not isinstance(event, Mapping) or set(event) != {
            "partition",
            "sequence",
            "event_kind",
            "previous_envelope_sha256",
            "event_payload",
        }:
            return "noncanonical"
        if (
            isinstance(event.get("sequence"), bool)
            or not isinstance(event.get("sequence"), int)
            or event.get("sequence") != sequence
            or event.get("previous_envelope_sha256") != previous
            or envelope.get("event_sha256")
            != hashlib.sha256(canonical_bytes(event)).hexdigest()
        ):
            return "hash_invalid"
        previous = hashlib.sha256(canonical_bytes(envelope)).hexdigest()
    return "canonical"


def _classify_holdout_attempt_events_structure_read_only(*, ledger_root: Path) -> str:
    backend = _production_backend()
    if (
        not _production_ledger_root_is_exact(Path(ledger_root))
        or Path(ledger_root) != Path(backend.ledger_root)
    ):
        raise ValueError("production holdout cleanup ledger root is fixed")
    return _classify_holdout_attempt_events_structure(
        holdout_attempt_events_path(ledger_root=Path(backend.ledger_root))
    )


def _classify_holdout_attempt_events_structure_for_test(*, backend: object) -> str:
    if getattr(backend, "test_capability", None) is None:
        raise ValueError("explicit test backend capability required")
    exact = _test_backend(
        file_root=Path(backend.file_root),
        registry_root=str(backend.registry_root),
        ledger_root=Path(backend.ledger_root),
        capability=str(backend.test_capability),
    )
    if exact != backend:
        raise ValueError("test holdout backend differs from exact reconstruction")
    return _classify_holdout_attempt_events_structure(
        holdout_attempt_events_path(ledger_root=exact.ledger_root)
    )


def _validate_holdout_chain_artifacts(path: Path, chain: list[dict[str, object]]) -> None:
    if len(chain) >= 2 and chain[1]["event"]["event_kind"] == "body_complete":
        payload = chain[1]["event"]["event_payload"]
        body = _validated_private_json_file(
            payload["body_file_ref"],
            contract="benchmark_v2_holdout_runner_actual_body_v1",
            fields={"contract_version", "attempt_ref", "partition", "screen_group_results", "body_status", "safety", "content_sha256"},
            label="holdout body file",
        )
        if body.get("attempt_ref") != payload["attempt_ref"] or body.get("partition") != "holdout" or not isinstance(body.get("screen_group_results"), list) or body.get("body_status") != "complete" or body.get("safety") != SAFETY:
            raise ValueError("holdout body file binding is invalid")
    if len(chain) == 4 and chain[-1]["event"]["event_kind"] == "result":
        cleanup_envelope = chain[2]
        lines = path.read_bytes().splitlines(keepends=True)
        prefix = b"".join(lines[:3])
        result_payload = chain[3]["event"]["event_payload"]
        expected = {
            "contract_version": "benchmark_v2_holdout_attempt_ledger_pre_result_ref_v1",
            "id": "holdout-attempt-ledger-pre-result/" + hashlib.sha256(b"benchmark-v2-holdout-attempt-ledger-pre-result\0" + prefix).hexdigest(),
            "attempt_ref": result_payload["attempt_ref"],
            "terminal_sequence": 2,
            "terminal_envelope_sha256": hashlib.sha256(canonical_bytes(cleanup_envelope)).hexdigest(),
            "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
        }
        if result_payload.get("attempt_ledger_pre_result_ref") != expected:
            raise ValueError("holdout pre-result ref differs from exact prefix")
        actual = _validated_private_json_file(
            result_payload["result_file_ref"],
            contract="benchmark_v2_holdout_runner_actual_result_v1",
            fields={"contract_version", "attempt_ref", "attempt_dir", "body_ref", "cleanup_receipt_ref", "attempt_ledger_pre_result_ref", "screen_group_count", "status", "safety", "content_sha256"},
            label="holdout result file",
        )
        body_ref = chain[1]["event"]["event_payload"]["body_file_ref"]
        cleanup_ref = cleanup_envelope["event"]["event_payload"]["cleanup_receipt_ref"]
        if actual.get("attempt_ref") != result_payload["attempt_ref"] or actual.get("attempt_dir") != result_payload["attempt_dir"] or actual.get("body_ref") != {"content_sha256": body_ref["content_sha256"]} or actual.get("cleanup_receipt_ref") != cleanup_ref or actual.get("attempt_ledger_pre_result_ref") != expected or isinstance(actual.get("screen_group_count"), bool) or not isinstance(actual.get("screen_group_count"), int) or actual.get("status") != "terminal" or actual.get("safety") != SAFETY:
            raise ValueError("holdout result file binding is invalid")


def validate_holdout_attempt_events(
    *, ledger_root: Path, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str]
) -> list[dict[str, object]]:
    backend = _production_backend()
    if not _production_ledger_root_is_exact(Path(ledger_root)) or Path(ledger_root) != Path(backend.ledger_root):
        raise ValueError("production holdout attempt ledger root is fixed")
    authority = _verified_attempt_authority(backend=backend, authorization_ref=authorization_ref, claim_ref=claim_ref)
    authorization = authority["authorization_ref"]
    claim = authority["claim_ref"]
    chain = _read_holdout_attempt_chain(
        holdout_attempt_events_path(ledger_root=ledger_root),
        authorization_ref=authorization,
        claim_ref=claim,
    )
    for envelope in chain:
        _assert_derived_attempt(envelope["event"]["event_payload"], authority)
    _validate_holdout_chain_artifacts(holdout_attempt_events_path(ledger_root=Path(backend.ledger_root)), chain)
    return chain


def _validate_holdout_attempt_events_for_test(
    *, backend: object, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str]
) -> list[dict[str, object]]:
    if getattr(backend, "test_capability", None) is None:
        raise ValueError("explicit test backend capability required")
    exact = _test_backend(
        file_root=Path(backend.file_root),
        registry_root=str(backend.registry_root),
        ledger_root=Path(backend.ledger_root),
        capability=str(backend.test_capability),
    )
    if exact != backend:
        raise ValueError("test holdout backend differs from exact reconstruction")
    root = exact.ledger_root
    authority = _verified_attempt_authority(backend=exact, authorization_ref=authorization_ref, claim_ref=claim_ref)
    chain = _read_holdout_attempt_chain(
        holdout_attempt_events_path(ledger_root=root),
        authorization_ref=authority["authorization_ref"],
        claim_ref=authority["claim_ref"],
    )
    for envelope in chain:
        _assert_derived_attempt(envelope["event"]["event_payload"], authority)
    _validate_holdout_chain_artifacts(holdout_attempt_events_path(ledger_root=root), chain)
    return chain


def _append_holdout_attempt_event(
    *, backend: object, ledger_root: Path, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str], event_kind: str, event_payload: Mapping[str, object]
) -> dict[str, object]:
    authority = _verified_attempt_authority(backend=backend, authorization_ref=authorization_ref, claim_ref=claim_ref)
    authorization = authority["authorization_ref"]
    claim = authority["claim_ref"]
    path = holdout_attempt_events_path(ledger_root=ledger_root)
    payload = _holdout_payload(event_kind, event_payload, authorization_ref=authorization, claim_ref=claim)
    _assert_derived_attempt(payload, authority)
    with _named_mutex(_holdout_attempt_mutex_name(path)):
        chain = _read_holdout_attempt_chain(path, authorization_ref=authorization, claim_ref=claim)
        if chain and chain[-1]["event"]["event_kind"] in {"result", "recovery_cleanup"}:
            if chain[-1]["event"]["event_kind"] == "recovery_cleanup" and event_kind == "recovery_cleanup" and chain[-1]["event"]["event_payload"] == payload:
                return chain[-1]
            raise ValueError("holdout attempt ledger is terminal")
        current = None if not chain else chain[-1]["event"]["event_kind"]
        allowed = {
            None: {"opened"},
            "opened": {"body_complete", "recovery_cleanup"},
            "body_complete": {"cleanup", "recovery_cleanup"},
            "cleanup": {"result"},
        }
        if event_kind not in allowed.get(current, set()):
            raise ValueError("holdout attempt transition is invalid")
        if event_kind == "body_complete":
            body = _validated_private_json_file(
                payload["body_file_ref"],
                contract="benchmark_v2_holdout_runner_actual_body_v1",
                fields={"contract_version", "attempt_ref", "partition", "screen_group_results", "body_status", "safety", "content_sha256"},
                label="holdout body file",
            )
            if (
                body.get("attempt_ref") != payload["attempt_ref"]
                or body.get("partition") != "holdout"
                or not isinstance(body.get("screen_group_results"), list)
                or body.get("body_status") != "complete"
                or body.get("safety") != SAFETY
            ):
                raise ValueError("holdout body file binding is invalid")
        elif event_kind == "result":
            if len(chain) != 3 or chain[-1]["event"]["event_kind"] != "cleanup":
                raise ValueError("holdout result predecessor is invalid")
            prefix = path.read_bytes()
            cleanup_envelope = chain[-1]
            expected_pre_result = {
                "contract_version": "benchmark_v2_holdout_attempt_ledger_pre_result_ref_v1",
                "id": "holdout-attempt-ledger-pre-result/"
                + hashlib.sha256(b"benchmark-v2-holdout-attempt-ledger-pre-result\0" + prefix).hexdigest(),
                "attempt_ref": payload["attempt_ref"],
                "terminal_sequence": 2,
                "terminal_envelope_sha256": hashlib.sha256(canonical_bytes(cleanup_envelope)).hexdigest(),
                "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
            }
            if payload.get("attempt_ledger_pre_result_ref") != expected_pre_result:
                raise ValueError("holdout pre-result ref differs from exact prefix")
            actual_result = _validated_private_json_file(
                payload["result_file_ref"],
                contract="benchmark_v2_holdout_runner_actual_result_v1",
                fields={"contract_version", "attempt_ref", "attempt_dir", "body_ref", "cleanup_receipt_ref", "attempt_ledger_pre_result_ref", "screen_group_count", "status", "safety", "content_sha256"},
                label="holdout result file",
            )
            body_ref = chain[1]["event"]["event_payload"]["body_file_ref"]
            cleanup_ref = chain[2]["event"]["event_payload"]["cleanup_receipt_ref"]
            if (
                actual_result.get("attempt_ref") != payload["attempt_ref"]
                or actual_result.get("attempt_dir") != payload["attempt_dir"]
                or actual_result.get("body_ref") != {"content_sha256": body_ref["content_sha256"]}
                or actual_result.get("cleanup_receipt_ref") != cleanup_ref
                or actual_result.get("attempt_ledger_pre_result_ref") != expected_pre_result
                or isinstance(actual_result.get("screen_group_count"), bool)
                or not isinstance(actual_result.get("screen_group_count"), int)
                or actual_result.get("status") != "terminal"
                or actual_result.get("safety") != SAFETY
            ):
                raise ValueError("holdout result file binding is invalid")
        previous = _ZERO if not chain else hashlib.sha256(canonical_bytes(chain[-1])).hexdigest()
        event = {
            "partition": "holdout",
            "sequence": len(chain),
            "event_kind": event_kind,
            "previous_envelope_sha256": previous,
            "event_payload": payload,
        }
        envelope = {
            "contract_version": _HOLDOUT_ATTEMPT_ENVELOPE,
            "event": event,
            "event_sha256": hashlib.sha256(canonical_bytes(event)).hexdigest(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        before_size = path.stat().st_size if path.exists() else 0
        try:
            with path.open("ab") as stream:
                stream.write(canonical_bytes(envelope) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            reloaded = _read_holdout_attempt_chain(path, authorization_ref=authorization, claim_ref=claim)
        except Exception:
            # 失败时绝不截断或修复；已有字节保留供独立审查。
            raise
        if len(reloaded) != len(chain) + 1 or reloaded[-1] != envelope or before_size >= path.stat().st_size:
            raise ValueError("holdout attempt ledger reload mismatch")
        return envelope


def _production_holdout_append(event_kind: str, *, ledger_root: Path, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str], event_payload: Mapping[str, object]) -> dict[str, object]:
    backend = _production_backend()
    if not _production_ledger_root_is_exact(Path(ledger_root)) or Path(ledger_root) != Path(backend.ledger_root):
        raise ValueError("production holdout attempt ledger root is fixed")
    return _append_holdout_attempt_event(backend=backend, ledger_root=Path(backend.ledger_root), authorization_ref=authorization_ref, claim_ref=claim_ref, event_kind=event_kind, event_payload=event_payload)


def _test_holdout_append(event_kind: str, *, backend: object, authorization_ref: Mapping[str, str], claim_ref: Mapping[str, str], event_payload: Mapping[str, object]) -> dict[str, object]:
    if getattr(backend, "test_capability", None) is None:
        raise ValueError("explicit test backend capability required")
    exact = _test_backend(file_root=Path(backend.file_root), registry_root=str(backend.registry_root), ledger_root=Path(backend.ledger_root), capability=str(backend.test_capability))
    if exact != backend:
        raise ValueError("test holdout backend differs from exact reconstruction")
    return _append_holdout_attempt_event(backend=exact, ledger_root=exact.ledger_root, authorization_ref=authorization_ref, claim_ref=claim_ref, event_kind=event_kind, event_payload=event_payload)


def append_holdout_attempt_opened(**kwargs: object) -> dict[str, object]:
    return _production_holdout_append("opened", **kwargs)


def append_holdout_attempt_body_complete(**kwargs: object) -> dict[str, object]:
    return _production_holdout_append("body_complete", **kwargs)


def append_holdout_attempt_cleanup(**kwargs: object) -> dict[str, object]:
    return _production_holdout_append("cleanup", **kwargs)


def append_holdout_attempt_result(**kwargs: object) -> dict[str, object]:
    return _production_holdout_append("result", **kwargs)


def append_holdout_attempt_recovery_cleanup(**kwargs: object) -> dict[str, object]:
    return _production_holdout_append("recovery_cleanup", **kwargs)


def _append_holdout_attempt_opened_for_test(**kwargs: object) -> dict[str, object]:
    return _test_holdout_append("opened", **kwargs)


def _append_holdout_attempt_body_complete_for_test(**kwargs: object) -> dict[str, object]:
    return _test_holdout_append("body_complete", **kwargs)


def _append_holdout_attempt_cleanup_for_test(**kwargs: object) -> dict[str, object]:
    return _test_holdout_append("cleanup", **kwargs)


def _append_holdout_attempt_result_for_test(**kwargs: object) -> dict[str, object]:
    return _test_holdout_append("result", **kwargs)


def _append_holdout_attempt_recovery_cleanup_for_test(**kwargs: object) -> dict[str, object]:
    return _test_holdout_append("recovery_cleanup", **kwargs)


def append_regression_event(
    *, ledger_root: Path, event: Mapping[str, object]
) -> dict[str, object]:
    backend = _production_backend()
    if not _production_ledger_root_is_exact(Path(ledger_root)):
        raise ValueError("production regression ledger root is fixed")
    return _append_regression_event(backend.ledger_root, event)


def _append_regression_event(
    ledger_root: Path, event: Mapping[str, object]
) -> dict[str, object]:
    if event.get("partition") != "regression" or event.get("event_type") not in {
        "authorized_genesis",
        "regression_attempt",
        "cleanup",
    }:
        raise ValueError("regression ledger event invalid")
    return _append(Path(ledger_root).resolve() / "regression" / "events.jsonl", event)


def _append_regression_event_for_test(
    *, backend: object, event: Mapping[str, object]
) -> dict[str, object]:
    if getattr(backend, "test_capability", None) is None:
        raise ValueError("explicit test backend capability required")
    return _append_regression_event(Path(backend.ledger_root), event)


def _validate_genesis_ref(
    *,
    file_root: Path,
    ledger_root: Path,
    authorization_ref: Mapping[str, str],
) -> None:
    root = Path(ledger_root)
    if not root.is_absolute() or str(root) != os.path.abspath(str(root)):
        raise ValueError("holdout ledger root is not canonical absolute")
    claim_root = Path(file_root)
    if not claim_root.is_absolute() or str(claim_root) != os.path.abspath(str(claim_root)):
        raise ValueError("holdout claim root is not canonical absolute")
    cid = claim_id(IDENTITY)
    expected = {
        "authorization_id": f"holdout-authorization/{cid}",
        "fixed_authorization_path": str(claim_root / f"{cid}.authorization.json"),
    }
    if (
        set(authorization_ref)
        != {"authorization_id", "envelope_sha256", "fixed_authorization_path"}
        or authorization_ref.get("authorization_id") != expected["authorization_id"]
        or authorization_ref.get("fixed_authorization_path")
        != expected["fixed_authorization_path"]
        or not isinstance(authorization_ref.get("envelope_sha256"), str)
        or len(str(authorization_ref["envelope_sha256"])) != 64
        or any(
            character not in "0123456789abcdef"
            for character in str(authorization_ref["envelope_sha256"])
        )
    ):
        raise ValueError("holdout genesis authorization ref invalid")


def authorize_holdout_genesis(
    *,
    ledger_root: Path,
    claim_identity: Mapping[str, str],
    authorization_ref: Mapping[str, str],
) -> dict[str, object]:
    backend = _production_backend()
    if not _production_ledger_root_is_exact(Path(ledger_root)):
        raise ValueError("production holdout ledger root is not exact")
    _validate_production_authorization_ref(backend, authorization_ref)
    return _authorize_holdout_genesis(
        file_root=backend.file_root,
        ledger_root=backend.ledger_root,
        claim_identity=claim_identity,
        authorization_ref=authorization_ref,
    )


def _validate_production_authorization_ref(
    backend: object, authorization_ref: Mapping[str, str]
) -> dict[str, object]:
    cid = claim_id(IDENTITY)
    path = Path(backend.file_root) / f"{cid}.authorization.json"
    try:
        raw = path.read_bytes()
        wrapped = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("production authorization object is missing or invalid") from error
    if not _file_anchor_exact(path, size=len(raw), raw=raw):
        raise ValueError("production authorization object security is invalid")
    try:
        candidate, digest = authorization_envelope(wrapped["payload"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("production authorization object contract is invalid") from error
    expected = {
        "authorization_id": f"holdout-authorization/{cid}",
        "envelope_sha256": digest,
        "fixed_authorization_path": str(path),
    }
    if (
        canonical_bytes(wrapped) != raw
        or wrapped != candidate
        or dict(authorization_ref) != expected
    ):
        raise ValueError("production authorization object or ref is invalid")
    return wrapped


def _authorize_holdout_genesis_for_test(
    *,
    backend: object,
    claim_identity: Mapping[str, str],
    authorization_ref: Mapping[str, str],
) -> dict[str, object]:
    if getattr(backend, "test_capability", None) is None:
        raise ValueError("explicit test backend capability required")
    return _authorize_holdout_genesis(
        file_root=Path(backend.file_root),
        ledger_root=Path(backend.ledger_root),
        claim_identity=claim_identity,
        authorization_ref=authorization_ref,
    )


def _authorize_holdout_genesis(
    *,
    file_root: Path,
    ledger_root: Path,
    claim_identity: Mapping[str, str],
    authorization_ref: Mapping[str, str],
) -> dict[str, object]:
    if dict(claim_identity) != IDENTITY:
        raise ValueError("holdout genesis authority invalid")
    root = Path(ledger_root)
    _validate_genesis_ref(
        file_root=Path(file_root),
        ledger_root=root,
        authorization_ref=authorization_ref,
    )
    path = root / "holdout" / "events.jsonl"
    with _ledger_lock(path):
        chain = _chain(path)
        expected_payload = {
            "claim_id": claim_id(IDENTITY),
            "authorization_ref": dict(authorization_ref),
            "safety": SAFETY,
        }
        if chain:
            if (
                len(chain) != 1
                or chain[0]["event"]["event_type"] != "authorized_genesis"
                or chain[0]["event"]["event_payload"] != expected_payload
            ):
                raise ValueError("holdout genesis immutable mismatch")
            return chain[0]
        event = {
            "partition": "holdout",
            "sequence": 0,
            "event_type": "authorized_genesis",
            "previous_envelope_sha256": _ZERO,
            "event_payload": {
                "claim_id": claim_id(IDENTITY),
                "authorization_ref": dict(authorization_ref),
                "safety": dict(SAFETY),
            },
        }
        return _append_locked(path, event)


def claim_holdout_once(
    *,
    ledger_root: Path,
    claim_identity: Mapping[str, str],
    authorization_ref: Mapping[str, str],
) -> dict[str, object]:
    backend = _production_backend()
    if (
        not _production_ledger_root_is_exact(Path(ledger_root))
        or dict(claim_identity) != IDENTITY
    ):
        raise ValueError("production holdout roots/identity are fixed")
    wrapped = _validate_production_authorization_ref(backend, authorization_ref)
    return _claim_with_backend(backend=backend, authorization=wrapped["payload"])


def verify_holdout_claim_anchors_for_public_projection(
    *, authorization_ref: Mapping[str, object], ledger_root: Path
) -> dict[str, object]:
    """只读验证 Task 11A 锚点并仅返回无路径公开投影。"""

    import win32security

    try:
        if not isinstance(authorization_ref, Mapping):
            raise ValueError("holdout authorization ref must be an object")
        native_authorization_ref = dict(authorization_ref)
        if set(native_authorization_ref) != {
            "authorization_id",
            "envelope_sha256",
            "fixed_authorization_path",
        } or any(
            not isinstance(native_authorization_ref[field], str)
            for field in native_authorization_ref
        ):
            raise ValueError("holdout authorization ref is not exact")
        backend = _production_backend()
        wrapped = _validate_production_authorization_ref(
            backend, native_authorization_ref
        )
        verified = _verify_claim_anchors_read_only(
            backend=backend,
            authorization=wrapped["payload"],
            authorization_ref=native_authorization_ref,
            ledger_root=Path(ledger_root),
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        win32security.error,
    ):
        raise ValueError("holdout anchor verification failed closed") from None

    authorization_projection = _seal_authority_projection(
        contract_version="benchmark_v2_holdout_authorization_public_projection_v1",
        semantic_fields={
            "authorization_id": verified["authorization_ref"]["authorization_id"],
            "envelope_sha256": verified["authorization_ref"]["envelope_sha256"],
            "claim_id": verified["claim_id"],
            "safety": dict(SAFETY),
        },
    )
    claim_projection = _seal_authority_projection(
        contract_version="benchmark_v2_holdout_claim_public_projection_v1",
        semantic_fields={
            "claim_ref": dict(verified["claim_ref"]),
            "claim_id": verified["claim_id"],
            "attempt_id": verified["attempt_id"],
            "authorization_projection_ref": dict(authorization_projection["ref"]),
            "state": "consumed",
            "safety": dict(SAFETY),
        },
    )
    file_projection = _seal_authority_projection(
        contract_version="benchmark_v2_holdout_file_anchor_public_projection_v1",
        semantic_fields={
            "anchor_kind": "win32_zero_byte_claim_sentinel",
            "claim_id": verified["claim_id"],
            "authorization_envelope_sha256": verified["authorization_ref"][
                "envelope_sha256"
            ],
            "size_bytes": 0,
            "verified": True,
            "safety": dict(SAFETY),
        },
    )
    registry_projection = _seal_authority_projection(
        contract_version="benchmark_v2_holdout_registry_anchor_public_projection_v1",
        semantic_fields={
            "anchor_kind": "hkcu_claim_registry_envelope",
            "claim_id": verified["claim_id"],
            "authorization_envelope_sha256": verified["authorization_ref"][
                "envelope_sha256"
            ],
            "claim_ref": dict(verified["claim_ref"]),
            "envelope_verified": True,
            "state": "consumed",
            "safety": dict(SAFETY),
        },
    )
    without_content = {
        "contract_version": "benchmark_v2_holdout_anchor_verification_result_v1",
        "authorization_ref": dict(verified["authorization_ref"]),
        "claim_ref": dict(verified["claim_ref"]),
        "attempt_id": verified["attempt_id"],
        "authority_projection_envelopes": {
            "authorization_public_projection_envelope": authorization_projection,
            "claim_public_projection_envelope": claim_projection,
            "file_anchor_public_projection_envelope": file_projection,
            "registry_anchor_public_projection_envelope": registry_projection,
        },
        "safety": dict(SAFETY),
    }
    return {
        **without_content,
        "content_sha256": hashlib.sha256(canonical_bytes(without_content)).hexdigest(),
    }


def recover_claim(*, claim_identity: Mapping[str, str]) -> dict[str, object]:
    if dict(claim_identity) != IDENTITY:
        raise ValueError("production holdout identity is fixed")
    backend = _production_backend()
    path = backend.file_root / f"{claim_id(IDENTITY)}.authorization.json"
    if not path.exists():
        return {
            "state": "permanent_refusal",
            "claim_id": claim_id(IDENTITY),
            "safety": dict(SAFETY),
        }
    wrapped = json.loads(path.read_text(encoding="utf-8"))
    return _recover_with_backend(backend=backend, authorization=wrapped["payload"])


__all__ = [
    "append_holdout_attempt_body_complete",
    "append_holdout_attempt_cleanup",
    "append_holdout_attempt_opened",
    "append_holdout_attempt_recovery_cleanup",
    "append_holdout_attempt_result",
    "append_regression_event",
    "authorize_holdout_genesis",
    "claim_holdout_once",
    "recover_claim",
    "holdout_attempt_events_path",
    "validate_holdout_attempt_events",
    "verify_holdout_claim_anchors_for_public_projection",
]
