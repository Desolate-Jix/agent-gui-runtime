"""Benchmark-v2 无路径投影注册表与封闭证据图验证。"""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePath
import re
from types import MappingProxyType
from typing import Callable, Mapping, Sequence


_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_REF_FIELDS = {"id", "content_sha256"}
_FILE_REF_FIELDS = {"file_sha256", "content_sha256"}
_CASE_REF_FIELDS = {"case_id", "case_content_sha256"}
_ZERO_RESOURCE_COUNTS = {
    "service_operations": 0,
    "windows": 0,
    "providers": 0,
    "listeners": 0,
    "leases": 0,
}
_ARMS = {
    ("qwen_only",),
    ("omni_only_discovery",),
    ("omni_to_qwen", "omni_to_qwen_vista"),
}


@dataclass(frozen=True)
class _RefRole:
    kind: str
    targets: tuple[str, ...] = ()
    external: bool = False
    raw_class: str | None = None
    nullable: bool = False
    ordered: bool = False


@dataclass(frozen=True)
class _ContractSpec:
    contract_version: str
    artifact_prefix: str
    semantic_fields: tuple[str, ...]
    semantic_validator: Callable[[Mapping[str, object]], None]
    ref_role_schema: Mapping[str, _RefRole]
    allowed_registry_names: frozenset[str]
    class_ranks: Mapping[str, int]
    semantic_sort_key: Callable[[Mapping[str, object], str], tuple[object, ...]]


@dataclass(frozen=True)
class _RawClass:
    contract_version: str
    artifact_prefix: str
    identity_domain: bytes | None
    allowed_registry_names: frozenset[str]
    class_ranks: Mapping[str, int]


def _canonical_bytes(value: object) -> bytes:
    _validate_json_value(value, name="canonical value")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_json_value(value: object, *, name: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            _reject_path_alias(value, name=name)
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, (Path, PurePath, bytes, bytearray, float)):
        raise ValueError(f"{name} contains a noncanonical JSON type")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{name} contains a noncanonical JSON key")
            lowered = key.casefold()
            if (
                lowered == "path"
                or lowered.endswith("_path")
                or lowered == "attempt_dir"
                or lowered.startswith("owner_journal")
            ):
                raise ValueError(f"{name} contains a forbidden path field")
            _validate_json_value(child, name=f"{name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        if isinstance(value, tuple):
            raise ValueError(f"{name} contains a noncanonical JSON type")
        for index, child in enumerate(value):
            _validate_json_value(child, name=f"{name}[{index}]")
        return
    raise ValueError(f"{name} contains a noncanonical JSON type")


def _validate_raw_public_json(value: object, *, name: str) -> None:
    """原始 provider 证据允许有限浮点数，但仍禁止任何路径或别名。"""

    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            _reject_path_alias(value, name=name)
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a noncanonical JSON number")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{name} contains a noncanonical JSON key")
            lowered = key.casefold()
            if (
                lowered == "path"
                or lowered.endswith("_path")
                or lowered == "attempt_dir"
                or lowered.startswith("owner_journal")
            ):
                raise ValueError(f"{name} contains a forbidden path field")
            _validate_raw_public_json(child, name=f"{name}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_raw_public_json(child, name=f"{name}[{index}]")
        return
    raise ValueError(f"{name} contains a noncanonical JSON type")


def _reject_path_alias(value: str, *, name: str) -> None:
    lowered = value.casefold()
    segments = value.split("/")
    if (
        any(ord(character) < 32 for character in value)
        or value.startswith(("/", "\\"))
        or _DRIVE_RE.match(value) is not None
        or lowered.startswith("file:")
        or "\\" in value
        or "%" in value
        or any(segment in {".", "..", "~"} for segment in segments)
    ):
        raise ValueError(f"{name} contains a filesystem path or alias escape")


def _closed(value: Mapping[str, object], fields: Sequence[str], *, name: str) -> None:
    if set(value) != set(fields):
        raise ValueError(f"{name} is not a closed contract")


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    _reject_path_alias(value, name=name)
    return value


def _sha(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _nonnegative(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _positive(value: object, *, name: str) -> int:
    result = _nonnegative(value, name=name)
    if result == 0:
        raise ValueError(f"{name} must be positive")
    return result


def _public_id(value: object, *, name: str) -> str:
    result = _text(value, name=name)
    if any(segment in {"", ".", "..", "~"} or segment != segment.strip() for segment in result.split("/")):
        raise ValueError(f"{name} public identifier contains an alias escape")
    return result


def _ref(value: object, *, name: str, prefixes: Sequence[str] = ()) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an exact ref")
    _closed(value, _REF_FIELDS, name=name)
    identifier = _public_id(value.get("id"), name=f"{name}.id")
    digest = _sha(value.get("content_sha256"), name=f"{name}.content_sha256")
    if prefixes and not any(identifier.startswith(f"{prefix}/") for prefix in prefixes):
        raise ValueError(f"{name} has the wrong registered prefix")
    return {"id": identifier, "content_sha256": digest}


def _file_ref(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a pathless file ref")
    _closed(value, _FILE_REF_FIELDS, name=name)
    return {
        "file_sha256": _sha(value.get("file_sha256"), name=f"{name}.file_sha256"),
        "content_sha256": _sha(value.get("content_sha256"), name=f"{name}.content_sha256"),
    }


def _case_ref(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a closed provider case ref")
    _closed(value, _CASE_REF_FIELDS, name=name)
    return {
        "case_id": _public_id(value.get("case_id"), name=f"{name}.case_id"),
        "case_content_sha256": _sha(
            value.get("case_content_sha256"), name=f"{name}.case_content_sha256"
        ),
    }


def _ledger_pre_result_ref(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a closed ledger pre-result ref")
    fields = {
        "contract_version",
        "id",
        "attempt_ref",
        "terminal_sequence",
        "terminal_envelope_sha256",
        "prefix_sha256",
    }
    _closed(value, fields, name=name)
    if value.get("contract_version") != "benchmark_v2_runner_ledger_pre_result_ref_v1":
        raise ValueError(f"{name} ledger contract is invalid")
    identifier = _public_id(value.get("id"), name=f"{name}.id")
    if not identifier.startswith("runner-ledger-pre-result/"):
        raise ValueError(f"{name} has the wrong registered prefix")
    return {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": identifier,
        "attempt_ref": _ref(value.get("attempt_ref"), name=f"{name}.attempt_ref", prefixes=("runner-attempt",)),
        "terminal_sequence": _nonnegative(value.get("terminal_sequence"), name=f"{name}.terminal_sequence"),
        "terminal_envelope_sha256": _sha(value.get("terminal_envelope_sha256"), name=f"{name}.terminal_envelope_sha256"),
        "prefix_sha256": _sha(value.get("prefix_sha256"), name=f"{name}.prefix_sha256"),
    }


def _safety(value: object) -> None:
    if value != _SAFETY:
        raise ValueError("pathless projection safety literal is invalid")


def _arm_scope(value: object, *, name: str = "arm_scope") -> tuple[str, ...]:
    if not isinstance(value, list) or tuple(value) not in _ARMS:
        raise ValueError(f"{name} is not a frozen arm scope")
    return tuple(value)


def _xyxy(value: object, *, name: str) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or value[2] <= value[0]
        or value[3] <= value[1]
    ):
        raise ValueError(f"{name} must be a positive-area integer xyxy")
    return list(value)


def _ref_list(value: object, *, name: str, exact_count: int | None = None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an ordered exact ref list")
    if exact_count is not None and len(value) != exact_count:
        raise ValueError(f"{name} must contain exactly {exact_count} refs")
    result = [_ref(item, name=f"{name}[{index}]") for index, item in enumerate(value)]
    if len({_canonical_bytes(item) for item in result}) != len(result):
        raise ValueError(f"{name} contains duplicate refs")
    return result


def _envelope_list(value: object, *, name: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    for index, envelope in enumerate(value):
        if not isinstance(envelope, Mapping):
            raise ValueError(f"{name}[{index}] must be an envelope")
        _closed(envelope, ("ref", "canonical_bytes_b64"), name=f"{name}[{index}]")
        _ref(envelope.get("ref"), name=f"{name}[{index}].ref")
        if not isinstance(envelope.get("canonical_bytes_b64"), str):
            raise ValueError(f"{name}[{index}] canonical bytes are invalid")


def _validate_nested(payload: Mapping[str, object]) -> None:
    _text(payload["evidence_kind"], name="evidence_kind")
    _case_ref(payload["case_ref"], name="case_ref")
    _ref(payload["actual_screen_group_ref"], name="actual_screen_group_ref")
    _sha(payload["canonical_value_sha256"], name="canonical_value_sha256")
    _safety(payload["safety"])


_SOURCE_EVIDENCE_FIELDS = {
    "incumbent_qwen_action": {"incumbent_response_ref", "available_action_ref"},
    "omni_inventory_item": {"omni_inventory_ref", "omni_item_ref"},
    "hybrid_bound_fusion_candidate": {
        "omni_inventory_ref",
        "qwen_bindings_ref",
        "fusion_result_ref",
        "fusion_candidate_ref",
    },
}


def _validate_source(payload: Mapping[str, object]) -> None:
    _case_ref(payload["case_ref"], name="case_ref")
    _arm_scope(payload["arm_scope"])
    source_kind = _text(payload["source_kind"], name="source_kind")
    if source_kind not in _SOURCE_EVIDENCE_FIELDS:
        raise ValueError("source_kind is not registered")
    evidence = payload["evidence_refs"]
    if not isinstance(evidence, Mapping) or set(evidence) != _SOURCE_EVIDENCE_FIELDS[source_kind]:
        raise ValueError("source parent evidence refs are not closed")
    for role, value in evidence.items():
        prefixes: tuple[str, ...] = ()
        if role in {"incumbent_response_ref", "available_action_ref", "omni_item_ref", "fusion_candidate_ref"}:
            prefixes = ("nested-provider-evidence",)
        elif role == "omni_inventory_ref":
            prefixes = ("omni-inventory",)
        elif role == "qwen_bindings_ref":
            prefixes = ("qwen-bindings",)
        elif role == "fusion_result_ref":
            prefixes = ("fusion-result",)
        _ref(value, name=f"evidence_refs.{role}", prefixes=prefixes)
    _ref(payload["actual_screen_group_ref"], name="actual_screen_group_ref")
    _ref(payload["capture_ref"], name="capture_ref")
    _safety(payload["safety"])


def _validate_bbox(payload: Mapping[str, object]) -> None:
    _public_id(payload["case_id"], name="case_id")
    _arm_scope(payload["arm_scope"])
    _public_id(payload["candidate_id"], name="candidate_id")
    if payload["coordinate_space"] != "capture_pixel_xyxy":
        raise ValueError("bbox coordinate_space is invalid")
    _xyxy(payload["xyxy"], name="xyxy")
    _ref(payload["capture_ref"], name="capture_ref")
    _ref(payload["source_parent_ref"], name="source_parent_ref", prefixes=("prediction-source-parent",))
    _safety(payload["safety"])


def _validate_binding(payload: Mapping[str, object]) -> None:
    _public_id(payload["case_id"], name="case_id")
    _arm_scope(payload["arm_scope"])
    _public_id(payload["candidate_id"], name="candidate_id")
    _ref(payload["source_parent_ref"], name="source_parent_ref", prefixes=("prediction-source-parent",))
    _ref(payload["capture_ref"], name="capture_ref")
    _ref(payload["bbox_ref"], name="bbox_ref", prefixes=("prediction-bbox",))
    _safety(payload["safety"])


def _validate_vista_request(payload: Mapping[str, object]) -> None:
    _public_id(payload["case_id"], name="case_id")
    if _arm_scope(payload["arm_scope"]) != ("omni_to_qwen", "omni_to_qwen_vista"):
        raise ValueError("only the paired hybrid scope may create a VISTA request")
    _public_id(payload["candidate_id"], name="candidate_id")
    _ref(payload["target_binding_ref"], name="target_binding_ref", prefixes=("target-binding",))
    _ref(payload["source_parent_ref"], name="source_parent_ref", prefixes=("prediction-source-parent",))
    _ref(payload["capture_ref"], name="capture_ref")
    _ref(payload["bbox_ref"], name="bbox_ref", prefixes=("prediction-bbox",))
    _ref(payload["submitted_request_ref"], name="submitted_request_ref", prefixes=("submitted-vista-request",))
    if payload["submission_status"] != "SUBMITTED":
        raise ValueError("VISTA submission_status is invalid")
    _safety(payload["safety"])


def _validate_runner_event(payload: Mapping[str, object]) -> None:
    if payload["partition"] not in {"regression", "holdout"}:
        raise ValueError("runner event partition is invalid")
    event_kind = payload["event_kind"]
    if event_kind not in {"opened", "body_complete", "cleanup", "result"}:
        raise ValueError("runner event kind is invalid")
    sequence = _nonnegative(payload["sequence"], name="sequence")
    _ref(payload["attempt_ref"], name="attempt_ref", prefixes=("runner-attempt",))
    previous = payload["previous_event_projection_ref"]
    if sequence == 0:
        if previous is not None:
            raise ValueError("sequence zero previous event ref must be null")
    else:
        _ref(previous, name="previous_event_projection_ref", prefixes=("verified-runner-event",))
    _sha(payload["raw_event_sha256"], name="raw_event_sha256")
    refs = payload["load_bearing_refs"]
    if not isinstance(refs, Mapping):
        raise ValueError("runner event load-bearing refs are invalid")
    expected = {
        "opened": {"attempt_ref"},
        "body_complete": {"body_file_ref"},
        "cleanup": {"cleanup_receipt_ref", "cleanup_projection_ref"},
        "result": {"result_file_ref", "attempt_ledger_pre_result_ref"},
    }[str(event_kind)]
    if set(refs) != expected:
        raise ValueError("runner event load-bearing refs are not closed")
    if event_kind == "opened":
        if _ref(refs["attempt_ref"], name="load_bearing_refs.attempt_ref") != _ref(payload["attempt_ref"], name="attempt_ref"):
            raise ValueError("opened runner event attempt ref mismatch")
    elif event_kind == "body_complete":
        _file_ref(refs["body_file_ref"], name="load_bearing_refs.body_file_ref")
    elif event_kind == "cleanup":
        _ref(refs["cleanup_receipt_ref"], name="load_bearing_refs.cleanup_receipt_ref", prefixes=("attempt-cleanup-receipt",))
        _ref(refs["cleanup_projection_ref"], name="load_bearing_refs.cleanup_projection_ref", prefixes=("verified-lifecycle",))
    else:
        _file_ref(refs["result_file_ref"], name="load_bearing_refs.result_file_ref")
        _ledger_pre_result_ref(
            refs["attempt_ledger_pre_result_ref"],
            name="load_bearing_refs.attempt_ledger_pre_result_ref",
        )
    _safety(payload["safety"])


def _validate_journal_terminal(payload: Mapping[str, object]) -> None:
    _ref(payload["attempt_ref"], name="attempt_ref", prefixes=("runner-attempt",))
    _nonnegative(payload["sequence"], name="sequence")
    if payload["phase"] != "terminal" or payload["event_kind"] != "attempt_terminal":
        raise ValueError("attempt journal terminal discriminator is invalid")
    _sha(payload["raw_event_sha256"], name="raw_event_sha256")
    _sha(payload["predecessor_content_sha256"], name="predecessor_content_sha256")
    _ref(payload["cleanup_receipt_ref"], name="cleanup_receipt_ref", prefixes=("attempt-cleanup-receipt",))
    _ref(payload["cleanup_projection_ref"], name="cleanup_projection_ref", prefixes=("verified-lifecycle",))
    _safety(payload["safety"])


def _validate_lifecycle(payload: Mapping[str, object]) -> None:
    _ref(payload["attempt_ref"], name="attempt_ref", prefixes=("runner-attempt",))
    kind = payload["lifecycle_kind"]
    if kind not in {"attempt", "screen_group", "cleanup"}:
        raise ValueError("lifecycle_kind is invalid")
    _sha(payload["raw_evidence_sha256"], name="raw_evidence_sha256")
    if payload["cleanup_stable_zero"] is not True or payload["resource_counts"] != _ZERO_RESOURCE_COUNTS:
        raise ValueError("lifecycle stable-zero resources are invalid")
    started = _nonnegative(payload["started_request_count"], name="started_request_count")
    terminal = _nonnegative(payload["terminal_or_unknown_request_count"], name="terminal_or_unknown_request_count")
    parents = payload["parent_refs"]
    if not isinstance(parents, Mapping):
        raise ValueError("lifecycle parent refs are invalid")
    if kind == "cleanup":
        if payload["terminal_status"] != "stable_zero" or started != 0 or terminal != 0:
            raise ValueError("cleanup lifecycle derivation is invalid")
        _closed(parents, ("cleanup_receipt_ref",), name="cleanup lifecycle parent refs")
        _ref(parents["cleanup_receipt_ref"], name="cleanup_receipt_ref", prefixes=("attempt-cleanup-receipt",))
    elif kind == "screen_group":
        if payload["terminal_status"] != "stable_zero" or started != 0 or terminal != 0:
            raise ValueError("screen-group lifecycle derivation is invalid")
        _closed(parents, ("actual_screen_group_ref", "provider_group_ref"), name="screen-group lifecycle parent refs")
        _ref(parents["actual_screen_group_ref"], name="actual_screen_group_ref")
        _ref(parents["provider_group_ref"], name="provider_group_ref")
    else:
        if payload["terminal_status"] != "terminal" or started != 0 or terminal != 0:
            raise ValueError("attempt lifecycle derivation is invalid")
        _closed(
            parents,
            (
                "attempt_journal_projection_ref",
                "cleanup_projection_ref",
                "terminal_event_ref",
                "screen_group_lifecycle_projection_refs",
            ),
            name="attempt lifecycle parent refs",
        )
        _ref(parents["attempt_journal_projection_ref"], name="attempt_journal_projection_ref", prefixes=("verified-attempt-journal",))
        _ref(parents["cleanup_projection_ref"], name="cleanup_projection_ref", prefixes=("verified-lifecycle",))
        _ref(parents["terminal_event_ref"], name="terminal_event_ref", prefixes=("verified-attempt-journal-terminal-event",))
        _ref_list(parents["screen_group_lifecycle_projection_refs"], name="screen_group_lifecycle_projection_refs", exact_count=12)
    _safety(payload["safety"])


def _validate_projected_ledger(payload: Mapping[str, object]) -> None:
    _public_id(payload["benchmark_release_id"], name="benchmark_release_id")
    if payload["partition"] not in {"regression", "holdout"}:
        raise ValueError("projected ledger partition is invalid")
    _ref(payload["raw_ledger_prefix_verification_ref"], name="raw_ledger_prefix_verification_ref", prefixes=("verified-runner-ledger-prefix",))
    entries = payload["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("projected ledger entries are empty")
    sequences: list[int] = []
    eligible: list[Mapping[str, object]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError("projected ledger entry is invalid")
        _closed(
            entry,
            ("sequence", "attempt_ref", "observed_state", "event_projection_refs", "lifecycle_ref", "selection_eligible"),
            name=f"projected ledger entry[{index}]",
        )
        sequences.append(_nonnegative(entry["sequence"], name=f"entry[{index}].sequence"))
        _ref(entry["attempt_ref"], name=f"entry[{index}].attempt_ref", prefixes=("runner-attempt",))
        if entry["observed_state"] not in {"opened", "body_complete", "cleanup", "result"}:
            raise ValueError("projected ledger observed state is invalid")
        refs = _ref_list(entry["event_projection_refs"], name=f"entry[{index}].event_projection_refs")
        if not refs:
            raise ValueError("projected ledger event refs are empty")
        lifecycle_ref = entry["lifecycle_ref"]
        if lifecycle_ref is not None:
            _ref(lifecycle_ref, name=f"entry[{index}].lifecycle_ref", prefixes=("verified-lifecycle",))
        if not isinstance(entry["selection_eligible"], bool):
            raise ValueError("projected ledger selection eligibility is invalid")
        if entry["selection_eligible"] is True:
            if entry["observed_state"] != "result" or lifecycle_ref is None:
                raise ValueError("projected ledger eligible entry is incomplete")
            eligible.append(entry)
    if sequences != list(range(len(entries))):
        raise ValueError("projected ledger sequence is not first-open order")
    if not eligible:
        raise ValueError("projected ledger has no eligible attempt")
    selected_attempt = _ref(payload["selected_attempt_ref"], name="selected_attempt_ref", prefixes=("runner-attempt",))
    selected_lifecycle = _ref(payload["selected_lifecycle_ref"], name="selected_lifecycle_ref", prefixes=("verified-lifecycle",))
    first = eligible[0]
    if selected_attempt != _ref(first["attempt_ref"], name="eligible attempt_ref") or selected_lifecycle != _ref(first["lifecycle_ref"], name="eligible lifecycle_ref"):
        raise ValueError("projected ledger first eligible selection mismatch")
    _safety(payload["safety"])


def _validated_outer_envelopes(
    payload: Mapping[str, object], *, registry_name: str
) -> list[tuple[dict[str, object], dict[str, str], str]]:
    envelopes = payload["sealed_artifact_envelopes"]
    if not isinstance(envelopes, list) or not envelopes:
        raise ValueError("sealed artifact closure is empty")
    ordering_context: dict[str, object] = {}
    if registry_name == "lifecycle_bundle_v3":
        ordering_context["attempt_first_open_order"] = _attempt_first_open_order(
            envelopes
        )
    ordered = order_pathless_envelopes(
        registry_name=registry_name, envelopes=envelopes, context=ordering_context
    )
    if ordered != envelopes:
        raise ValueError("sealed artifact closure is misordered")
    result: list[tuple[dict[str, object], dict[str, str], str]] = []
    for envelope in ordered:
        raw, item, raw_class, _ = _decode_envelope(envelope)
        if raw_class is None:
            ref_value = pathless_artifact_ref(item)
            class_name = str(item["contract_version"])
        else:
            ref_value = _raw_ref(raw_class, raw, item)
            class_name = raw_class
        result.append((item, ref_value, class_name))
    return result


def _validate_prediction_run(payload: Mapping[str, object]) -> None:
    _public_id(payload["benchmark_release_id"], name="benchmark_release_id")
    if payload["partition"] not in {"regression", "holdout"}:
        raise ValueError("prediction run partition is invalid")
    for field in (
        "corpus_parent_ref",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "attempt_ref",
        "projected_attempt_ledger_ref",
        "raw_ledger_prefix_verification_ref",
        "automatic_prediction_ref",
        "selected_lifecycle_ref",
    ):
        _ref(payload[field], name=field)
    closure = _validated_outer_envelopes(payload, registry_name="prediction_run_v3")
    classes = [class_name for _, _, class_name in closure]
    if classes.count("automatic_prediction") != 1:
        raise ValueError("prediction closure requires exactly one automatic prediction")
    if classes.count("benchmark_v2_projected_attempt_ledger_v1") != 1:
        raise ValueError("prediction closure requires exactly one projected ledger")
    if not any(class_name == "benchmark_v2_runner_event_verified_projection_v1" for class_name in classes):
        raise ValueError("prediction closure requires runner events")
    automatic_ref = next(ref_value for _, ref_value, name in closure if name == "automatic_prediction")
    ledger_ref = next(
        ref_value
        for _, ref_value, name in closure
        if name == "benchmark_v2_projected_attempt_ledger_v1"
    )
    if automatic_ref != payload["automatic_prediction_ref"]:
        raise ValueError("prediction closure automatic ref mismatch")
    if ledger_ref != payload["projected_attempt_ledger_ref"]:
        raise ValueError("prediction closure projected ledger ref mismatch")
    provider_classes = {
        name
        for name in classes
        if name in {"omni_inventory", "qwen_bindings", "fusion_result", "submitted_vista_request"}
    }
    if provider_classes and not {
        "omni_inventory",
        "qwen_bindings",
        "fusion_result",
    }.issubset(provider_classes):
        raise ValueError("prediction closure provider evidence is incomplete")
    _safety(payload["safety"])


def _validate_lifecycle_bundle(payload: Mapping[str, object]) -> None:
    _public_id(payload["benchmark_release_id"], name="benchmark_release_id")
    if payload["partition"] not in {"regression", "holdout"}:
        raise ValueError("lifecycle bundle partition is invalid")
    for field in (
        "attempt_ref",
        "projected_attempt_ledger_ref",
        "raw_ledger_prefix_verification_ref",
        "selected_lifecycle_ref",
        "attempt_cleanup_projection_ref",
    ):
        _ref(payload[field], name=field)
    _ref_list(payload["screen_group_lifecycle_projection_refs"], name="screen_group_lifecycle_projection_refs", exact_count=12)
    closure = _validated_outer_envelopes(payload, registry_name="lifecycle_bundle_v3")
    lifecycle_items = [
        (item, ref_value)
        for item, ref_value, name in closure
        if name == "benchmark_v2_lifecycle_verified_projection_v1"
    ]
    screens = [pair for pair in lifecycle_items if pair[0]["lifecycle_kind"] == "screen_group"]
    cleanup = [pair for pair in lifecycle_items if pair[0]["lifecycle_kind"] == "cleanup"]
    attempts = [pair for pair in lifecycle_items if pair[0]["lifecycle_kind"] == "attempt"]
    classes = [name for _, _, name in closure]
    if len(screens) != 12 or not cleanup or len(attempts) != 1:
        raise ValueError("lifecycle closure lifecycle classes are incomplete")
    if classes.count("benchmark_v2_attempt_journal_terminal_event_verified_projection_v1") != 1:
        raise ValueError("lifecycle closure requires one journal terminal event")
    if classes.count("benchmark_v2_projected_attempt_ledger_v1") != 1:
        raise ValueError("lifecycle closure requires one projected ledger")
    if not any(name == "benchmark_v2_runner_event_verified_projection_v1" for name in classes):
        raise ValueError("lifecycle closure requires runner events")
    expected_screens = [ref_value for _, ref_value in screens]
    if expected_screens != payload["screen_group_lifecycle_projection_refs"]:
        raise ValueError("lifecycle closure screen-group refs mismatch")
    if attempts[0][1] != payload["selected_lifecycle_ref"]:
        raise ValueError("lifecycle closure selected attempt ref mismatch")
    selected_attempt_ref = _ref(payload["attempt_ref"], name="attempt_ref")
    selected_cleanup_ref = _ref(
        payload["attempt_cleanup_projection_ref"],
        name="attempt_cleanup_projection_ref",
    )
    selected_lifecycle = attempts[0][0]
    if _ref(selected_lifecycle["attempt_ref"], name="selected lifecycle attempt_ref") != selected_attempt_ref:
        raise ValueError("lifecycle closure selected lifecycle attempt mismatch")
    selected_parents = selected_lifecycle["parent_refs"]
    assert isinstance(selected_parents, Mapping)
    if _ref(selected_parents["cleanup_projection_ref"], name="selected lifecycle cleanup ref") != selected_cleanup_ref:
        raise ValueError("lifecycle closure selected cleanup ref mismatch")

    runner_events = [
        item
        for item, _, name in closure
        if name == "benchmark_v2_runner_event_verified_projection_v1"
    ]
    cleanup_events = [item for item in runner_events if item["event_kind"] == "cleanup"]
    cleanup_by_attempt: dict[bytes, tuple[Mapping[str, object], dict[str, str]]] = {}
    for lifecycle, ref_value in cleanup:
        attempt_key = _canonical_bytes(
            _ref(lifecycle["attempt_ref"], name="cleanup lifecycle attempt_ref")
        )
        if attempt_key in cleanup_by_attempt:
            raise ValueError("lifecycle closure has duplicate cleanup attempt")
        cleanup_by_attempt[attempt_key] = (lifecycle, ref_value)
    cleanup_event_by_attempt: dict[bytes, Mapping[str, object]] = {}
    for event in cleanup_events:
        attempt_key = _canonical_bytes(
            _ref(event["attempt_ref"], name="cleanup event attempt_ref")
        )
        if attempt_key in cleanup_event_by_attempt:
            raise ValueError("lifecycle closure has duplicate cleanup event attempt")
        cleanup_event_by_attempt[attempt_key] = event
    if set(cleanup_by_attempt) != set(cleanup_event_by_attempt):
        raise ValueError("lifecycle closure cleanup attempts do not match runner events")
    for attempt_key, (lifecycle, lifecycle_ref) in cleanup_by_attempt.items():
        event = cleanup_event_by_attempt[attempt_key]
        event_refs = event["load_bearing_refs"]
        lifecycle_parents = lifecycle["parent_refs"]
        assert isinstance(event_refs, Mapping) and isinstance(lifecycle_parents, Mapping)
        if _ref(event_refs["cleanup_projection_ref"], name="cleanup event projection ref") != lifecycle_ref:
            raise ValueError("lifecycle closure cleanup event projection mismatch")
        if _ref(event_refs["cleanup_receipt_ref"], name="cleanup event receipt ref") != _ref(
            lifecycle_parents["cleanup_receipt_ref"], name="cleanup lifecycle receipt ref"
        ):
            raise ValueError("lifecycle closure cleanup receipt mismatch")
    selected_key = _canonical_bytes(selected_attempt_ref)
    if selected_key not in cleanup_by_attempt or cleanup_by_attempt[selected_key][1] != selected_cleanup_ref:
        raise ValueError("lifecycle closure selected cleanup ref mismatch")

    terminal = next(
        item
        for item, _, name in closure
        if name == "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1"
    )
    if (
        _ref(terminal["attempt_ref"], name="terminal attempt_ref") != selected_attempt_ref
        or _ref(terminal["cleanup_projection_ref"], name="terminal cleanup ref")
        != selected_cleanup_ref
    ):
        raise ValueError("lifecycle closure terminal binding mismatch")
    ledger_ref = next(
        ref_value
        for _, ref_value, name in closure
        if name == "benchmark_v2_projected_attempt_ledger_v1"
    )
    if ledger_ref != payload["projected_attempt_ledger_ref"]:
        raise ValueError("lifecycle closure projected ledger ref mismatch")
    ledger = next(
        item
        for item, _, name in closure
        if name == "benchmark_v2_projected_attempt_ledger_v1"
    )
    by_ref = {
        _canonical_bytes(ref_value): (item, {})
        for item, ref_value, _ in closure
    }
    _validate_projected_ledger_graph(ledger, by_ref)
    ledger_entries = ledger["entries"]
    assert isinstance(ledger_entries, list)
    entries_by_attempt = {
        _canonical_bytes(_ref(entry["attempt_ref"], name="ledger entry attempt_ref")): entry
        for entry in ledger_entries
        if isinstance(entry, Mapping)
    }
    for attempt_key in cleanup_by_attempt:
        entry = entries_by_attempt.get(attempt_key)
        if entry is None:
            raise ValueError("lifecycle closure cleanup attempt is absent from projected ledger")
        if attempt_key == selected_key:
            if (
                entry["observed_state"] != "result"
                or entry["selection_eligible"] is not True
                or _ref(entry["lifecycle_ref"], name="selected entry lifecycle_ref")
                != payload["selected_lifecycle_ref"]
            ):
                raise ValueError("lifecycle closure selected ledger entry is invalid")
        elif (
            entry["observed_state"] != "cleanup"
            or entry["selection_eligible"] is not False
            or entry["lifecycle_ref"] is not None
        ):
            raise ValueError("lifecycle closure prior cleanup entry must remain ineligible")
    _safety(payload["safety"])


def _validate_runner_prefix(payload: Mapping[str, object]) -> None:
    if payload["partition"] not in {"regression", "holdout"}:
        raise ValueError("runner prefix partition is invalid")
    for field in ("raw_prefix_sha256", "through_result_terminal_envelope_sha256"):
        _sha(payload[field], name=field)
    _ledger_pre_result_ref(payload["attempt_ledger_pre_result_ref"], name="attempt_ledger_pre_result_ref")
    _nonnegative(payload["through_result_terminal_sequence"], name="through_result_terminal_sequence")
    _ref(payload["attempt_ref"], name="attempt_ref", prefixes=("runner-attempt",))
    _file_ref(payload["body_file_ref"], name="body_file_ref")
    _ref(payload["cleanup_event_projection_ref"], name="cleanup_event_projection_ref", prefixes=("verified-runner-event",))
    _file_ref(payload["result_file_ref"], name="result_file_ref")
    _ref(payload["result_event_projection_ref"], name="result_event_projection_ref", prefixes=("verified-runner-event",))
    if payload["verified"] is not True:
        raise ValueError("runner prefix verified literal is invalid")
    _safety(payload["safety"])


def _validate_journal_projection(payload: Mapping[str, object]) -> None:
    _ref(payload["attempt_ref"], name="attempt_ref", prefixes=("runner-attempt",))
    _sha(payload["raw_journal_sha256"], name="raw_journal_sha256")
    _ref(payload["terminal_event_ref"], name="terminal_event_ref", prefixes=("verified-attempt-journal-terminal-event",))
    started = _nonnegative(payload["started_request_count"], name="started_request_count")
    terminal = _nonnegative(payload["terminal_or_unknown_request_count"], name="terminal_or_unknown_request_count")
    if started != terminal:
        raise ValueError("attempt journal request counts differ")
    _ref(payload["cleanup_projection_ref"], name="cleanup_projection_ref", prefixes=("verified-lifecycle",))
    if payload["verified"] is not True:
        raise ValueError("attempt journal verified literal is invalid")
    _safety(payload["safety"])


def _validate_actual_body(payload: Mapping[str, object]) -> None:
    _ref(payload["attempt_ref"], name="attempt_ref", prefixes=("runner-attempt",))
    _text(payload["body_contract_version"], name="body_contract_version")
    for field in ("raw_file_sha256", "body_content_sha256", "case_arm_multiset_sha256"):
        _sha(payload[field], name=field)
    if _positive(payload["screen_group_count"], name="screen_group_count") != 12:
        raise ValueError("actual body must contain 12 screen groups")
    _ref_list(payload["pre_vista_evidence_refs"], name="pre_vista_evidence_refs", exact_count=12)
    if payload["verified"] is not True:
        raise ValueError("actual body verified literal is invalid")
    _safety(payload["safety"])


def _validate_actual_result(payload: Mapping[str, object]) -> None:
    _ref(payload["attempt_ref"], name="attempt_ref", prefixes=("runner-attempt",))
    _text(payload["result_contract_version"], name="result_contract_version")
    for field in ("raw_file_sha256", "result_content_sha256"):
        _sha(payload[field], name=field)
    _ref(payload["body_projection_ref"], name="body_projection_ref", prefixes=("verified-actual-body",))
    _ref(payload["cleanup_projection_ref"], name="cleanup_projection_ref", prefixes=("verified-lifecycle",))
    _ledger_pre_result_ref(payload["attempt_ledger_pre_result_ref"], name="attempt_ledger_pre_result_ref")
    _ref(payload["runner_ledger_prefix_projection_ref"], name="runner_ledger_prefix_projection_ref", prefixes=("verified-runner-ledger-prefix",))
    _ref(payload["result_event_projection_ref"], name="result_event_projection_ref", prefixes=("verified-runner-event",))
    if payload["verified"] is not True:
        raise ValueError("actual result verified literal is invalid")
    _safety(payload["safety"])


def _sort_by_ref(value: Mapping[str, object], registry_name: str) -> tuple[object, ...]:
    return (str(value["artifact_id"]), str(value["content_sha256"]))


def _sort_runner_event(value: Mapping[str, object], registry_name: str) -> tuple[object, ...]:
    return (_nonnegative(value["sequence"], name="sequence"),)


def _sort_lifecycle(value: Mapping[str, object], registry_name: str) -> tuple[object, ...]:
    if value["lifecycle_kind"] == "screen_group":
        parent = value["parent_refs"]
        assert isinstance(parent, Mapping)
        actual = parent["actual_screen_group_ref"]
        assert isinstance(actual, Mapping)
        return (str(actual["id"]),)
    return (str(value["artifact_id"]),)


def _roles(**values: _RefRole) -> Mapping[str, _RefRole]:
    return MappingProxyType(dict(values))


def _ranks(**values: int) -> Mapping[str, int]:
    return MappingProxyType(dict(values))


def _spec(
    contract_version: str,
    artifact_prefix: str,
    semantic_fields: Sequence[str],
    validator: Callable[[Mapping[str, object]], None],
    roles: Mapping[str, _RefRole],
    registries: Sequence[str],
    ranks: Mapping[str, int],
    sort_key: Callable[[Mapping[str, object], str], tuple[object, ...]] = _sort_by_ref,
) -> _ContractSpec:
    return _ContractSpec(
        contract_version=contract_version,
        artifact_prefix=artifact_prefix,
        semantic_fields=tuple(semantic_fields),
        semantic_validator=validator,
        ref_role_schema=roles,
        allowed_registry_names=frozenset(registries),
        class_ranks=ranks,
        semantic_sort_key=sort_key,
    )


_INTERNAL_NESTED = _RefRole("exact_ref", ("benchmark_v2_nested_provider_evidence_ref_v1",), False)
_EXTERNAL_REF = _RefRole("exact_ref", (), True)
_EXTERNAL_CASE_REF = _RefRole("closed_case_ref", (), True)


_CONTRACTS_MUTABLE = {
    "benchmark_v2_nested_provider_evidence_ref_v1": _spec(
        "benchmark_v2_nested_provider_evidence_ref_v1",
        "nested-provider-evidence",
        ("evidence_kind", "case_ref", "actual_screen_group_ref", "canonical_value_sha256", "safety"),
        _validate_nested,
        _roles(case_ref=_EXTERNAL_CASE_REF, actual_screen_group_ref=_EXTERNAL_REF),
        ("prediction_selection_v1", "prediction_run_v3"),
        _ranks(prediction_selection_v1=5, prediction_run_v3=5),
    ),
    "sealed_prediction_source_parent_v1": _spec(
        "sealed_prediction_source_parent_v1",
        "prediction-source-parent",
        ("case_ref", "arm_scope", "source_kind", "evidence_refs", "actual_screen_group_ref", "capture_ref", "safety"),
        _validate_source,
        _roles(
            case_ref=_EXTERNAL_CASE_REF,
            actual_screen_group_ref=_EXTERNAL_REF,
            capture_ref=_EXTERNAL_REF,
            **{
                "evidence_refs.incumbent_response_ref": _INTERNAL_NESTED,
                "evidence_refs.available_action_ref": _INTERNAL_NESTED,
                "evidence_refs.omni_item_ref": _INTERNAL_NESTED,
                "evidence_refs.fusion_candidate_ref": _INTERNAL_NESTED,
                "evidence_refs.omni_inventory_ref": _RefRole("opaque_raw_ref", external=True, raw_class="omni_inventory"),
                "evidence_refs.qwen_bindings_ref": _RefRole("opaque_raw_ref", external=True, raw_class="qwen_bindings"),
                "evidence_refs.fusion_result_ref": _RefRole("opaque_raw_ref", external=True, raw_class="fusion_result"),
            },
        ),
        ("prediction_selection_v1", "prediction_run_v3"),
        _ranks(prediction_selection_v1=6, prediction_run_v3=6),
    ),
    "sealed_prediction_bbox_v1": _spec(
        "sealed_prediction_bbox_v1",
        "prediction-bbox",
        ("case_id", "arm_scope", "candidate_id", "coordinate_space", "xyxy", "capture_ref", "source_parent_ref", "safety"),
        _validate_bbox,
        _roles(capture_ref=_EXTERNAL_REF, source_parent_ref=_RefRole("exact_ref", ("sealed_prediction_source_parent_v1",))),
        ("prediction_selection_v1", "prediction_run_v3"),
        _ranks(prediction_selection_v1=7, prediction_run_v3=7),
    ),
    "sealed_target_binding_v4": _spec(
        "sealed_target_binding_v4",
        "target-binding",
        ("case_id", "arm_scope", "candidate_id", "source_parent_ref", "capture_ref", "bbox_ref", "safety"),
        _validate_binding,
        _roles(
            source_parent_ref=_RefRole("exact_ref", ("sealed_prediction_source_parent_v1",)),
            capture_ref=_EXTERNAL_REF,
            bbox_ref=_RefRole("exact_ref", ("sealed_prediction_bbox_v1",)),
        ),
        ("prediction_selection_v1", "prediction_run_v3"),
        _ranks(prediction_selection_v1=8, prediction_run_v3=8),
    ),
    "sealed_vista_request_v4": _spec(
        "sealed_vista_request_v4",
        "vista-request",
        ("case_id", "arm_scope", "candidate_id", "target_binding_ref", "source_parent_ref", "capture_ref", "bbox_ref", "submitted_request_ref", "submission_status", "safety"),
        _validate_vista_request,
        _roles(
            target_binding_ref=_RefRole("exact_ref", ("sealed_target_binding_v4",)),
            source_parent_ref=_RefRole("exact_ref", ("sealed_prediction_source_parent_v1",)),
            capture_ref=_EXTERNAL_REF,
            bbox_ref=_RefRole("exact_ref", ("sealed_prediction_bbox_v1",)),
            submitted_request_ref=_RefRole("opaque_raw_ref", external=True, raw_class="submitted_vista_request"),
        ),
        ("prediction_selection_v1", "prediction_run_v3"),
        _ranks(prediction_selection_v1=9, prediction_run_v3=9),
    ),
    "benchmark_v2_runner_event_verified_projection_v1": _spec(
        "benchmark_v2_runner_event_verified_projection_v1",
        "verified-runner-event",
        ("partition", "event_kind", "sequence", "attempt_ref", "previous_event_projection_ref", "raw_event_sha256", "load_bearing_refs", "safety"),
        _validate_runner_event,
        _roles(
            attempt_ref=_EXTERNAL_REF,
            previous_event_projection_ref=_RefRole("exact_ref", ("benchmark_v2_runner_event_verified_projection_v1",), nullable=True),
            **{
                "load_bearing_refs.attempt_ref": _EXTERNAL_REF,
                "load_bearing_refs.body_file_ref": _RefRole("pathless_file_ref", external=True),
                "load_bearing_refs.cleanup_receipt_ref": _RefRole("opaque_raw_ref", external=True, raw_class="cleanup_receipt"),
                "load_bearing_refs.cleanup_projection_ref": _RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
                "load_bearing_refs.result_file_ref": _RefRole("pathless_file_ref", external=True),
                "load_bearing_refs.attempt_ledger_pre_result_ref": _RefRole("closed_logical_ref", external=True),
            },
        ),
        ("prediction_run_v3", "lifecycle_bundle_v3"),
        _ranks(prediction_run_v3=11, lifecycle_bundle_v3=5),
        _sort_runner_event,
    ),
    "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1": _spec(
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
        "verified-attempt-journal-terminal-event",
        ("attempt_ref", "sequence", "phase", "event_kind", "raw_event_sha256", "predecessor_content_sha256", "cleanup_receipt_ref", "cleanup_projection_ref", "safety"),
        _validate_journal_terminal,
        _roles(
            attempt_ref=_EXTERNAL_REF,
            cleanup_receipt_ref=_RefRole("opaque_raw_ref", external=True, raw_class="cleanup_receipt"),
            cleanup_projection_ref=_RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
        ),
        ("lifecycle_bundle_v3",),
        _ranks(lifecycle_bundle_v3=3),
    ),
    "benchmark_v2_lifecycle_verified_projection_v1": _spec(
        "benchmark_v2_lifecycle_verified_projection_v1",
        "verified-lifecycle",
        ("attempt_ref", "lifecycle_kind", "raw_evidence_sha256", "terminal_status", "cleanup_stable_zero", "resource_counts", "started_request_count", "terminal_or_unknown_request_count", "parent_refs", "safety"),
        _validate_lifecycle,
        _roles(
            attempt_ref=_EXTERNAL_REF,
            **{
                "parent_refs.cleanup_receipt_ref": _RefRole("opaque_raw_ref", external=True, raw_class="cleanup_receipt"),
                "parent_refs.actual_screen_group_ref": _EXTERNAL_REF,
                "parent_refs.provider_group_ref": _EXTERNAL_REF,
                "parent_refs.attempt_journal_projection_ref": _RefRole("exact_ref", ("benchmark_v2_attempt_journal_verified_projection_v1",), True),
                "parent_refs.cleanup_projection_ref": _RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
                "parent_refs.terminal_event_ref": _RefRole("exact_ref", ("benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",)),
                "parent_refs.screen_group_lifecycle_projection_refs": _RefRole("ordered_exact_ref_list", ("benchmark_v2_lifecycle_verified_projection_v1",), ordered=True),
            },
        ),
        ("lifecycle_bundle_v3",),
        _ranks(lifecycle_bundle_v3=1),
        _sort_lifecycle,
    ),
    "benchmark_v2_projected_attempt_ledger_v1": _spec(
        "benchmark_v2_projected_attempt_ledger_v1",
        "projected-attempt-ledger",
        ("benchmark_release_id", "partition", "raw_ledger_prefix_verification_ref", "entries", "selected_attempt_ref", "selected_lifecycle_ref", "safety"),
        _validate_projected_ledger,
        _roles(
            raw_ledger_prefix_verification_ref=_RefRole("exact_ref", ("benchmark_v2_runner_ledger_prefix_verified_projection_v1",), True),
            selected_attempt_ref=_EXTERNAL_REF,
            selected_lifecycle_ref=_RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
            **{
                "entries.attempt_ref": _EXTERNAL_REF,
                "entries.event_projection_refs": _RefRole("ordered_exact_ref_list", ("benchmark_v2_runner_event_verified_projection_v1",), ordered=True),
                "entries.lifecycle_ref": _RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",), nullable=True),
            },
        ),
        ("prediction_run_v3", "lifecycle_bundle_v3"),
        _ranks(prediction_run_v3=12, lifecycle_bundle_v3=6),
    ),
    "benchmark_v2_prediction_run_v3": _spec(
        "benchmark_v2_prediction_run_v3",
        "prediction-run",
        ("benchmark_release_id", "partition", "corpus_parent_ref", "provider_manifest_ref", "provider_corpus_ref", "attempt_ref", "projected_attempt_ledger_ref", "raw_ledger_prefix_verification_ref", "automatic_prediction_ref", "selected_lifecycle_ref", "sealed_artifact_envelopes", "safety"),
        _validate_prediction_run,
        _roles(
            corpus_parent_ref=_EXTERNAL_REF,
            provider_manifest_ref=_EXTERNAL_REF,
            provider_corpus_ref=_EXTERNAL_REF,
            attempt_ref=_EXTERNAL_REF,
            projected_attempt_ledger_ref=_RefRole("exact_ref", ("benchmark_v2_projected_attempt_ledger_v1",)),
            raw_ledger_prefix_verification_ref=_RefRole("exact_ref", ("benchmark_v2_runner_ledger_prefix_verified_projection_v1",), True),
            automatic_prediction_ref=_EXTERNAL_REF,
            selected_lifecycle_ref=_RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
        ),
        ("prediction_run_v3",),
        _ranks(prediction_run_v3=100),
    ),
    "benchmark_v2_lifecycle_bundle_v3": _spec(
        "benchmark_v2_lifecycle_bundle_v3",
        "lifecycle-bundle",
        ("benchmark_release_id", "partition", "attempt_ref", "projected_attempt_ledger_ref", "raw_ledger_prefix_verification_ref", "selected_lifecycle_ref", "attempt_cleanup_projection_ref", "screen_group_lifecycle_projection_refs", "sealed_artifact_envelopes", "safety"),
        _validate_lifecycle_bundle,
        _roles(
            attempt_ref=_EXTERNAL_REF,
            projected_attempt_ledger_ref=_RefRole("exact_ref", ("benchmark_v2_projected_attempt_ledger_v1",)),
            raw_ledger_prefix_verification_ref=_RefRole("exact_ref", ("benchmark_v2_runner_ledger_prefix_verified_projection_v1",), True),
            selected_lifecycle_ref=_RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
            attempt_cleanup_projection_ref=_RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
            screen_group_lifecycle_projection_refs=_RefRole("ordered_exact_ref_list", ("benchmark_v2_lifecycle_verified_projection_v1",), ordered=True),
        ),
        ("lifecycle_bundle_v3",),
        _ranks(lifecycle_bundle_v3=100),
    ),
    "benchmark_v2_runner_ledger_prefix_verified_projection_v1": _spec(
        "benchmark_v2_runner_ledger_prefix_verified_projection_v1",
        "verified-runner-ledger-prefix",
        ("partition", "raw_prefix_sha256", "attempt_ledger_pre_result_ref", "through_result_terminal_sequence", "through_result_terminal_envelope_sha256", "attempt_ref", "body_file_ref", "cleanup_event_projection_ref", "result_file_ref", "result_event_projection_ref", "verified", "safety"),
        _validate_runner_prefix,
        _roles(
            attempt_ledger_pre_result_ref=_RefRole("closed_logical_ref", external=True),
            attempt_ref=_EXTERNAL_REF,
            body_file_ref=_RefRole("pathless_file_ref", external=True),
            cleanup_event_projection_ref=_RefRole("exact_ref", ("benchmark_v2_runner_event_verified_projection_v1",)),
            result_file_ref=_RefRole("pathless_file_ref", external=True),
            result_event_projection_ref=_RefRole("exact_ref", ("benchmark_v2_runner_event_verified_projection_v1",)),
        ),
        ("verified_parents_v1",),
        _ranks(verified_parents_v1=1),
    ),
    "benchmark_v2_attempt_journal_verified_projection_v1": _spec(
        "benchmark_v2_attempt_journal_verified_projection_v1",
        "verified-attempt-journal",
        ("attempt_ref", "raw_journal_sha256", "terminal_event_ref", "started_request_count", "terminal_or_unknown_request_count", "cleanup_projection_ref", "verified", "safety"),
        _validate_journal_projection,
        _roles(
            attempt_ref=_EXTERNAL_REF,
            terminal_event_ref=_RefRole("exact_ref", ("benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",)),
            cleanup_projection_ref=_RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
        ),
        ("verified_parents_v1",),
        _ranks(verified_parents_v1=2),
    ),
    "benchmark_v2_actual_body_verified_projection_v1": _spec(
        "benchmark_v2_actual_body_verified_projection_v1",
        "verified-actual-body",
        ("attempt_ref", "body_contract_version", "raw_file_sha256", "body_content_sha256", "screen_group_count", "case_arm_multiset_sha256", "pre_vista_evidence_refs", "verified", "safety"),
        _validate_actual_body,
        _roles(attempt_ref=_EXTERNAL_REF, pre_vista_evidence_refs=_RefRole("ordered_exact_ref_list", external=True, ordered=True)),
        ("verified_parents_v1",),
        _ranks(verified_parents_v1=3),
    ),
    "benchmark_v2_actual_result_verified_projection_v1": _spec(
        "benchmark_v2_actual_result_verified_projection_v1",
        "verified-actual-result",
        ("attempt_ref", "result_contract_version", "raw_file_sha256", "result_content_sha256", "body_projection_ref", "cleanup_projection_ref", "attempt_ledger_pre_result_ref", "runner_ledger_prefix_projection_ref", "result_event_projection_ref", "verified", "safety"),
        _validate_actual_result,
        _roles(
            attempt_ref=_EXTERNAL_REF,
            body_projection_ref=_RefRole("exact_ref", ("benchmark_v2_actual_body_verified_projection_v1",)),
            cleanup_projection_ref=_RefRole("exact_ref", ("benchmark_v2_lifecycle_verified_projection_v1",)),
            attempt_ledger_pre_result_ref=_RefRole("closed_logical_ref", external=True),
            runner_ledger_prefix_projection_ref=_RefRole("exact_ref", ("benchmark_v2_runner_ledger_prefix_verified_projection_v1",)),
            result_event_projection_ref=_RefRole("exact_ref", ("benchmark_v2_runner_event_verified_projection_v1",)),
        ),
        ("verified_parents_v1",),
        _ranks(verified_parents_v1=4),
    ),
}
_CONTRACTS: Mapping[str, _ContractSpec] = MappingProxyType(_CONTRACTS_MUTABLE)

_RAW_CLASSES: Mapping[str, _RawClass] = MappingProxyType(
    {
        "omni_inventory": _RawClass(
            "hybrid_omni_inventory_v1",
            "omni-inventory",
            b"benchmark-v2-omni-inventory\0",
            frozenset({"prediction_run_v3"}),
            _ranks(prediction_run_v3=1),
        ),
        "qwen_bindings": _RawClass(
            "hybrid_qwen_bindings_v1",
            "qwen-bindings",
            b"benchmark-v2-qwen-bindings\0",
            frozenset({"prediction_run_v3"}),
            _ranks(prediction_run_v3=2),
        ),
        "fusion_result": _RawClass(
            "hybrid_fusion_result_v1",
            "fusion-result",
            b"benchmark-v2-fusion-result\0",
            frozenset({"prediction_run_v3"}),
            _ranks(prediction_run_v3=3),
        ),
        "submitted_vista_request": _RawClass(
            "hybrid_vista_refinement_request_v1",
            "submitted-vista-request",
            b"benchmark-v2-submitted-vista-request\0",
            frozenset({"prediction_run_v3"}),
            _ranks(prediction_run_v3=4),
        ),
        "automatic_prediction": _RawClass(
            "automatic_prediction_v2",
            "automatic",
            None,
            frozenset({"prediction_run_v3"}),
            _ranks(prediction_run_v3=10),
        ),
        "cleanup_receipt": _RawClass(
            "benchmark_v2_attempt_cleanup_receipt_v1",
            "attempt-cleanup-receipt",
            b"benchmark-v2-attempt-cleanup-receipt\0",
            frozenset(),
            _ranks(),
        ),
    }
)
_RAW_CONTRACTS: Mapping[str, str] = MappingProxyType(
    {spec.contract_version: name for name, spec in _RAW_CLASSES.items()}
)


def _registered(contract_version: object) -> _ContractSpec:
    if not isinstance(contract_version, str) or contract_version not in _CONTRACTS:
        raise ValueError("unknown pathless contract")
    return _CONTRACTS[contract_version]


def _validated_semantic(spec: _ContractSpec, payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("pathless semantic payload must be an object")
    result = deepcopy(dict(payload))
    if {"contract_version", "artifact_id", "content_sha256"} & set(result):
        raise ValueError("caller identity fields are forbidden")
    _closed(result, spec.semantic_fields, name=f"{spec.contract_version} semantic payload")
    _validate_json_value(result, name=f"{spec.contract_version} semantic payload")
    spec.semantic_validator(result)
    return result


def seal_pathless_projection(
    *, contract_version: str, semantic_payload: Mapping[str, object]
) -> dict[str, object]:
    """按注册合同验证语义后生成不可由调用者指定身份的投影。"""

    spec = _registered(contract_version)
    payload = _validated_semantic(spec, semantic_payload)
    semantic = {"contract_version": contract_version, **payload}
    semantic_sha256 = hashlib.sha256(
        contract_version.encode("utf-8") + b"\0" + _canonical_bytes(semantic)
    ).hexdigest()
    without_content = {
        "contract_version": contract_version,
        "artifact_id": f"{spec.artifact_prefix}/{semantic_sha256}",
        **payload,
    }
    return {
        **without_content,
        "content_sha256": hashlib.sha256(_canonical_bytes(without_content)).hexdigest(),
    }


def _validated_artifact(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("pathless artifact must be an object")
    item = deepcopy(dict(value))
    spec = _registered(item.get("contract_version"))
    expected_fields = {"contract_version", "artifact_id", "content_sha256", *spec.semantic_fields}
    _closed(item, expected_fields, name=spec.contract_version)
    _validate_json_value(item, name=spec.contract_version)
    payload = {field: deepcopy(item[field]) for field in spec.semantic_fields}
    expected = seal_pathless_projection(contract_version=spec.contract_version, semantic_payload=payload)
    if item.get("artifact_id") != expected["artifact_id"]:
        raise ValueError("pathless artifact semantic identity mismatch")
    if item.get("content_sha256") != expected["content_sha256"]:
        raise ValueError("pathless artifact content identity mismatch")
    return item


def pathless_artifact_ref(value: Mapping[str, object]) -> dict[str, str]:
    """验证完整投影后返回精确无路径引用。"""

    item = _validated_artifact(value)
    return {"id": str(item["artifact_id"]), "content_sha256": str(item["content_sha256"])}


def seal_pathless_envelope(value: Mapping[str, object]) -> dict[str, object]:
    """仅为已通过注册验证的投影发布规范字节信封。"""

    item = _validated_artifact(value)
    raw = _canonical_bytes(item)
    return {
        "ref": pathless_artifact_ref(item),
        "canonical_bytes_b64": base64.b64encode(raw).decode("ascii"),
    }


def _resolve_role(role: str, context: Mapping[str, object]) -> tuple[_ContractSpec, str, _RefRole]:
    if not isinstance(role, str) or not role:
        raise ValueError("unknown ref role")
    contract_version = context.get("contract_version")
    if not isinstance(contract_version, str):
        raise ValueError("typed ref role requires contract_version context")
    spec = _registered(contract_version)
    if role not in spec.ref_role_schema:
        raise ValueError("unknown ref role; untyped refs fail closed")
    return spec, role, spec.ref_role_schema[role]


def _raw_bytes_for_role(role: str, context: Mapping[str, object]) -> bytes:
    values = context.get("opaque_raw_canonical_bytes")
    if not isinstance(values, Mapping):
        raise ValueError("opaque raw canonical bytes are required")
    candidates = (role, role.rsplit(".", 1)[-1])
    raw: object = None
    for candidate in candidates:
        if candidate in values:
            raw = values[candidate]
            break
    if not isinstance(raw, bytes):
        raise ValueError("opaque raw canonical bytes are required")
    return raw


def _decode_raw_bytes(raw_class: str, raw: bytes) -> dict[str, object]:
    try:
        spec = _RAW_CLASSES[raw_class]
    except KeyError as exc:
        raise ValueError("unknown opaque raw class") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("opaque raw canonical bytes are invalid") from exc
    if not isinstance(decoded, Mapping) or decoded.get("contract_version") != spec.contract_version:
        raise ValueError("opaque raw contract is invalid")
    _validate_raw_public_json(decoded, name=f"{raw_class} raw evidence")
    from app.learn.recognition.uei.canonical import canonical_json_bytes

    if canonical_json_bytes(decoded) != raw:
        raise ValueError("opaque raw bytes are not canonical")
    return deepcopy(dict(decoded))


def _unseal_raw_payload(value: Mapping[str, object], *, name: str) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import content_sha256

    result = deepcopy(dict(value))
    declared = result.pop("content_sha256", None)
    if not isinstance(declared, str) or declared != content_sha256(dict(value)):
        raise ValueError(f"{name} sealed content identity is invalid")
    return result


def _same_capture_candidates(
    value: Mapping[str, object], candidates: Sequence[Mapping[str, object]], *, name: str
) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import canonical_json_bytes

    capture = value.get("capture_identity")
    matches = [
        candidate
        for candidate in candidates
        if canonical_json_bytes(candidate.get("capture_identity"))
        == canonical_json_bytes(capture)
    ]
    if len(matches) != 1:
        raise ValueError(f"{name} has no unique same-capture parent")
    return deepcopy(dict(matches[0]))


def _validate_raw_class_value(
    raw_class: str,
    value: Mapping[str, object],
    *,
    validated_by_class: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    if raw_class == "omni_inventory":
        from app.learn.hybrid.contracts import validate_omni_inventory

        return validate_omni_inventory(_unseal_raw_payload(value, name="Omni inventory"))
    if raw_class == "qwen_bindings":
        from app.learn.hybrid.contracts import validate_qwen_bindings

        payload = _unseal_raw_payload(value, name="Qwen bindings")
        inventory = _same_capture_candidates(
            payload,
            validated_by_class.get("omni_inventory", ()),
            name="Qwen bindings",
        )
        return validate_qwen_bindings(payload, inventory)
    if raw_class == "fusion_result":
        from app.learn.hybrid.contracts import validate_fusion_result

        payload = _unseal_raw_payload(value, name="fusion result")
        inventory = _same_capture_candidates(
            payload,
            validated_by_class.get("omni_inventory", ()),
            name="fusion result Omni lineage",
        )
        bindings = _same_capture_candidates(
            payload,
            validated_by_class.get("qwen_bindings", ()),
            name="fusion result Qwen lineage",
        )
        return validate_fusion_result(payload, inventory, bindings)
    if raw_class == "submitted_vista_request":
        from app.learn.hybrid.vista_refinement import _validated_request

        return _validated_request(value)
    if raw_class == "automatic_prediction":
        from app.learn.hybrid.benchmark_v2_predictions import _validate_pre

        return _validate_pre(value)
    if raw_class == "cleanup_receipt":
        from app.learn.hybrid.benchmark_v2_lifecycle import _s13_cleanup_receipt

        return _s13_cleanup_receipt(value)
    raise ValueError("unknown opaque raw class")


def _raw_context_values(context: Mapping[str, object]) -> dict[str, list[dict[str, object]]]:
    raw_values = context.get("opaque_raw_canonical_bytes")
    if not isinstance(raw_values, Mapping):
        return {}
    result: dict[str, list[dict[str, object]]] = {}
    for raw_class in ("omni_inventory", "qwen_bindings", "fusion_result"):
        candidate = raw_values.get(raw_class)
        values = candidate if isinstance(candidate, list) else [candidate]
        for raw in values:
            if isinstance(raw, bytes):
                result.setdefault(raw_class, []).append(_decode_raw_bytes(raw_class, raw))
    validated: dict[str, list[dict[str, object]]] = {}
    for raw_class in ("omni_inventory", "qwen_bindings", "fusion_result"):
        for item in result.get(raw_class, []):
            validated.setdefault(raw_class, []).append(
                _validate_raw_class_value(
                    raw_class, item, validated_by_class=validated
                )
            )
    return validated


def _raw_ref(raw_class: str, raw: bytes, decoded: Mapping[str, object]) -> dict[str, str]:
    spec = _RAW_CLASSES[raw_class]
    if raw_class == "automatic_prediction":
        identifier = _public_id(decoded.get("artifact_id"), name="automatic prediction artifact_id")
        return {"id": identifier, "content_sha256": hashlib.sha256(raw).hexdigest()}
    assert spec.identity_domain is not None
    return {
        "id": f"{spec.artifact_prefix}/{hashlib.sha256(spec.identity_domain + raw).hexdigest()}",
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _validated_raw_ref(
    raw_class: str, raw: bytes, *, context: Mapping[str, object] | None = None
) -> dict[str, str]:
    decoded = _decode_raw_bytes(raw_class, raw)
    parents = _raw_context_values(context or {})
    _validate_raw_class_value(raw_class, decoded, validated_by_class=parents)
    return _raw_ref(raw_class, raw, decoded)


def validate_pathless_ref(
    *, role: str, value: Mapping[str, object], context: Mapping[str, object]
) -> dict[str, str]:
    """按合同字段角色验证引用，禁止通用或调用者自定义前缀。"""

    _, _, role_spec = _resolve_role(role, context)
    if role_spec.kind == "pathless_file_ref":
        return _file_ref(value, name=role)  # type: ignore[return-value]
    if role_spec.kind == "closed_case_ref":
        return _case_ref(value, name=role)
    if role_spec.kind == "closed_logical_ref":
        return _ledger_pre_result_ref(value, name=role)  # type: ignore[return-value]
    expected_prefixes = tuple(_registered(target).artifact_prefix for target in role_spec.targets)
    result = _ref(value, name=role, prefixes=expected_prefixes)
    if role_spec.kind == "opaque_raw_ref":
        assert role_spec.raw_class is not None
        expected = _validated_raw_ref(
            role_spec.raw_class,
            _raw_bytes_for_role(role, context),
            context=context,
        )
        if result != expected:
            raise ValueError("opaque raw ref does not match validated canonical bytes")
    elif role_spec.kind not in {"exact_ref", "ordered_exact_ref_list"}:
        raise ValueError("unknown typed ref role")
    return result


def validate_pathless_envelope(
    *, role: str, envelope: Mapping[str, object], context: Mapping[str, object]
) -> dict[str, object]:
    """解码并重规范化信封，再以同一注册语义验证器验证。"""

    if not isinstance(envelope, Mapping):
        raise ValueError("pathless envelope must be an object")
    _closed(envelope, ("ref", "canonical_bytes_b64"), name="pathless envelope")
    encoded = envelope.get("canonical_bytes_b64")
    if not isinstance(encoded, str):
        raise ValueError("pathless envelope canonical bytes are invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pathless envelope canonical bytes are invalid") from exc
    if not isinstance(decoded, Mapping) or _canonical_bytes(decoded) != raw:
        raise ValueError("pathless envelope bytes are not canonical")
    item = _validated_artifact(decoded)
    expected_contract = role
    if role not in _CONTRACTS:
        expected = context.get("expected_contract_version")
        if not isinstance(expected, str):
            raise ValueError("pathless envelope role is not typed")
        expected_contract = expected
    if item["contract_version"] != expected_contract:
        raise ValueError("pathless envelope contract role mismatch")
    if _ref(envelope.get("ref"), name="pathless envelope ref") != pathless_artifact_ref(item):
        raise ValueError("pathless envelope ref mismatch")
    return item


def _value_at(value: Mapping[str, object], path: str) -> list[object]:
    parts = path.split(".")
    current: list[object] = [value]
    for part in parts:
        next_values: list[object] = []
        for item in current:
            if isinstance(item, list):
                for child in item:
                    if isinstance(child, Mapping) and part in child:
                        next_values.append(child[part])
            elif isinstance(item, Mapping) and part in item:
                next_values.append(item[part])
        current = next_values
    return current


def _edges(item: Mapping[str, object]) -> list[tuple[str, _RefRole, dict[str, object]]]:
    if item.get("contract_version") in _RAW_CONTRACTS:
        return []
    spec = _registered(item["contract_version"])
    result: list[tuple[str, _RefRole, dict[str, object]]] = []
    for role, role_spec in spec.ref_role_schema.items():
        for raw in _value_at(item, role):
            if raw is None and role_spec.nullable:
                continue
            values = raw if role_spec.ordered and isinstance(raw, list) else [raw]
            for value in values:
                if role_spec.kind == "pathless_file_ref":
                    result.append((role, role_spec, _file_ref(value, name=role)))
                elif role_spec.kind == "closed_case_ref":
                    result.append((role, role_spec, _case_ref(value, name=role)))
                elif role_spec.kind == "closed_logical_ref":
                    result.append((role, role_spec, _ledger_pre_result_ref(value, name=role)))
                else:
                    prefixes = tuple(_registered(target).artifact_prefix for target in role_spec.targets)
                    result.append((role, role_spec, _ref(value, name=role, prefixes=prefixes)))
    return result


def _validate_projected_ledger_graph(
    ledger: Mapping[str, object],
    by_ref: Mapping[bytes, tuple[dict[str, object], dict[str, object]]],
) -> None:
    expected_kinds = ("opened", "body_complete", "cleanup", "result")
    entries = ledger["entries"]
    assert isinstance(entries, list)
    eligible: list[Mapping[str, object]] = []
    for index, entry in enumerate(entries):
        assert isinstance(entry, Mapping)
        attempt_ref = _ref(entry["attempt_ref"], name=f"entry[{index}].attempt_ref")
        event_refs = _ref_list(
            entry["event_projection_refs"], name=f"entry[{index}].event_projection_refs"
        )
        events: list[Mapping[str, object]] = []
        for event_ref in event_refs:
            resolved = by_ref.get(_canonical_bytes(event_ref))
            if resolved is None:
                raise ValueError("projected ledger event ref is unresolved")
            event = resolved[0]
            if event.get("contract_version") != "benchmark_v2_runner_event_verified_projection_v1":
                raise ValueError("projected ledger event ref has class drift")
            if _ref(event.get("attempt_ref"), name="runner event attempt_ref") != attempt_ref:
                raise ValueError("projected ledger event attempt mismatch")
            events.append(event)
        kinds = tuple(str(event["event_kind"]) for event in events)
        observed = str(entry["observed_state"])
        expected_prefixes = {
            "opened": (("opened",),),
            "body_complete": (("opened", "body_complete"),),
            "cleanup": (
                ("opened", "cleanup"),
                ("opened", "body_complete", "cleanup"),
            ),
            "result": (expected_kinds,),
        }[observed]
        if kinds not in expected_prefixes:
            raise ValueError("projected ledger event prefix is invalid")
        sequences = [int(event["sequence"]) for event in events]
        if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
            raise ValueError("projected ledger event sequence is invalid")
        cleanup_events = [event for event in events if event["event_kind"] == "cleanup"]
        cleanup_ref: dict[str, str] | None = None
        if cleanup_events:
            cleanup_event = cleanup_events[0]
            cleanup_refs = cleanup_event["load_bearing_refs"]
            assert isinstance(cleanup_refs, Mapping)
            cleanup_ref = _ref(
                cleanup_refs["cleanup_projection_ref"],
                name="cleanup event projection ref",
            )
            resolved_cleanup = by_ref.get(_canonical_bytes(cleanup_ref))
            if resolved_cleanup is None:
                raise ValueError("projected ledger cleanup projection ref is unresolved")
            cleanup_lifecycle = resolved_cleanup[0]
            if (
                cleanup_lifecycle.get("contract_version")
                != "benchmark_v2_lifecycle_verified_projection_v1"
                or cleanup_lifecycle.get("lifecycle_kind") != "cleanup"
            ):
                raise ValueError("projected ledger cleanup projection has class drift")
            if _ref(cleanup_lifecycle.get("attempt_ref"), name="cleanup lifecycle attempt_ref") != attempt_ref:
                raise ValueError("projected ledger cleanup lifecycle attempt mismatch")
        lifecycle_ref = entry["lifecycle_ref"]
        if lifecycle_ref is not None:
            resolved_lifecycle = by_ref.get(
                _canonical_bytes(_ref(lifecycle_ref, name=f"entry[{index}].lifecycle_ref"))
            )
            if resolved_lifecycle is None:
                raise ValueError("projected ledger lifecycle ref is unresolved")
            lifecycle = resolved_lifecycle[0]
            if (
                lifecycle.get("contract_version")
                != "benchmark_v2_lifecycle_verified_projection_v1"
                or lifecycle.get("lifecycle_kind") != "attempt"
            ):
                raise ValueError("projected ledger selected lifecycle must be an attempt lifecycle")
            if _ref(lifecycle.get("attempt_ref"), name="attempt lifecycle attempt_ref") != attempt_ref:
                raise ValueError("projected ledger lifecycle attempt mismatch")
            parents = lifecycle.get("parent_refs")
            if not isinstance(parents, Mapping) or cleanup_ref is None:
                raise ValueError("projected ledger selected lifecycle cleanup is missing")
            if _ref(parents.get("cleanup_projection_ref"), name="attempt lifecycle cleanup ref") != cleanup_ref:
                raise ValueError("projected ledger selected lifecycle cleanup mismatch")
        elif entry["selection_eligible"] is True:
            raise ValueError("projected ledger eligible lifecycle is missing")
        if entry["selection_eligible"] is True:
            if lifecycle_ref is None or observed != "result":
                raise ValueError("projected ledger eligible entry is incomplete")
            eligible.append(entry)
        elif lifecycle_ref is not None:
            raise ValueError("projected ledger ineligible entry cannot carry lifecycle")
    if not eligible:
        raise ValueError("projected ledger has no eligible entry")
    first = eligible[0]
    if (
        _ref(ledger["selected_attempt_ref"], name="selected_attempt_ref")
        != _ref(first["attempt_ref"], name="first eligible attempt_ref")
        or _ref(ledger["selected_lifecycle_ref"], name="selected_lifecycle_ref")
        != _ref(first["lifecycle_ref"], name="first eligible lifecycle_ref")
    ):
        raise ValueError("projected ledger selected refs are not earliest eligible")


def _external_values(
    value: object, *, role: str, role_spec: _RefRole
) -> list[dict[str, object]]:
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    if role_spec.kind == "pathless_file_ref":
        return [_file_ref(item, name=f"external {role}") for item in values]
    if role_spec.kind == "closed_case_ref":
        return [_case_ref(item, name=f"external {role}") for item in values]
    if role_spec.kind == "closed_logical_ref":
        return [_ledger_pre_result_ref(item, name=f"external {role}") for item in values]
    return [_ref(item, name=f"external {role}") for item in values]


def _decode_envelope(
    envelope: Mapping[str, object],
) -> tuple[bytes, dict[str, object], str | None, _ContractSpec | None]:
    if not isinstance(envelope, Mapping):
        raise ValueError("pathless envelope is invalid")
    _closed(envelope, ("ref", "canonical_bytes_b64"), name="pathless envelope")
    encoded = envelope.get("canonical_bytes_b64")
    if not isinstance(encoded, str):
        raise ValueError("pathless envelope canonical bytes are invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
        preview = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pathless envelope canonical bytes are invalid") from exc
    if not isinstance(preview, Mapping):
        raise ValueError("pathless envelope artifact is invalid")
    item = deepcopy(dict(preview))
    contract_version = item.get("contract_version")
    if isinstance(contract_version, str) and contract_version in _CONTRACTS:
        spec = _registered(contract_version)
        if _canonical_bytes(item) != raw:
            raise ValueError("pathless envelope bytes are not canonical")
        validated = validate_pathless_envelope(
            role=contract_version, envelope=envelope, context={}
        )
        return raw, validated, None, spec
    raw_class = _RAW_CONTRACTS.get(str(contract_version))
    if raw_class is None:
        raise ValueError("unknown pathless contract")
    decoded = _decode_raw_bytes(raw_class, raw)
    expected = _raw_ref(raw_class, raw, decoded)
    if _ref(envelope.get("ref"), name="pathless envelope ref") != expected:
        raise ValueError("pathless envelope ref mismatch")
    return raw, decoded, raw_class, None


def _attempt_first_open_order(
    envelopes: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    opened: list[tuple[int, dict[str, str]]] = []
    sequences: set[int] = set()
    for envelope in envelopes:
        _, item, raw_class, spec = _decode_envelope(envelope)
        if (
            raw_class is None
            and spec is not None
            and spec.contract_version
            == "benchmark_v2_runner_event_verified_projection_v1"
        ):
            sequence = _nonnegative(item["sequence"], name="runner event sequence")
            if sequence in sequences:
                raise ValueError("lifecycle closure runner event sequence is duplicated")
            sequences.add(sequence)
            if item["event_kind"] == "opened":
                opened.append(
                    (
                        sequence,
                        _ref(item["attempt_ref"], name="opened event attempt_ref"),
                    )
                )
    ordered = [attempt_ref for _, attempt_ref in sorted(opened, key=lambda pair: pair[0])]
    keys = [_canonical_bytes(attempt_ref) for attempt_ref in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("lifecycle closure attempt has duplicate opened event")
    return ordered


def order_pathless_envelopes(
    *, registry_name: str, envelopes: Sequence[Mapping[str, object]], context: Mapping[str, object]
) -> list[dict[str, object]]:
    """以注册表固定类别秩和语义键排序信封。"""

    if not isinstance(registry_name, str) or not registry_name:
        raise ValueError("pathless registry_name is invalid")
    decoded: list[
        tuple[_ContractSpec | None, str | None, dict[str, object], dict[str, object], bytes]
    ] = []
    seen: set[bytes] = set()
    for envelope in envelopes:
        raw, item, raw_class, spec = _decode_envelope(envelope)
        if spec is not None:
            allowed = spec.allowed_registry_names
            ref_value = pathless_artifact_ref(item)
        else:
            assert raw_class is not None
            allowed = _RAW_CLASSES[raw_class].allowed_registry_names
            ref_value = _raw_ref(raw_class, raw, item)
        if registry_name not in allowed:
            raise ValueError("pathless envelope class is not allowed in registry")
        ref_key = _canonical_bytes(ref_value)
        if ref_key in seen:
            raise ValueError("duplicate pathless envelope ref")
        seen.add(ref_key)
        decoded.append((spec, raw_class, item, deepcopy(dict(envelope)), raw))

    raw_items: dict[str, list[dict[str, object]]] = {}
    for _, raw_class, item, _, _ in decoded:
        if raw_class is not None:
            raw_items.setdefault(raw_class, []).append(item)
    validated_raw: dict[str, list[dict[str, object]]] = {}
    for raw_class in (
        "omni_inventory",
        "qwen_bindings",
        "fusion_result",
        "submitted_vista_request",
        "automatic_prediction",
    ):
        for item in raw_items.get(raw_class, []):
            validated_raw.setdefault(raw_class, []).append(
                _validate_raw_class_value(
                    raw_class, item, validated_by_class=validated_raw
                )
            )

    attempt_order: dict[bytes, int] = {}
    if registry_name == "lifecycle_bundle_v3":
        derived_order = _attempt_first_open_order(envelopes)
        declared_order = context.get("attempt_first_open_order")
        if declared_order is not None:
            if not isinstance(declared_order, list):
                raise ValueError("attempt_first_open_order context is invalid")
            validated_declared = _ref_list(
                declared_order, name="attempt_first_open_order"
            )
            if validated_declared != derived_order:
                raise ValueError("attempt_first_open_order context mismatch")
        attempt_order = {
            _canonical_bytes(attempt_ref): index
            for index, attempt_ref in enumerate(derived_order)
        }
        cleanup_attempts: set[bytes] = set()
        for spec, _, item, _, _ in decoded:
            if (
                spec is not None
                and spec.contract_version
                == "benchmark_v2_lifecycle_verified_projection_v1"
                and item["lifecycle_kind"] == "cleanup"
            ):
                attempt_key = _canonical_bytes(
                    _ref(item["attempt_ref"], name="cleanup lifecycle attempt_ref")
                )
                if attempt_key not in attempt_order:
                    raise ValueError("cleanup lifecycle attempt has no opened runner event")
                if attempt_key in cleanup_attempts:
                    raise ValueError("duplicate cleanup lifecycle attempt")
                cleanup_attempts.add(attempt_key)

    def key(
        entry: tuple[_ContractSpec | None, str | None, dict[str, object], dict[str, object], bytes]
    ) -> tuple[object, ...]:
        spec, raw_class, item, envelope, raw = entry
        if spec is None:
            assert raw_class is not None
            rank = _RAW_CLASSES[raw_class].class_ranks.get(registry_name)
            if rank is None:
                raise ValueError("pathless envelope class has no registered rank")
            ref_value = _raw_ref(raw_class, raw, item)
            return (rank, ref_value["id"], ref_value["content_sha256"])
        rank = spec.class_ranks.get(registry_name)
        if rank is None:
            raise ValueError("pathless envelope class has no registered rank")
        if spec.contract_version == "benchmark_v2_lifecycle_verified_projection_v1" and registry_name == "lifecycle_bundle_v3":
            rank = {"screen_group": 1, "cleanup": 2, "attempt": 4}[str(item["lifecycle_kind"])]
            if item["lifecycle_kind"] == "cleanup":
                attempt_key = _canonical_bytes(
                    _ref(item["attempt_ref"], name="cleanup lifecycle attempt_ref")
                )
                return (rank, attempt_order[attempt_key])
        return (rank, *spec.semantic_sort_key(item, registry_name))

    return [envelope for _, _, _, envelope, _ in sorted(decoded, key=key)]


def validate_pathless_recursive(
    *,
    registry_name: str,
    roots: Sequence[Mapping[str, object]],
    envelopes: Sequence[Mapping[str, object]],
    external_refs: Mapping[str, object],
    context: Mapping[str, object],
) -> list[dict[str, object]]:
    """验证闭合可达图，拒绝循环、孤儿、重复与内外角色漂移。"""

    ordered = order_pathless_envelopes(
        registry_name=registry_name,
        envelopes=envelopes,
        context=context,
    )
    by_ref: dict[bytes, tuple[dict[str, object], dict[str, object]]] = {}
    for envelope in ordered:
        _, item, _, _ = _decode_envelope(envelope)
        ref_value = _ref(envelope["ref"], name="pathless envelope ref")
        by_ref[_canonical_bytes(ref_value)] = (item, envelope)
    root_refs = [_ref(root, name=f"root[{index}]") for index, root in enumerate(roots)]
    if not root_refs:
        raise ValueError("pathless graph roots are empty")
    external = dict(external_refs)
    consumed_external: set[str] = set()
    for key in external:
        if not isinstance(key, str) or "." not in key:
            raise ValueError("external ref role must be contract-qualified")
    visiting: set[bytes] = set()
    visited: set[bytes] = set()

    def visit(ref_value: dict[str, str]) -> None:
        key = _canonical_bytes(ref_value)
        if key in visiting:
            raise ValueError("pathless graph contains a cycle")
        if key in visited:
            return
        if key not in by_ref:
            raise ValueError("pathless graph root or child is missing")
        visiting.add(key)
        item, _ = by_ref[key]
        spec = _registered(item["contract_version"])
        for role, role_spec, child_ref in _edges(item):
            qualified = f"{spec.contract_version}.{role}"
            child_key = _canonical_bytes(child_ref)
            if role_spec.external:
                if role_spec.kind in {"exact_ref", "opaque_raw_ref"} and child_key in by_ref:
                    raise ValueError("external ref was injected as an internal envelope")
                if qualified not in external:
                    raise ValueError(f"external ref role is missing: {qualified}")
                accepted = _external_values(
                    external[qualified], role=qualified, role_spec=role_spec
                )
                if child_ref not in accepted:
                    raise ValueError(f"external ref role mismatch: {qualified}")
                consumed_external.add(qualified)
            else:
                if qualified in external:
                    raise ValueError("internal ref was presented as external")
                visit(child_ref)
        visiting.remove(key)
        visited.add(key)

    for root in root_refs:
        visit(root)
    for key in visited:
        item = by_ref[key][0]
        if item.get("contract_version") == "benchmark_v2_projected_attempt_ledger_v1":
            _validate_projected_ledger_graph(item, by_ref)
    if visited != set(by_ref):
        raise ValueError("pathless graph contains an orphan envelope")
    extras = set(external) - consumed_external
    if extras:
        internal = any(
            key.split(".", 1)[0] in _CONTRACTS
            and key.split(".", 1)[1] in _CONTRACTS[key.split(".", 1)[0]].ref_role_schema
            and not _CONTRACTS[key.split(".", 1)[0]].ref_role_schema[key.split(".", 1)[1]].external
            for key in extras
        )
        if internal:
            raise ValueError("internal ref was presented as external")
        raise ValueError("unused external ref role")
    return ordered


__all__ = [
    "seal_pathless_projection",
    "pathless_artifact_ref",
    "seal_pathless_envelope",
    "validate_pathless_ref",
    "validate_pathless_envelope",
    "validate_pathless_recursive",
    "order_pathless_envelopes",
]
