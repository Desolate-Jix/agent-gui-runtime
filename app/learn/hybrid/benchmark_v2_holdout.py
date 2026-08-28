"""Partitioned Benchmark-v2 ledgers and production holdout claim facade."""

from __future__ import annotations

import hashlib
import json
import os
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
    authorization_envelope,
    canonical_bytes,
    claim_id,
)


_ZERO = "0" * 64


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
    if not root.is_absolute() or str(root) != str(root.resolve()):
        raise ValueError("holdout ledger root is not canonical absolute")
    claim_root = Path(file_root)
    if not claim_root.is_absolute() or str(claim_root) != str(claim_root.resolve()):
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
    root = Path(ledger_root).resolve()
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
    "append_regression_event",
    "authorize_holdout_genesis",
    "claim_holdout_once",
    "recover_claim",
]
