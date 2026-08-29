from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Iterator, Mapping, Sequence
import uuid

from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID
from app.learn.hybrid.benchmark_v2_lifecycle import (
    compose_benchmark_v2_lifecycle_bundle_v3,
    materialize_benchmark_v2_attempt_ledger_projections,
    project_benchmark_v2_attempt_journal,
    project_benchmark_v2_attempt_journal_terminal_event,
    project_benchmark_v2_attempt_lifecycle,
    project_benchmark_v2_cleanup_lifecycle,
    project_benchmark_v2_runner_events,
    project_benchmark_v2_screen_group_lifecycles,
    read_benchmark_v2_attempt_journal,
    select_benchmark_v2_attempt_ledger_horizon,
)
from app.learn.hybrid.benchmark_v2_predictions import (
    materialize_benchmark_v2_accepted_regression_score_input_v2,
    project_benchmark_v2_actual_body,
    project_benchmark_v2_actual_result,
)
from app.learn.hybrid.benchmark_v2_probe_authority import (
    materialize_benchmark_v2_regression_probe_authority,
)
from app.learn.hybrid.benchmark_v2_runtime import (
    get_production_benchmark_v2_runtime,
)
from app.learn.hybrid.benchmark_v2_durable_claim import (
    EXACT_HOLDOUT_COMMAND,
    IDENTITY,
    PRODUCTION_LEDGER_ROOT,
    SAFETY as HOLDOUT_SAFETY,
)
from app.learn.hybrid.benchmark_v2_holdout import (
    AUTHORIZED_HOLDOUT_OUTPUT_ROOT,
    _classify_holdout_attempt_events_structure_read_only,
    _derive_holdout_cleanup_authority_read_only,
    append_holdout_attempt_body_complete,
    append_holdout_attempt_cleanup,
    append_holdout_attempt_opened,
    append_holdout_attempt_recovery_cleanup,
    append_holdout_attempt_result,
    claim_holdout_once,
    holdout_attempt_events_path,
    validate_holdout_attempt_events,
)


_LEDGER_CONTRACT = "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2"
_ATTEMPT_CONTRACT = "benchmark_v2_runner_attempt_ref_v1"
_ATTEMPT_PAYLOAD_CONTRACT = "benchmark_v2_runner_regression_attempt_payload_v1"
_CLEANUP_PAYLOAD_CONTRACT = "benchmark_v2_runner_cleanup_payload_v1"
_RESULT_PAYLOAD_CONTRACT = "benchmark_v2_runner_result_payload_v1"
_ACTUAL_RESULT_CONTRACT = "benchmark_v2_runner_actual_result_v2"
_PRE_RESULT_REF_CONTRACT = "benchmark_v2_runner_ledger_pre_result_ref_v1"
_CLEANUP_RECEIPT_CONTRACT = "benchmark_v2_attempt_cleanup_receipt_v1"
_HOLDOUT_NORMAL_CLEANUP_REASON = "benchmark_v2_holdout_actual_runner_finished"
_HOLDOUT_RECOVERY_CLEANUP_REASON = "cleanup_only_after_interrupted_holdout_attempt"
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
_PROBE_RESULT_V2_FIELDS = {
    "contract_version", "attempt_ref", "attempt_dir", "provider_id", "probe_kind",
    "body_ref", "cleanup_receipt_ref", "lifecycle_probe_receipt_ref", "status",
    "artifact_is_authorization", "execute_binding_enabled", "content_sha256",
}
_PROBE_SUMMARY_V2_FIELDS = {
    "contract_version", "benchmark_release_id", "partition", "probe_kind",
    "collection_policy", "attempts", "status", "artifact_is_authorization",
    "execute_binding_enabled", "content_sha256",
}
_PROBE_RECEIPT_V2_FIELDS = {
    "contract_version", "benchmark_release_id", "partition", "probe_id",
    "attempt_ref", "provider", "probe_kind", "operation_ref",
    "request_in_flight_ref", "trigger_observation", "body_completion_observation",
    "termination_observation", "stable_zero_observation", "cleanup_receipt_ref",
    "observer_identity", "status", "artifact_is_authorization",
    "execute_binding_enabled", "content_sha256",
}
_PROBE_RECEIPT_PROVIDER_FIELDS = {
    "provider_id", "provider_revision", "profile_id", "profile_sha256",
}
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class _ValidatedHoldoutActualModelsInput:
    provider_manifest_path: Path
    authorization_ref_path: Path
    ledger_root: Path
    output_root: Path
    authorization_ref: dict[str, str]


@dataclass(frozen=True)
class _OpenedHoldoutActualModelsAttempt:
    validated: _ValidatedHoldoutActualModelsInput
    attempt_ref: dict[str, object]
    attempt_dir: Path


@dataclass(frozen=True)
class _ValidatedHoldoutCleanupOnlyInput:
    authorization_ref_path: Path
    ledger_root: Path
    authorization_ref: dict[str, str]


@dataclass(frozen=True)
class _PreparedHoldoutCleanupOnly:
    validated: _ValidatedHoldoutCleanupOnlyInput
    attempt_ref: dict[str, object]
    attempt_dir: Path
    claim_ref: dict[str, str]
    structure: str
    chain: list[dict[str, object]] | None


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


def _validate_holdout_actual_models_input(
    argv: Sequence[str],
) -> _ValidatedHoldoutActualModelsInput:
    raw = tuple(argv)
    expected = tuple(EXACT_HOLDOUT_COMMAND[4:])
    if raw != expected:
        raise ValueError("holdout actual-models requires the exact raw token vector")
    if (
        len(expected) != 11
        or expected[0] != "--provider-manifest"
        or expected[2:5] != ("--partition", "holdout", "--actual-models")
        or expected[5] != "--holdout-authorization"
        or expected[7] != "--ledger-root"
        or expected[9] != "--output-root"
    ):
        raise ValueError("frozen holdout command layout is invalid")

    project_root = Path(_PROJECT_ROOT)
    if (
        not project_root.is_absolute()
        or project_root.resolve(strict=True) != project_root
        or _is_reparse(project_root)
    ):
        raise ValueError("compile-time project root is not canonical")

    def resolve_token(token: str, *, label: str) -> Path:
        candidate = project_root.joinpath(*token.split("/"))
        resolved = candidate.resolve(strict=False)
        if candidate != resolved:
            raise ValueError(f"{label} resolves through an alias")
        return candidate

    provider_manifest_path = _require_ordinary_path(
        resolve_token(expected[1], label="holdout provider manifest"),
        name="holdout provider manifest",
        kind="file",
    )
    authorization_ref_path = _require_ordinary_path(
        resolve_token(expected[6], label="holdout authorization ref"),
        name="holdout authorization ref",
        kind="file",
    )
    ledger_root = _require_ordinary_path(
        resolve_token(expected[8], label="holdout ledger root"),
        name="holdout ledger root",
        kind="directory",
    )
    output_root = _require_ordinary_path(
        resolve_token(expected[10], label="holdout output root"),
        name="holdout output root",
        kind="pending",
    )
    if ledger_root != Path(PRODUCTION_LEDGER_ROOT):
        raise ValueError("holdout ledger root is not the fixed production root")
    if output_root != Path(AUTHORIZED_HOLDOUT_OUTPUT_ROOT):
        raise ValueError("holdout output root is not authorized")
    if output_root.exists() or _is_reparse(output_root):
        _require_ordinary_path(
            output_root,
            name="holdout output root",
            kind="directory",
        )
    else:
        _require_ordinary_path(
            output_root.parent,
            name="holdout output root parent",
            kind="directory",
        )

    try:
        raw_authorization_ref = authorization_ref_path.read_bytes()
        decoded = json.loads(raw_authorization_ref.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("holdout authorization ref is not exact canonical JSON") from error
    if (
        not isinstance(decoded, Mapping)
        or _canonical_bytes(decoded) != raw_authorization_ref
        or set(decoded)
        != {"authorization_id", "envelope_sha256", "fixed_authorization_path"}
    ):
        raise ValueError("holdout authorization ref is not exact canonical JSON")
    authorization_ref = dict(decoded)
    frozen_claim_id = hashlib.sha256(_canonical_bytes(IDENTITY)).hexdigest()
    envelope_sha256 = authorization_ref.get("envelope_sha256")
    fixed_path_raw = authorization_ref.get("fixed_authorization_path")
    if (
        authorization_ref.get("authorization_id")
        != f"holdout-authorization/{frozen_claim_id}"
        or not isinstance(envelope_sha256, str)
        or len(envelope_sha256) != 64
        or any(character not in "0123456789abcdef" for character in envelope_sha256)
        or not isinstance(fixed_path_raw, str)
        or not fixed_path_raw
    ):
        raise ValueError("holdout authorization ref shape is invalid")
    fixed_path = Path(fixed_path_raw)
    if (
        not fixed_path.is_absolute()
        or str(fixed_path) != fixed_path_raw
        or fixed_path.resolve(strict=False) != fixed_path
        or fixed_path.name != f"{frozen_claim_id}.authorization.json"
    ):
        raise ValueError("holdout authorization ref fixed path is invalid")
    _require_ordinary_path(
        fixed_path,
        name="holdout authorization fixed path",
        kind="pending",
    )
    return _ValidatedHoldoutActualModelsInput(
        provider_manifest_path=provider_manifest_path,
        authorization_ref_path=authorization_ref_path,
        ledger_root=ledger_root,
        output_root=output_root,
        authorization_ref={
            "authorization_id": str(authorization_ref["authorization_id"]),
            "envelope_sha256": envelope_sha256,
            "fixed_authorization_path": fixed_path_raw,
        },
    )


def _validate_holdout_cleanup_only_input(
    argv: Sequence[str],
) -> _ValidatedHoldoutCleanupOnlyInput:
    raw = tuple(argv)
    expected = (
        "--cleanup-only",
        "--holdout-authorization",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json",
        "--ledger-root",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger",
    )
    if raw != expected:
        raise ValueError("holdout cleanup-only requires the exact raw token vector")
    project_root = Path(_PROJECT_ROOT)
    if (
        not project_root.is_absolute()
        or project_root.resolve(strict=True) != project_root
        or _is_reparse(project_root)
    ):
        raise ValueError("compile-time project root is not canonical")

    def resolve_token(token: str, *, label: str) -> Path:
        candidate = project_root.joinpath(*token.split("/"))
        resolved = candidate.resolve(strict=False)
        if candidate != resolved:
            raise ValueError(f"{label} resolves through an alias")
        return candidate

    authorization_ref_path = _require_ordinary_path(
        resolve_token(expected[2], label="holdout cleanup authorization ref"),
        name="holdout cleanup authorization ref",
        kind="file",
    )
    ledger_root = _require_ordinary_path(
        resolve_token(expected[4], label="holdout cleanup ledger root"),
        name="holdout cleanup ledger root",
        kind="directory",
    )
    if ledger_root != Path(PRODUCTION_LEDGER_ROOT):
        raise ValueError("holdout cleanup ledger root is not the fixed production root")
    try:
        raw_ref = authorization_ref_path.read_bytes()
        decoded = json.loads(raw_ref.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("holdout cleanup authorization ref is invalid") from error
    if (
        not isinstance(decoded, Mapping)
        or _canonical_bytes(decoded) != raw_ref
        or set(decoded)
        != {"authorization_id", "envelope_sha256", "fixed_authorization_path"}
    ):
        raise ValueError("holdout cleanup authorization ref is invalid")
    claim_id = hashlib.sha256(_canonical_bytes(IDENTITY)).hexdigest()
    envelope_sha256 = decoded.get("envelope_sha256")
    fixed_path_raw = decoded.get("fixed_authorization_path")
    if (
        decoded.get("authorization_id") != f"holdout-authorization/{claim_id}"
        or not isinstance(envelope_sha256, str)
        or len(envelope_sha256) != 64
        or any(character not in "0123456789abcdef" for character in envelope_sha256)
        or not isinstance(fixed_path_raw, str)
        or not fixed_path_raw
    ):
        raise ValueError("holdout cleanup authorization ref shape is invalid")
    fixed_path = Path(fixed_path_raw)
    if (
        not fixed_path.is_absolute()
        or str(fixed_path) != fixed_path_raw
        or fixed_path.resolve(strict=False) != fixed_path
        or fixed_path.name != f"{claim_id}.authorization.json"
    ):
        raise ValueError("holdout cleanup authorization fixed path is invalid")
    _require_ordinary_path(
        fixed_path,
        name="holdout cleanup authorization fixed path",
        kind="pending",
    )
    return _ValidatedHoldoutCleanupOnlyInput(
        authorization_ref_path=authorization_ref_path,
        ledger_root=ledger_root,
        authorization_ref={
            "authorization_id": str(decoded["authorization_id"]),
            "envelope_sha256": envelope_sha256,
            "fixed_authorization_path": fixed_path_raw,
        },
    )


def _open_holdout_actual_models_attempt(
    validated: _ValidatedHoldoutActualModelsInput,
) -> _OpenedHoldoutActualModelsAttempt:
    if not isinstance(validated, _ValidatedHoldoutActualModelsInput):
        raise ValueError("holdout attempt requires already validated inputs")
    claimed = claim_holdout_once(
        ledger_root=validated.ledger_root,
        claim_identity=IDENTITY,
        authorization_ref=validated.authorization_ref,
    )
    claim_id = hashlib.sha256(_canonical_bytes(IDENTITY)).hexdigest()
    expected_attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + validated.authorization_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    if not isinstance(claimed, Mapping):
        raise ValueError("holdout claim result is invalid")
    claim_result = dict(claimed)
    claim_ref = claim_result.get("claim_ref")
    if (
        set(claim_result)
        != {
            "state",
            "claim_id",
            "attempt_id",
            "claim_ref",
            "newly_created",
            "safety",
        }
        or claim_result.get("state") != "consumed"
        or claim_result.get("newly_created") is not True
        or claim_result.get("claim_id") != claim_id
        or claim_result.get("attempt_id") != expected_attempt_id
        or claim_result.get("safety") != HOLDOUT_SAFETY
        or not isinstance(claim_ref, Mapping)
        or set(claim_ref) != {"id", "envelope_sha256"}
        or claim_ref.get("id") != f"holdout-claim/{claim_id}"
        or not isinstance(claim_ref.get("envelope_sha256"), str)
        or len(str(claim_ref.get("envelope_sha256"))) != 64
        or any(
            character not in "0123456789abcdef"
            for character in str(claim_ref.get("envelope_sha256"))
        )
    ):
        raise ValueError("holdout claim is not the exact unique first use")
    native_claim_ref = {
        "id": str(claim_ref["id"]),
        "envelope_sha256": str(claim_ref["envelope_sha256"]),
    }

    if validated.output_root.exists() or _is_reparse(validated.output_root):
        _require_ordinary_path(
            validated.output_root,
            name="holdout output root",
            kind="directory",
        )
    else:
        _require_ordinary_path(
            validated.output_root.parent,
            name="holdout output root parent",
            kind="directory",
        )
        validated.output_root.mkdir()
        _require_ordinary_path(
            validated.output_root,
            name="holdout output root",
            kind="directory",
        )
    attempt_dir = validated.output_root / expected_attempt_id
    if (
        attempt_dir.parent != validated.output_root
        or attempt_dir.name != expected_attempt_id
        or attempt_dir.exists()
        or _is_reparse(attempt_dir)
    ):
        raise ValueError("holdout attempt directory is not a new exact child")
    attempt_dir.mkdir()
    if (
        not attempt_dir.is_dir()
        or _is_reparse(attempt_dir)
        or attempt_dir.resolve(strict=True) != attempt_dir
    ):
        raise ValueError("holdout attempt directory is not canonical ordinary storage")

    attempt_ref = _seal(
        {
            "contract_version": "benchmark_v2_holdout_attempt_ref_v1",
            "attempt_id": expected_attempt_id,
            "authorization_ref": deepcopy(validated.authorization_ref),
            "claim_ref": native_claim_ref,
            "partition": "holdout",
            "mode": "actual_models",
            "provider_id": None,
            "safety": deepcopy(HOLDOUT_SAFETY),
        }
    )
    opened_payload = _seal(
        {
            "contract_version": "benchmark_v2_holdout_attempt_opened_payload_v1",
            "attempt_ref": attempt_ref,
            "attempt_dir": str(attempt_dir),
            "status": "opened",
            "safety": deepcopy(HOLDOUT_SAFETY),
        }
    )
    opened_event = {
        "partition": "holdout",
        "sequence": 0,
        "event_kind": "opened",
        "previous_envelope_sha256": _ZERO_SHA256,
        "event_payload": opened_payload,
    }
    expected_opened_envelope = {
        "contract_version": "benchmark_v2_holdout_attempt_event_envelope_v1",
        "event": opened_event,
        "event_sha256": hashlib.sha256(_canonical_bytes(opened_event)).hexdigest(),
    }
    appended = append_holdout_attempt_opened(
        ledger_root=validated.ledger_root,
        authorization_ref=validated.authorization_ref,
        claim_ref=native_claim_ref,
        event_payload=opened_payload,
    )
    if appended != expected_opened_envelope:
        raise ValueError("holdout opened append differs from the exact envelope")
    reopened = validate_holdout_attempt_events(
        ledger_root=validated.ledger_root,
        authorization_ref=validated.authorization_ref,
        claim_ref=native_claim_ref,
    )
    if reopened != [expected_opened_envelope]:
        raise ValueError("holdout opened event was not durably reopened as the exact chain")
    return _OpenedHoldoutActualModelsAttempt(
        validated=validated,
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )


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


def _write_holdout_compact_json_create(
    path: Path, value: Mapping[str, object]
) -> None:
    destination = Path(path).resolve()
    with destination.open("xb") as stream:
        stream.write(_canonical_bytes(value))
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


def _write_pretty_json_create_or_identical(
    path: Path, value: Mapping[str, object]
) -> None:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    try:
        with destination.open("xb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        with destination.open("rb") as stream:
            if stream.read() != expected:
                raise ValueError(
                    f"existing {destination.name} differs from authoritative bytes"
                )


def _file_ref(path: Path, value: Mapping[str, object]) -> dict[str, object]:
    resolved = Path(path).resolve()
    return {
        "path": str(resolved),
        "file_sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "content_sha256": str(value["content_sha256"]),
    }


def _read_ledger_structure(path: Path) -> list[dict[str, object]]:
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
    return result


def _read_ledger(path: Path) -> list[dict[str, object]]:
    result = _read_ledger_structure(path)
    ledger = Path(path).resolve()
    raw_lines = ledger.read_bytes().split(b"\n")[:-1] if ledger.exists() else []
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
    result = _sealed_mapping(value, name="probe result v2")
    expected_kind = str(attempt_ref.get("mode", "")).removesuffix("_probe")
    if (
        set(result) != _PROBE_RESULT_V2_FIELDS
        or result.get("contract_version") != "benchmark_v2_runner_probe_result_v2"
        or result.get("attempt_ref") != dict(attempt_ref)
        or result.get("attempt_dir") != str(Path(attempt_dir).resolve())
        or result.get("provider_id") != attempt_ref.get("provider_id")
        or result.get("probe_kind") != expected_kind
        or result.get("body_ref")
        != {"content_sha256": body_ref.get("content_sha256")}
        or result.get("cleanup_receipt_ref")
        != {"content_sha256": cleanup_ref.get("content_sha256")}
        or not _valid_probe_receipt_ref(result.get("lifecycle_probe_receipt_ref"))
        or result.get("status") != "terminal"
        or result.get("artifact_is_authorization") is not False
        or result.get("execute_binding_enabled") is not False
    ):
        raise ValueError("probe result lineage is invalid")
    receipt, receipt_bytes = _read_finalized_probe_receipt(
        Path(attempt_dir).resolve() / "lifecycle-probe-receipt.json",
        attempt_ref=attempt_ref,
        provider_id=str(attempt_ref["provider_id"]),
        probe_kind=expected_kind,
        cleanup_ref=cleanup_ref,
    )
    if result.get("lifecycle_probe_receipt_ref") != {
        "contract_version": "benchmark_v2_lifecycle_probe_receipt_v2",
        "file_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "content_sha256": receipt["content_sha256"],
    }:
        raise ValueError("probe result lifecycle receipt lineage is invalid")


def _valid_probe_receipt_ref(value: object) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == {"contract_version", "file_sha256", "content_sha256"}
        and value.get("contract_version") == "benchmark_v2_lifecycle_probe_receipt_v2"
        and all(
            isinstance(value.get(name), str)
            and len(str(value[name])) == 64
            and str(value[name]) == str(value[name]).lower()
            and all(ch in "0123456789abcdef" for ch in str(value[name]))
            for name in ("file_sha256", "content_sha256")
        )
    )


def _valid_lower_sha(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _validate_finalized_probe_receipt_projection(
    value: object,
    *,
    attempt_ref: Mapping[str, object],
    provider_id: str,
    probe_kind: str,
    cleanup_ref: Mapping[str, object],
) -> dict[str, object]:
    receipt = _sealed_mapping(value, name="lifecycle probe receipt v2")
    if (
        set(receipt) != _PROBE_RECEIPT_V2_FIELDS
        or receipt.get("contract_version") != "benchmark_v2_lifecycle_probe_receipt_v2"
        or receipt.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or receipt.get("partition") != "regression"
        or receipt.get("probe_id")
        != f"probe/{provider_id}/{probe_kind}/{attempt_ref['content_sha256']}"
        or receipt.get("attempt_ref") != dict(attempt_ref)
        or receipt.get("probe_kind") != probe_kind
        or receipt.get("status") != "PASS"
        or receipt.get("artifact_is_authorization") is not False
        or receipt.get("execute_binding_enabled") is not False
    ):
        raise ValueError("lifecycle probe receipt v2 is not closed")
    provider = receipt.get("provider")
    if (
        not isinstance(provider, Mapping)
        or set(provider) != _PROBE_RECEIPT_PROVIDER_FIELDS
        or provider.get("provider_id") != provider_id
        or not isinstance(provider.get("provider_revision"), str)
        or not provider["provider_revision"]
        or not isinstance(provider.get("profile_id"), str)
        or not provider["profile_id"]
        or not _valid_lower_sha(provider.get("profile_sha256"))
    ):
        raise ValueError("lifecycle probe provider lineage differs")
    # D2 语义只由生产 Runtime 的 finalizer 证明；Runner 仅固定 D3 投影与当前 lineage。
    if (
        receipt.get("cleanup_receipt_ref")
        != {"content_sha256": cleanup_ref.get("content_sha256")}
        or not _valid_lower_sha(cleanup_ref.get("content_sha256"))
    ):
        raise ValueError("lifecycle probe cleanup lineage differs")
    return receipt


def _read_finalized_probe_receipt(
    path: Path,
    *,
    attempt_ref: Mapping[str, object],
    provider_id: str,
    probe_kind: str,
    cleanup_ref: Mapping[str, object],
) -> tuple[dict[str, object], bytes]:
    raw = Path(path).read_bytes()
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("lifecycle probe receipt is not canonical") from error
    receipt = _validate_finalized_probe_receipt_projection(
        decoded,
        attempt_ref=attempt_ref,
        provider_id=provider_id,
        probe_kind=probe_kind,
        cleanup_ref=cleanup_ref,
    )
    expected = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    if raw != expected:
        raise ValueError("lifecycle probe receipt is not canonical pretty-LF")
    return receipt, raw


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
    expected_partition: str = "regression",
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
        or group.get("partition") != expected_partition
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
    value: object,
    *,
    group: Mapping[str, object],
    expected_partition: str = "regression",
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
        or projection.get("partition") != expected_partition
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


def _reopen_holdout_transition(
    *,
    opened: _OpenedHoldoutActualModelsAttempt,
    event_kind: str,
    event_payload: Mapping[str, object],
) -> list[dict[str, object]]:
    appenders = {
        "body_complete": append_holdout_attempt_body_complete,
        "cleanup": append_holdout_attempt_cleanup,
        "result": append_holdout_attempt_result,
    }
    appender = appenders.get(event_kind)
    if appender is None:
        raise ValueError("holdout transition kind is invalid")
    claim_ref = opened.attempt_ref["claim_ref"]
    assert isinstance(claim_ref, Mapping)
    appended = appender(
        ledger_root=opened.validated.ledger_root,
        authorization_ref=opened.validated.authorization_ref,
        claim_ref=claim_ref,
        event_payload=event_payload,
    )
    reopened = validate_holdout_attempt_events(
        ledger_root=opened.validated.ledger_root,
        authorization_ref=opened.validated.authorization_ref,
        claim_ref=claim_ref,
    )
    expected_kinds = {
        "body_complete": ["opened", "body_complete"],
        "cleanup": ["opened", "body_complete", "cleanup"],
        "result": ["opened", "body_complete", "cleanup", "result"],
    }[event_kind]
    if (
        [item.get("event", {}).get("event_kind") for item in reopened]
        != expected_kinds
        or not reopened
        or reopened[-1] != appended
    ):
        raise ValueError("holdout transition was not durably reopened")
    return reopened


def _finish_holdout_actual_models_attempt(
    runtime: object,
    *,
    opened: _OpenedHoldoutActualModelsAttempt,
    append_normal_cleanup: bool,
) -> tuple[dict[str, object], dict[str, str] | None, list[dict[str, object]] | None]:
    cleanup = _validate_cleanup_receipt(
        runtime.cleanup_attempt(
            attempt=deepcopy(opened.attempt_ref),
            reason=_HOLDOUT_NORMAL_CLEANUP_REASON,
        ),
        attempt_ref=opened.attempt_ref,
        require_effect_refs=append_normal_cleanup,
    )
    if cleanup.get("reason") != _HOLDOUT_NORMAL_CLEANUP_REASON:
        raise ValueError("holdout cleanup receipt reason differs")
    counts = _require_zero_counts(runtime)
    if cleanup.get("resource_counts") != counts:
        raise ValueError("holdout cleanup receipt differs from fresh stable zero")
    cleanup_path = opened.attempt_dir / "cleanup.json"
    _write_json_create_or_identical(cleanup_path, cleanup)
    cleanup_ref = _content_ref(cleanup, name="holdout cleanup receipt")
    if not append_normal_cleanup:
        return cleanup, None, None
    cleanup_payload = _seal(
        {
            "contract_version": "benchmark_v2_holdout_attempt_cleanup_payload_v1",
            "attempt_ref": deepcopy(opened.attempt_ref),
            "attempt_dir": str(opened.attempt_dir),
            "status": "cleanup",
            "cleanup_receipt_ref": cleanup_ref,
            "resource_counts": counts,
            "safety": deepcopy(HOLDOUT_SAFETY),
        }
    )
    reopened = _reopen_holdout_transition(
        opened=opened,
        event_kind="cleanup",
        event_payload=cleanup_payload,
    )
    return cleanup, cleanup_ref, reopened


def _holdout_pre_result_ref(
    *,
    opened: _OpenedHoldoutActualModelsAttempt,
    cleanup_chain: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if (
        len(cleanup_chain) != 3
        or cleanup_chain[-1].get("event", {}).get("event_kind") != "cleanup"
    ):
        raise ValueError("holdout cleanup chain is not complete")
    ledger_path = holdout_attempt_events_path(
        ledger_root=opened.validated.ledger_root
    )
    raw_prefix = Path(ledger_path).read_bytes()
    cleanup_envelope = cleanup_chain[-1]
    if not raw_prefix.endswith(b"\n") or raw_prefix != b"".join(
        _canonical_bytes(item) + b"\n" for item in cleanup_chain
    ):
        raise ValueError("holdout pre-result ledger prefix is not exact")
    return {
        "contract_version": "benchmark_v2_holdout_attempt_ledger_pre_result_ref_v1",
        "id": "holdout-attempt-ledger-pre-result/"
        + hashlib.sha256(
            b"benchmark-v2-holdout-attempt-ledger-pre-result\0" + raw_prefix
        ).hexdigest(),
        "attempt_ref": deepcopy(opened.attempt_ref),
        "terminal_sequence": 2,
        "terminal_envelope_sha256": hashlib.sha256(
            _canonical_bytes(cleanup_envelope)
        ).hexdigest(),
        "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
    }


def _run_holdout_actual_models(
    *,
    validated: _ValidatedHoldoutActualModelsInput,
    runtime: object,
) -> dict[str, object]:
    manifest = runtime.load_provider_manifest(path=validated.provider_manifest_path)
    if not isinstance(manifest, Mapping):
        raise ValueError("holdout provider manifest projection must be an object")
    provider_corpus_ref = manifest.get("provider_corpus_ref")
    if not isinstance(provider_corpus_ref, Mapping):
        raise ValueError("holdout provider manifest corpus lineage is unavailable")
    opened = _open_holdout_actual_models_attempt(validated)
    primary: BaseException | None = None
    body: dict[str, object] | None = None
    body_ref: dict[str, str] | None = None
    body_complete_durable = False
    try:
        projections: list[dict[str, object]] = []
        identities: set[tuple[str, str]] = set()
        screen_group_ids: set[str] = set()
        case_ids: set[str] = set()
        owner = runtime.prepare_screen_groups(
            provider_manifest=manifest,
            partition="holdout",
            attempt_ref=deepcopy(opened.attempt_ref),
            attempt_dir=opened.attempt_dir,
        )
        with owner as groups:
            for raw_group in groups:
                group, identity, group_case_ids = _validate_actual_group(
                    raw_group,
                    attempt_ref=opened.attempt_ref,
                    provider_corpus_ref=provider_corpus_ref,
                    expected_partition="holdout",
                )
                if (
                    identity in identities
                    or identity[0] in screen_group_ids
                    or case_ids.intersection(group_case_ids)
                    or len(identities) >= 12
                ):
                    raise ValueError("holdout runner requires 12 unique screen groups")
                identities.add(identity)
                screen_group_ids.add(identity[0])
                case_ids.update(group_case_ids)
                projections.append(
                    _validate_actual_projection(
                        runtime.run_actual_screen_group(
                            provider_group=group,
                            attempt_ref=deepcopy(opened.attempt_ref),
                            attempt_dir=opened.attempt_dir,
                        ),
                        group=group,
                        expected_partition="holdout",
                    )
                )
        if len(identities) != 12 or len(screen_group_ids) != 12 or len(case_ids) != 60:
            raise ValueError("holdout runner requires 12 unique screen groups")
        body = _seal(
            {
                "contract_version": "benchmark_v2_holdout_runner_actual_body_v1",
                "attempt_ref": deepcopy(opened.attempt_ref),
                "partition": "holdout",
                "screen_group_results": projections,
                "body_status": "complete",
                "safety": deepcopy(HOLDOUT_SAFETY),
            }
        )
        body_path = opened.attempt_dir / "body.json"
        _write_holdout_compact_json_create(body_path, body)
        private_body_ref = _file_ref(body_path, body)
        body_ref = _content_ref(body, name="holdout body")
        body_payload = _seal(
            {
                "contract_version": "benchmark_v2_holdout_attempt_body_complete_payload_v1",
                "attempt_ref": deepcopy(opened.attempt_ref),
                "attempt_dir": str(opened.attempt_dir),
                "status": "body_complete",
                "body_file_ref": private_body_ref,
                "safety": deepcopy(HOLDOUT_SAFETY),
            }
        )
        _reopen_holdout_transition(
            opened=opened,
            event_kind="body_complete",
            event_payload=body_payload,
        )
        body_complete_durable = True
    except BaseException as error:
        primary = error

    cleanup: dict[str, object] | None = None
    cleanup_ref: dict[str, str] | None = None
    cleanup_chain: list[dict[str, object]] | None = None
    try:
        cleanup, cleanup_ref, cleanup_chain = _finish_holdout_actual_models_attempt(
            runtime,
            opened=opened,
            append_normal_cleanup=body_complete_durable,
        )
    except BaseException as cleanup_error:
        if primary is not None:
            raise BaseExceptionGroup(
                "benchmark holdout actual body and cleanup failed",
                [primary, cleanup_error],
            )
        raise
    if primary is not None:
        raise primary
    if body is None or body_ref is None or cleanup is None or cleanup_ref is None or cleanup_chain is None:
        raise RuntimeError("holdout attempt evidence is incomplete")

    pre_result_ref = _holdout_pre_result_ref(
        opened=opened,
        cleanup_chain=cleanup_chain,
    )
    result = _seal(
        {
            "contract_version": "benchmark_v2_holdout_runner_actual_result_v1",
            "attempt_ref": deepcopy(opened.attempt_ref),
            "attempt_dir": str(opened.attempt_dir),
            "body_ref": body_ref,
            "cleanup_receipt_ref": cleanup_ref,
            "attempt_ledger_pre_result_ref": pre_result_ref,
            "screen_group_count": 12,
            "status": "terminal",
            "safety": deepcopy(HOLDOUT_SAFETY),
        }
    )
    result_path = opened.attempt_dir / "result.json"
    _write_holdout_compact_json_create(result_path, result)
    result_payload = _seal(
        {
            "contract_version": "benchmark_v2_holdout_attempt_result_payload_v1",
            "attempt_ref": deepcopy(opened.attempt_ref),
            "attempt_dir": str(opened.attempt_dir),
            "status": "result",
            "result_file_ref": _file_ref(result_path, result),
            "attempt_ledger_pre_result_ref": pre_result_ref,
            "safety": deepcopy(HOLDOUT_SAFETY),
        }
    )
    _reopen_holdout_transition(
        opened=opened,
        event_kind="result",
        event_payload=result_payload,
    )
    return result


def _prepare_holdout_cleanup_only(
    validated: _ValidatedHoldoutCleanupOnlyInput,
) -> _PreparedHoldoutCleanupOnly:
    authority = _derive_holdout_cleanup_authority_read_only(
        ledger_root=validated.ledger_root,
        authorization_ref=validated.authorization_ref,
    )
    if not isinstance(authority, Mapping) or set(authority) != {
        "authorization_ref",
        "claim_ref",
        "attempt_ref",
        "attempt_dir",
    }:
        raise ValueError("holdout cleanup authority is invalid")
    claim_ref_raw = authority.get("claim_ref")
    if (
        authority.get("authorization_ref") != validated.authorization_ref
        or not isinstance(claim_ref_raw, Mapping)
        or set(claim_ref_raw) != {"id", "envelope_sha256"}
    ):
        raise ValueError("holdout cleanup authority binding differs")
    claim_ref = {name: str(value) for name, value in claim_ref_raw.items()}
    attempt_ref = _sealed_mapping(
        authority.get("attempt_ref"), name="holdout cleanup attempt ref"
    )
    expected_attempt_fields = {
        "contract_version",
        "attempt_id",
        "authorization_ref",
        "claim_ref",
        "partition",
        "mode",
        "provider_id",
        "safety",
        "content_sha256",
    }
    attempt_id = attempt_ref.get("attempt_id")
    expected_dir = (
        Path(AUTHORIZED_HOLDOUT_OUTPUT_ROOT) / str(attempt_id)
    ).resolve()
    attempt_dir_raw = authority.get("attempt_dir")
    if (
        set(attempt_ref) != expected_attempt_fields
        or attempt_ref.get("contract_version")
        != "benchmark_v2_holdout_attempt_ref_v1"
        or not _valid_lower_sha(attempt_id)
        or attempt_ref.get("authorization_ref") != validated.authorization_ref
        or attempt_ref.get("claim_ref") != claim_ref
        or attempt_ref.get("partition") != "holdout"
        or attempt_ref.get("mode") != "actual_models"
        or attempt_ref.get("provider_id") is not None
        or attempt_ref.get("safety") != HOLDOUT_SAFETY
        or not isinstance(attempt_dir_raw, (str, Path))
        or Path(attempt_dir_raw) != expected_dir
    ):
        raise ValueError("holdout cleanup derived attempt authority differs")
    structure = _classify_holdout_attempt_events_structure_read_only(
        ledger_root=validated.ledger_root
    )
    allowed_structures = {
        "canonical",
        "missing",
        "partial",
        "noncanonical",
        "hash_invalid",
    }
    if structure not in allowed_structures:
        raise RuntimeError("cleanup_indeterminate")
    chain: list[dict[str, object]] | None = None
    if structure == "canonical":
        chain = validate_holdout_attempt_events(
            ledger_root=validated.ledger_root,
            authorization_ref=validated.authorization_ref,
            claim_ref=claim_ref,
        )
        if not chain:
            raise ValueError("holdout cleanup canonical ledger is empty")
        tail = chain[-1].get("event", {}).get("event_kind")
        if tail in {"cleanup", "result"}:
            raise ValueError("holdout cleanup normal terminal tail is ineligible")
        if tail not in {"opened", "body_complete", "recovery_cleanup"}:
            raise ValueError("holdout cleanup attempt tail is ineligible")
        payload = chain[-1].get("event", {}).get("event_payload")
        if (
            not isinstance(payload, Mapping)
            or payload.get("attempt_ref") != attempt_ref
            or payload.get("attempt_dir") != str(expected_dir)
        ):
            raise ValueError("holdout cleanup event authority differs")
    return _PreparedHoldoutCleanupOnly(
        validated=validated,
        attempt_ref=attempt_ref,
        attempt_dir=expected_dir,
        claim_ref=claim_ref,
        structure=structure,
        chain=chain,
    )


def _run_holdout_cleanup_only(
    *, prepared: _PreparedHoldoutCleanupOnly, runtime: object
) -> dict[str, object]:
    try:
        cleanup = _validate_cleanup_receipt(
            runtime.cleanup_attempt(
                attempt=deepcopy(prepared.attempt_ref),
                reason=_HOLDOUT_RECOVERY_CLEANUP_REASON,
            ),
            attempt_ref=prepared.attempt_ref,
            require_effect_refs=False,
        )
        if cleanup.get("reason") != _HOLDOUT_RECOVERY_CLEANUP_REASON:
            raise ValueError("holdout recovery cleanup receipt reason differs")
        counts = _require_zero_counts(runtime)
        if cleanup.get("resource_counts") != counts:
            raise ValueError(
                "holdout recovery cleanup receipt differs from fresh stable zero"
            )
    except BaseException as error:
        if prepared.structure != "canonical":
            raise RuntimeError("cleanup_indeterminate") from error
        raise
    if prepared.structure != "canonical":
        return {"status": "cleanup_indeterminate"}

    assert prepared.chain is not None
    cleanup_path = prepared.attempt_dir / "cleanup.json"
    _write_json_create_or_identical(cleanup_path, cleanup)
    payload = _seal(
        {
            "contract_version": "benchmark_v2_holdout_attempt_recovery_cleanup_payload_v1",
            "attempt_ref": deepcopy(prepared.attempt_ref),
            "attempt_dir": str(prepared.attempt_dir),
            "status": "recovery_cleanup",
            "cleanup_receipt_ref": _content_ref(
                cleanup, name="holdout recovery cleanup receipt"
            ),
            "resource_counts": counts,
            "recovery_reason": _HOLDOUT_RECOVERY_CLEANUP_REASON,
            "safety": deepcopy(HOLDOUT_SAFETY),
        }
    )
    ledger_path = holdout_attempt_events_path(
        ledger_root=prepared.validated.ledger_root
    )
    before = Path(ledger_path).read_bytes()
    appended = append_holdout_attempt_recovery_cleanup(
        ledger_root=prepared.validated.ledger_root,
        authorization_ref=prepared.validated.authorization_ref,
        claim_ref=prepared.claim_ref,
        event_payload=payload,
    )
    reopened = validate_holdout_attempt_events(
        ledger_root=prepared.validated.ledger_root,
        authorization_ref=prepared.validated.authorization_ref,
        claim_ref=prepared.claim_ref,
    )
    prior_kinds = [item["event"]["event_kind"] for item in prepared.chain]
    expected_kinds = (
        prior_kinds
        if prior_kinds[-1] == "recovery_cleanup"
        else [*prior_kinds, "recovery_cleanup"]
    )
    if (
        [item.get("event", {}).get("event_kind") for item in reopened]
        != expected_kinds
        or not reopened
        or reopened[-1] != appended
    ):
        raise ValueError("holdout recovery cleanup was not durably reopened")
    if prior_kinds[-1] == "recovery_cleanup" and Path(ledger_path).read_bytes() != before:
        raise ValueError("holdout recovery cleanup reinvocation changed ledger bytes")
    return {"status": "recovery_cleanup"}


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
    lifecycle_receipt = _validate_finalized_probe_receipt_projection(
        runtime.finalize_probe_lifecycle_receipt(
            provider_manifest=manifest,
            attempt_ref=deepcopy(attempt),
            cleanup_receipt=deepcopy(cleanup),
        ),
        attempt_ref=attempt,
        provider_id=provider_id,
        probe_kind=probe_kind,
        cleanup_ref=cleanup,
    )
    receipt_path = attempt_dir / "lifecycle-probe-receipt.json"
    persisted_receipt, receipt_bytes = _read_finalized_probe_receipt(
        receipt_path,
        attempt_ref=attempt,
        provider_id=provider_id,
        probe_kind=probe_kind,
        cleanup_ref=cleanup,
    )
    if persisted_receipt != lifecycle_receipt:
        raise ValueError("lifecycle probe receipt bytes differ from finalized receipt")
    lifecycle_ref = {
        "contract_version": "benchmark_v2_lifecycle_probe_receipt_v2",
        "file_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "content_sha256": lifecycle_receipt["content_sha256"],
    }
    result = _seal(
        {
            "contract_version": "benchmark_v2_runner_probe_result_v2",
            "attempt_ref": deepcopy(attempt),
            "attempt_dir": str(attempt_dir),
            "provider_id": provider_id,
            "probe_kind": probe_kind,
            "body_ref": _content_ref(body, name="probe body"),
            "cleanup_receipt_ref": _content_ref(cleanup, name="cleanup receipt"),
            "lifecycle_probe_receipt_ref": lifecycle_ref,
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


def _validate_probe_summary(
    value: object,
    *,
    probe_kind: str,
    requested_providers: Sequence[str],
    expected_results: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    summary = _sealed_mapping(value, name="probe summary v2")
    providers = tuple(requested_providers)
    attempts = summary.get("attempts")
    if (
        set(summary) != _PROBE_SUMMARY_V2_FIELDS
        or summary.get("contract_version") != "benchmark_v2_runner_probe_summary_v2"
        or summary.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or summary.get("partition") != "regression"
        or summary.get("probe_kind") != probe_kind
        or summary.get("collection_policy") != "one_requested_attempt_per_provider"
        or summary.get("status") != "terminal"
        or summary.get("artifact_is_authorization") is not False
        or summary.get("execute_binding_enabled") is not False
        or probe_kind not in {"cancel", "timeout"}
        or not providers
        or len(set(providers)) != len(providers)
        or any(provider not in _PROVIDERS for provider in providers)
        or not isinstance(attempts, list)
        or attempts != [dict(item) for item in expected_results]
        or len(attempts) != len(providers)
        or [item.get("provider_id") for item in attempts if isinstance(item, Mapping)]
        != list(providers)
    ):
        raise ValueError("probe summary v2 lineage is invalid")
    seen_attempts: set[str] = set()
    for provider_id, raw_result in zip(providers, attempts, strict=True):
        if not isinstance(raw_result, Mapping):
            raise ValueError("probe summary v2 result is not an object")
        attempt_ref = _validate_attempt_ref(raw_result.get("attempt_ref"))
        digest = str(attempt_ref["content_sha256"])
        if digest in seen_attempts or attempt_ref.get("provider_id") != provider_id:
            raise ValueError("probe summary v2 attempts are duplicate or reordered")
        seen_attempts.add(digest)
        attempt_dir = Path(str(raw_result.get("attempt_dir"))).resolve()
        body = _read_canonical_json_file(attempt_dir / "body.json", name="probe body")
        cleanup = _read_canonical_json_file(
            attempt_dir / "cleanup.json", name="probe cleanup receipt"
        )
        _validate_probe_result(
            raw_result,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
            body_ref=body,
            cleanup_ref=cleanup,
        )
        if raw_result.get("probe_kind") != probe_kind:
            raise ValueError("probe summary v2 cell kind differs")
    return summary


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
    result = _validate_probe_summary(
        _seal(
        {
            "contract_version": "benchmark_v2_runner_probe_summary_v2",
            "benchmark_release_id": BENCHMARK_RELEASE_ID,
            "partition": "regression",
            "probe_kind": probe_kind,
            "collection_policy": "one_requested_attempt_per_provider",
            "attempts": attempts,
            "status": "terminal",
            **_SAFETY,
        }
        ),
        probe_kind=probe_kind,
        requested_providers=providers,
        expected_results=attempts,
    )
    summary_path = (
        _PROJECT_ROOT / "runtime_state" / "portfolio-hybrid-v1-1" / "benchmark-v2"
        / "regression" / f"{probe_kind}-probes" / f"{probe_kind}-probes.json"
    )
    _write_json_create_or_identical(summary_path, result)
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


def _lexical_path(raw: object, *, name: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{name} is required")
    if any(part in {".", ".."} for part in raw.replace("\\", "/").split("/")):
        raise ValueError(f"{name} has a lexical alias")
    platform_spelling = raw.replace("/", os.sep).replace("\\", os.sep)
    if os.path.normpath(platform_spelling) != platform_spelling:
        raise ValueError(f"{name} has a lexical alias")
    candidate = Path(platform_spelling)
    return Path(os.path.abspath(candidate))


def _is_reparse(path: Path) -> bool:
    candidate = Path(path)
    if candidate.is_symlink():
        return True
    try:
        attributes = int(getattr(candidate.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _require_ordinary_path(path: Path, *, name: str, kind: str) -> Path:
    absolute = Path(os.path.abspath(path))
    existing = absolute if absolute.exists() or _is_reparse(absolute) else absolute.parent
    for candidate in [existing, *existing.parents]:
        if _is_reparse(candidate):
            raise ValueError(f"{name} traverses a symlink, junction, or reparse point")
    if absolute.resolve(strict=False) != absolute:
        raise ValueError(f"{name} resolves through an alias")
    if kind == "file" and not absolute.is_file():
        raise ValueError(f"{name} fixed file is missing")
    if kind == "directory" and not absolute.is_dir():
        raise ValueError(f"{name} directory is missing")
    return absolute


def _materializer_attempt_paths(
    *,
    prefix: Sequence[Mapping[str, object]],
    output_root: Path,
) -> dict[str, Path]:
    attempt_dirs: dict[str, Path] = {}
    for envelope in prefix:
        payload = envelope["event"]["event_payload"]
        attempt = payload["attempt_ref"]
        attempt_id = str(attempt["attempt_id"])
        attempt_key = str(attempt["content_sha256"])
        raw_attempt_dir = str(payload["attempt_dir"])
        attempt_dir = Path(raw_attempt_dir)
        expected = output_root / attempt_id
        if (
            raw_attempt_dir != str(expected)
            or attempt_dir.parent != output_root
            or attempt_dir.name != attempt_id
        ):
            raise ValueError("materializer attempt directory is not the immediate fixed child")
        ordinary = _require_ordinary_path(
            attempt_dir, name="materializer attempt directory", kind="directory"
        )
        prior = attempt_dirs.setdefault(attempt_key, ordinary)
        if prior != ordinary:
            raise ValueError("materializer attempt directory lineage differs")
        event_type = str(envelope["event"]["event_type"])
        status = str(payload["status"])
        fixed_name = None
        if event_type == "regression_attempt" and status == "body_complete":
            fixed_name = "body.json"
        elif event_type == "cleanup":
            fixed_name = "cleanup.json"
        elif event_type == "result":
            fixed_name = "result.json"
        if fixed_name is not None:
            _require_ordinary_path(
                ordinary / fixed_name,
                name=f"materializer {fixed_name}",
                kind="file",
            )
    return attempt_dirs


def _materialize_score_input(args: argparse.Namespace) -> dict[str, object]:
    if args.partition != "regression":
        raise ValueError("score-input materialization is regression-only")
    provider_manifest_path = _require_ordinary_path(
        _lexical_path(args.provider_manifest, name="provider manifest"),
        name="provider manifest",
        kind="file",
    )
    if provider_manifest_path.name != "benchmark-v2-provider-manifest.json":
        raise ValueError(
            "provider manifest basename must be benchmark-v2-provider-manifest.json"
        )
    provider_corpus_path = _require_ordinary_path(
        provider_manifest_path.parent / "provider-corpus.v2.json",
        name="provider corpus",
        kind="file",
    )
    ledger_path = _require_ordinary_path(
        _lexical_path(args.attempt_ledger, name="attempt ledger"),
        name="attempt ledger",
        kind="file",
    )
    output_root = _require_ordinary_path(
        _lexical_path(args.output_root, name="output root"),
        name="output root",
        kind="directory",
    )
    output_path = _lexical_path(args.output, name="materialized output")
    _require_ordinary_path(
        output_path, name="materialized output", kind="pending"
    )
    if len(
        {
            provider_manifest_path,
            provider_corpus_path,
            ledger_path,
            output_root,
            output_path,
        }
    ) != 5:
        raise ValueError("materializer paths are aliased")

    ledger = _read_ledger_structure(ledger_path)
    horizon = select_benchmark_v2_attempt_ledger_horizon(
        runner_ledger_events=ledger
    )
    prefix = ledger[: horizon.selected_result_terminal_sequence + 1]
    attempt_dirs = _materializer_attempt_paths(
        prefix=prefix, output_root=output_root
    )
    selected_evidence_paths = {
        path
        for attempt_dir in attempt_dirs.values()
        for path in (
            attempt_dir,
            attempt_dir / "body.json",
            attempt_dir / "cleanup.json",
            attempt_dir / "result.json",
        )
    }
    if output_path in selected_evidence_paths:
        raise ValueError("materialized output aliases a selected evidence path")
    raw_lines = ledger_path.read_bytes().split(b"\n")[:-1]
    _validate_ledger_records(
        prefix,
        raw_lines=raw_lines[: horizon.selected_result_terminal_sequence + 1],
    )

    bodies: list[dict[str, object]] = []
    cleanups: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    cleanup_projections: list[dict[str, object]] = []
    cleanup_projection_by_attempt: dict[str, dict[str, object]] = {}
    first_open_attempt_keys: list[str] = []
    selected_raw_attempt: dict[str, object] | None = None
    selected_attempt_dir: Path | None = None
    selected_body: dict[str, object] | None = None
    selected_cleanup: dict[str, object] | None = None
    selected_result: dict[str, object] | None = None
    selected_cleanup_projection: dict[str, object] | None = None
    selected_key = horizon.selected_attempt_ref["content_sha256"]
    for envelope in prefix:
        event = envelope["event"]
        payload = event["event_payload"]
        raw_attempt = deepcopy(dict(payload["attempt_ref"]))
        key = str(raw_attempt["content_sha256"])
        attempt_dir = attempt_dirs[key]
        if event["event_type"] == "regression_attempt" and payload["status"] == "opened":
            first_open_attempt_keys.append(key)
        if key == selected_key:
            selected_raw_attempt = raw_attempt
            selected_attempt_dir = attempt_dir
        if event["event_type"] == "regression_attempt" and payload["status"] == "body_complete":
            body = _read_canonical_json_file(attempt_dir / "body.json", name="actual body")
            bodies.append(body)
            if key == selected_key:
                selected_body = body
        elif event["event_type"] == "cleanup":
            cleanup = _read_canonical_json_file(
                attempt_dir / "cleanup.json", name="cleanup receipt"
            )
            projection = project_benchmark_v2_cleanup_lifecycle(
                attempt_ref=raw_attempt,
                cleanup_receipt=cleanup,
            )
            cleanups.append(cleanup)
            cleanup_projections.append(projection)
            cleanup_projection_by_attempt[key] = projection
            if key == selected_key:
                selected_cleanup = cleanup
                selected_cleanup_projection = projection
        elif event["event_type"] == "result":
            result = _read_canonical_json_file(attempt_dir / "result.json", name="runner result")
            results.append(result)
            if key == selected_key:
                selected_result = result
    if any(
        value is None
        for value in (
            selected_raw_attempt,
            selected_attempt_dir,
            selected_body,
            selected_cleanup,
            selected_result,
            selected_cleanup_projection,
        )
    ):
        raise ValueError("selected materializer evidence is incomplete")
    assert selected_raw_attempt is not None
    assert selected_attempt_dir is not None
    assert selected_body is not None
    assert selected_cleanup is not None
    assert selected_result is not None
    assert selected_cleanup_projection is not None

    journal_path = _require_ordinary_path(
        _PROJECT_ROOT
        / "runtime_state"
        / "benchmark-v2-attempts"
        / f"{selected_raw_attempt['content_sha256']}.jsonl",
        name="selected attempt journal",
        kind="file",
    )
    if output_path == journal_path:
        raise ValueError("materialized output aliases the selected attempt journal")
    journal = read_benchmark_v2_attempt_journal(
        journal_path=journal_path,
        attempt_ref=selected_raw_attempt,
    )
    terminal_projection = project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=selected_raw_attempt,
        journal_events=journal,
        cleanup_receipt=selected_cleanup,
        cleanup_projection=selected_cleanup_projection,
    )
    journal_projection = project_benchmark_v2_attempt_journal(
        attempt_ref=selected_raw_attempt,
        journal_events=journal,
        terminal_event_projection=terminal_projection,
        cleanup_projection=selected_cleanup_projection,
    )
    screen_projections = project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=selected_raw_attempt,
        screen_group_projections=selected_body["screen_group_results"],
    )
    attempt_lifecycle = project_benchmark_v2_attempt_lifecycle(
        attempt_ref=selected_raw_attempt,
        journal_events=journal,
        attempt_journal_projection=journal_projection,
        cleanup_projection=selected_cleanup_projection,
        terminal_event_projection=terminal_projection,
        screen_group_lifecycle_projections=screen_projections,
    )
    runner_events = project_benchmark_v2_runner_events(
        partition="regression",
        runner_ledger_events=prefix,
        actual_body=bodies,
        actual_result=results,
        cleanup_receipt=cleanups,
        cleanup_projection=cleanup_projections,
    )
    ledger_materialization = materialize_benchmark_v2_attempt_ledger_projections(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        partition="regression",
        runner_ledger_events=prefix,
        runner_event_projections=runner_events,
        attempt_lifecycle_projections=[attempt_lifecycle],
    )
    bundle_cleanup_projections = [
        cleanup_projection_by_attempt[key]
        for key in first_open_attempt_keys
        if key in cleanup_projection_by_attempt
    ]
    lifecycle_bundle = compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        partition="regression",
        attempt_ref=selected_raw_attempt,
        raw_ledger_prefix_projection=ledger_materialization.runner_ledger_prefix_projection,
        projected_attempt_ledger=ledger_materialization.projected_attempt_ledger,
        selected_attempt_lifecycle_projection=attempt_lifecycle,
        cleanup_lifecycle_projection=selected_cleanup_projection,
        cleanup_lifecycle_projections=bundle_cleanup_projections,
        journal_terminal_event_projection=terminal_projection,
        attempt_journal_projection=journal_projection,
        screen_group_lifecycle_projections=screen_projections,
        runner_event_projections=runner_events,
        cleanup_receipt=selected_cleanup,
    )
    actual_body_bytes = (selected_attempt_dir / "body.json").read_bytes()
    actual_result_bytes = (selected_attempt_dir / "result.json").read_bytes()
    cleanup_receipt_bytes = (selected_attempt_dir / "cleanup.json").read_bytes()
    provider_manifest_bytes = provider_manifest_path.read_bytes()
    provider_corpus_bytes = provider_corpus_path.read_bytes()
    body_projection = project_benchmark_v2_actual_body(
        actual_body_bytes=actual_body_bytes,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    result_projection = project_benchmark_v2_actual_result(
        actual_result_bytes=actual_result_bytes,
        cleanup_receipt_bytes=cleanup_receipt_bytes,
        expected_attempt_dir=selected_attempt_dir,
        actual_body_projection=body_projection,
        cleanup_projection=selected_cleanup_projection,
        runner_ledger_prefix_projection=ledger_materialization.runner_ledger_prefix_projection,
        result_event_projection=runner_events[horizon.selected_result_terminal_sequence],
    )
    accepted = materialize_benchmark_v2_accepted_regression_score_input_v2(
        actual_body_bytes=actual_body_bytes,
        actual_result_bytes=actual_result_bytes,
        cleanup_receipt_bytes=cleanup_receipt_bytes,
        expected_attempt_dir=selected_attempt_dir,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
        runner_ledger_prefix_projection=ledger_materialization.runner_ledger_prefix_projection,
        attempt_journal_projection=journal_projection,
        actual_body_projection=body_projection,
        actual_result_projection=result_projection,
        lifecycle_bundle_v3=lifecycle_bundle,
    )
    _write_pretty_json_create_or_identical(output_path, accepted)
    return accepted


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
    action.add_argument("--materialize-score-input", action="store_true")
    action.add_argument("--materialize-probe-authority", action="store_true")
    parser.add_argument("--providers")
    parser.add_argument("--attempt-ledger")
    parser.add_argument("--ledger-root")
    parser.add_argument("--regression-run-ref")
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
    argv_list = list(argv)
    args = _parser().parse_args(argv_list)
    if args.cleanup_only:
        validated_cleanup = _validate_holdout_cleanup_only_input(argv_list)
        prepared_cleanup = _prepare_holdout_cleanup_only(validated_cleanup)
        cleanup_runtime = get_production_benchmark_v2_runtime()
        return _run_holdout_cleanup_only(
            prepared=prepared_cleanup,
            runtime=cleanup_runtime,
        )
    if args.actual_models and (
        args.partition == "holdout" or args.holdout_authorization is not None
    ):
        validated = _validate_holdout_actual_models_input(argv_list)
        runtime = get_production_benchmark_v2_runtime()
        _run_holdout_actual_models(validated=validated, runtime=runtime)
        return {"status": "terminal"}
    if args.materialize_score_input:
        _require(
            args,
            "provider_manifest",
            "partition",
            "attempt_ledger",
            "output_root",
            "output",
        )
        forbidden = (
            "providers",
            "ledger_root",
            "regression_run_ref",
            "holdout_authorization",
        )
        present = [
            name
            for name in forbidden
            if any(
                token == "--" + name.replace("_", "-")
                or token.startswith("--" + name.replace("_", "-") + "=")
                for token in argv_list
            )
        ]
        if present:
            raise ValueError(
                "runner arguments are not valid for this action: "
                + ", ".join(present)
            )
        return _materialize_score_input(args)
    if args.materialize_probe_authority:
        _require(
            args,
            "provider_manifest",
            "partition",
            "regression_run_ref",
            "ledger_root",
            "output",
        )
        if args.partition != "regression":
            raise ValueError("probe authority materialization requires regression")
        fixed_regression_root = (
            _PROJECT_ROOT
            / "runtime_state"
            / "portfolio-hybrid-v1-1"
            / "benchmark-v2"
            / "regression"
        ).resolve()
        if Path(args.regression_run_ref).resolve() != (
            fixed_regression_root / "accepted-run-ref.json"
        ) or Path(args.output).resolve() != (
            fixed_regression_root / "probe-authority.json"
        ):
            raise ValueError(
                "probe authority inputs do not match the fixed public paths"
            )
        forbidden = (
            "providers",
            "attempt_ledger",
            "output_root",
            "holdout_authorization",
        )
        present = [
            name
            for name in forbidden
            if any(
                token == "--" + name.replace("_", "-")
                or token.startswith("--" + name.replace("_", "-") + "=")
                for token in argv_list
            )
        ]
        if present:
            raise ValueError(
                "runner arguments are not valid for this action: "
                + ", ".join(present)
            )
        bundle = materialize_benchmark_v2_regression_probe_authority(
            provider_manifest_path=Path(args.provider_manifest),
            regression_run_ref_path=Path(args.regression_run_ref),
            ledger_root=Path(args.ledger_root),
            output_path=Path(args.output),
        )
        return {
            "probe_authority_ref": {
                "id": bundle["artifact_id"],
                "content_sha256": bundle["content_sha256"],
            },
            "status": "PASS",
        }
    runtime = get_production_benchmark_v2_runtime()
    if args.dry_run:
        _require(args, "provider_manifest", "partition", "output")
        _reject(
            args,
            "providers",
            "attempt_ledger",
            "ledger_root",
            "regression_run_ref",
            "output_root",
            "holdout_authorization",
        )
        return _dry_run(args, runtime)
    if args.actual_models:
        _require(args, "provider_manifest", "partition", "attempt_ledger", "output_root")
        _reject(
            args,
            "providers",
            "ledger_root",
            "regression_run_ref",
            "output",
            "holdout_authorization",
        )
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
        _reject(
            args,
            "ledger_root",
            "regression_run_ref",
            "output",
            "holdout_authorization",
        )
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
            "regression_run_ref",
            "output",
            "holdout_authorization",
        )
        return _cleanup_open_attempts(args, runtime)
    raise RuntimeError("runner action selection is unreachable")


def main(argv: Sequence[str] | None = None) -> int:
    result = run_cli(sys.argv[1:] if argv is None else argv)
    sys.stdout.buffer.write(_canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
