"""Benchmark-v2 incumbent的closed documents与纯重放核心。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, content_sha256
from app.learn.hybrid.benchmark_v2_provider_corpus import (
    provider_case_resolver_corpus_file_ref,
)
from app.operation.observe.contracts import ObserveScreenTaskInput


BENCHMARK_V2_INCUMBENT_OPERATION_CONTRACT = "benchmark_v2_incumbent_operation_v1"
BENCHMARK_V2_INCUMBENT_MODE = "benchmark_v2_incumbent_single_observe"
BENCHMARK_V2_INCUMBENT_SOURCE_CONTRACT = (
    "benchmark_v2_incumbent_handler_payload_source_v1"
)
BENCHMARK_V2_INCUMBENT_SOURCE_REF_CONTRACT = (
    "benchmark_v2_incumbent_handler_payload_source_ref_v1"
)
BENCHMARK_V2_INCUMBENT_PROJECTION_CONTRACT = (
    "benchmark_v2_observe_screen_payload_projection_v1"
)
BENCHMARK_V2_INCUMBENT_TERMINAL_INTENT_CONTRACT = (
    "benchmark_v2_incumbent_terminal_intent_v1"
)
BENCHMARK_V2_INCUMBENT_CANCEL_INTENT_CONTRACT = (
    "benchmark_v2_incumbent_cancel_intent_v1"
)
BENCHMARK_V2_INCUMBENT_TERMINAL_RECEIPT_CONTRACT = (
    "benchmark_v2_incumbent_terminal_receipt_v1"
)

BENCHMARK_V2_INCUMBENT_PAYLOAD_PROJECTION_RULES = {
    "task": {"literal": "observe_screen"},
    "app_name": {"provider_case_field": "layout.title"},
    "state_hint": {"provider_case_field": "goal"},
    "provider_mode": {"literal": "local_understanding"},
    "agent_mode": {"literal": "learn"},
    "learn_depth": {"literal": "fast"},
    "write_policy": {
        "literal": {
            "path_graph": True,
            "element_memory": False,
            "trace": True,
        }
    },
    "metadata": {"source": "validated_provider_case_v2"},
    "operation_context": {"source": "server_owned_benchmark_v2"},
    "capture_live": {"literal": False},
    "image_path": {"source": "task5_sealed_capture"},
    "_benchmark_v2_window_binding": {"source": "task5_literal_projection"},
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NONTERMINAL_PHASES = frozenset(
    {
        "prepared",
        "provider_owner_prepared",
        "worker_starting",
        "worker_bound",
        "result_ready",
        "terminal_intent",
        "adopted",
        "cancel_intent",
        "cleanup_pending",
    }
)
_TERMINAL_PHASES = frozenset({"complete", "cancelled", "safe_stopped"})
_PHASES = _NONTERMINAL_PHASES | _TERMINAL_PHASES
_LEGAL_TRANSITIONS = {
    "prepared": {"provider_owner_prepared", "cancel_intent", "safe_stopped"},
    "provider_owner_prepared": {"worker_starting", "cancel_intent", "safe_stopped"},
    "worker_starting": {"worker_bound", "cancel_intent", "safe_stopped"},
    "worker_bound": {"result_ready", "cancel_intent", "safe_stopped"},
    "result_ready": {"terminal_intent", "cancel_intent", "safe_stopped"},
    "terminal_intent": {"adopted", "safe_stopped"},
    "adopted": {"complete", "safe_stopped"},
    "cancel_intent": {"cleanup_pending", "cancelled", "safe_stopped"},
    "cleanup_pending": {"cleanup_pending", "cancelled", "safe_stopped"},
}
_OPERATION_FIELDS = {
    "contract_version",
    "mode",
    "run_id",
    "stage",
    "operation_id",
    "operation_anchor_ref",
    "reservation_ref",
    "supervision_inputs_ref",
    "expected_supervision_ref",
    "acquisition_intent_ref",
    "runtime_owner_ref",
    "prepared_revision",
    "current_document_revision",
    "task_kind",
    "handler_payload_source",
    "handler_payload_source_ref",
    "handler_payload_sha256",
    "window_binding_ref",
    "capture_ref",
    "execution_nonce",
    "phase",
    "worker_ref",
    "result_identity_ref",
    "window_adoption_ref",
    "worker_cleanup_ref",
    "provider_cleanup_ref",
    "terminal_intent",
    "cancel_intent",
    "generic_adoption_ref",
    "terminal_receipt",
    "predecessor_content_sha256",
    "content_sha256",
}
_MUTABLE_FIELDS = {
    "acquisition_intent_ref",
    "runtime_owner_ref",
    "worker_ref",
    "result_identity_ref",
    "window_adoption_ref",
    "worker_cleanup_ref",
    "provider_cleanup_ref",
    "terminal_intent",
    "cancel_intent",
    "generic_adoption_ref",
    "terminal_receipt",
}
_TERMINAL_INTENT_FIELDS = {
    "contract_version",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "model_request_id",
    "payload_sha256",
    "result_sha256",
    "normal_binding_evidence_ref",
    "provider_cleanup_evidence_ref",
    "worker_cleanup_evidence_ref",
    "intent_revision",
    "intent_at",
    "predecessor_content_sha256",
    "content_sha256",
}
_CANCEL_INTENT_FIELDS = {
    "contract_version",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "model_request_id",
    "payload_sha256",
    "execution_nonce",
    "reservation_ref",
    "operation_anchor_ref",
    "acquisition_intent_ref",
    "runtime_owner_ref",
    "process_identity",
    "scope_name",
    "assignment_proven_ref",
    "reason",
    "intent_revision",
    "intent_at",
    "predecessor_content_sha256",
    "content_sha256",
}
_TERMINAL_RECEIPT_FIELDS = {
    "contract_version",
    "outcome",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "model_request_id",
    "payload_sha256",
    "result_sha256",
    "terminal_intent_ref",
    "cancel_intent_ref",
    "generic_adoption_ref",
    "window_adoption_ref",
    "worker_cleanup_ref",
    "provider_cleanup_ref",
    "provider_cleanup_outcome",
    "terminal_at",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "predecessor_content_sha256",
    "content_sha256",
}


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} schema is not closed")
    return deepcopy(dict(value))


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _revision(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _content_ref(value: object, name: str) -> dict[str, str]:
    ref = _closed(value, {"content_sha256"}, name)
    _sha(ref["content_sha256"], f"{name}.content_sha256")
    return ref


def _identity_ref(value: object, name: str) -> dict[str, str]:
    ref = _closed(value, {"id", "content_sha256"}, name)
    _text(ref["id"], f"{name}.id")
    _sha(ref["content_sha256"], f"{name}.content_sha256")
    return ref


def _sealed_parent(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a sealed mapping")
    result = deepcopy(dict(value))
    digest = result.get("content_sha256")
    _sha(digest, f"{name}.content_sha256")
    if len(result) > 1 and content_sha256(result) != digest:
        raise ValueError(f"{name} content SHA mismatch")
    return result


def _seal(body: Mapping[str, object]) -> dict[str, Any]:
    result = deepcopy(dict(body))
    result["content_sha256"] = content_sha256(result)
    return result


def _payload_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _validate_source_ref(value: object) -> dict[str, str]:
    ref = _closed(
        value,
        {"contract_version", "content_sha256"},
        "benchmark source ref",
    )
    if ref["contract_version"] != BENCHMARK_V2_INCUMBENT_SOURCE_REF_CONTRACT:
        raise ValueError("benchmark source ref contract is invalid")
    _sha(ref["content_sha256"], "benchmark source ref content SHA")
    return ref


def _validate_corpus_file_ref(value: object) -> dict[str, Any]:
    ref = _closed(
        value,
        {
            "contract_version",
            "relative_path",
            "file_sha256",
            "source_parent_ref",
            "content_sha256",
        },
        "benchmark provider corpus file ref",
    )
    if (
        ref["contract_version"] != "benchmark_v2_provider_corpus_file_ref_v1"
        or ref["relative_path"] != "provider-corpus.v2.json"
    ):
        raise ValueError("benchmark provider corpus file ref identity is invalid")
    _sha(ref["file_sha256"], "benchmark provider corpus file SHA")
    ref["source_parent_ref"] = _content_ref(
        ref["source_parent_ref"], "benchmark provider corpus parent ref"
    )
    _sha(ref["content_sha256"], "benchmark provider corpus file ref SHA")
    if ref["content_sha256"] != content_sha256(ref):
        raise ValueError("benchmark provider corpus file ref SHA mismatch")
    return ref


def validate_benchmark_v2_incumbent_handler_payload_source(
    value: object,
) -> dict[str, Any]:
    source = _closed(
        value,
        {
            "contract_version",
            "provider_corpus_file_ref",
            "provider_case_ref",
            "projection_contract_version",
            "projection_rules_content_sha256",
            "window_binding_ref",
            "capture_ref",
            "handler_payload_sha256",
            "predecessor_content_sha256",
            "content_sha256",
        },
        "benchmark handler payload source",
    )
    if source["contract_version"] != BENCHMARK_V2_INCUMBENT_SOURCE_CONTRACT:
        raise ValueError("benchmark handler payload source contract is invalid")
    corpus_ref = _validate_corpus_file_ref(source["provider_corpus_file_ref"])
    case_ref = _closed(
        source["provider_case_ref"],
        {"case_id", "case_content_sha256"},
        "benchmark provider case ref",
    )
    _text(case_ref["case_id"], "benchmark provider case id")
    _sha(case_ref["case_content_sha256"], "benchmark provider case SHA")
    if source["projection_contract_version"] != BENCHMARK_V2_INCUMBENT_PROJECTION_CONTRACT:
        raise ValueError("benchmark payload projection contract is invalid")
    if source["projection_rules_content_sha256"] != content_sha256(
        BENCHMARK_V2_INCUMBENT_PAYLOAD_PROJECTION_RULES
    ):
        raise ValueError("benchmark payload projection rules SHA is invalid")
    source["window_binding_ref"] = _identity_ref(
        source["window_binding_ref"], "benchmark window binding ref"
    )
    source["capture_ref"] = _identity_ref(
        source["capture_ref"], "benchmark capture ref"
    )
    _sha(source["handler_payload_sha256"], "benchmark handler payload SHA")
    if source["predecessor_content_sha256"] != corpus_ref["content_sha256"]:
        raise ValueError("benchmark handler payload source predecessor is invalid")
    _sha(source["content_sha256"], "benchmark handler payload source SHA")
    if source["content_sha256"] != content_sha256(source):
        raise ValueError("benchmark handler payload source SHA mismatch")
    source["provider_corpus_file_ref"] = corpus_ref
    source["provider_case_ref"] = case_ref
    return source


def _compose_payload(
    *,
    case: Mapping[str, object],
    corpus_file_ref: Mapping[str, object],
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    serialized_window_binding: Mapping[str, object],
) -> dict[str, Any]:
    image = case.get("image")
    layout = case.get("layout")
    if not isinstance(image, Mapping) or not isinstance(layout, Mapping):
        raise ValueError("provider case image/layout is invalid")
    binding = deepcopy(dict(serialized_window_binding))
    image_path = Path(_text(binding.get("capture_image_path"), "capture image path"))
    if not image_path.is_absolute() or str(image_path) != str(image_path.resolve()):
        raise ValueError("capture image path must be canonical and absolute")
    if not image_path.is_file():
        raise ValueError("capture image path is unavailable")
    image_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if (
        image_sha256 != image.get("sha256")
        or image_sha256 != capture_ref["content_sha256"]
        or image_sha256 != binding.get("capture_sha256")
        or binding.get("screenshot_sha256") != image_sha256
        or binding.get("image_dimensions") != {
            "width": image.get("width"),
            "height": image.get("height"),
        }
    ):
        raise ValueError("capture identity differs from validated provider case")
    if window_binding_ref["content_sha256"] != binding.get("payload_sha256"):
        raise ValueError("window binding ref differs from Task5 projection")
    case_sha256 = content_sha256(dict(case))
    context = {
        "contract_version": "operation_runtime_context_v1",
        "authorized_intent_id": None,
        "semantic_action": "observe_screen",
        "skill_id": None,
        "gate_decision_id": None,
        "gate_policy_version": None,
        "allowed_action_scope": None,
        "capture_id": capture_ref["content_sha256"],
        "window_binding_id": window_binding_ref["content_sha256"],
        "viewport_size": {
            "width": image["width"],
            "height": image["height"],
        },
        "evidence_refs": [
            corpus_file_ref["content_sha256"],
            case_sha256,
            window_binding_ref["content_sha256"],
            capture_ref["content_sha256"],
        ],
        "source": "benchmark_v2_provider_safe",
        "synthesized_fields": [],
    }
    task = ObserveScreenTaskInput.model_validate(
        {
            "task": "observe_screen",
            "app_name": layout.get("title"),
            "state_hint": case.get("goal"),
            "provider_mode": "local_understanding",
            "agent_mode": "learn",
            "learn_depth": "fast",
            "write_policy": {
                "path_graph": True,
                "element_memory": False,
                "trace": True,
            },
            "metadata": {
                "benchmark_release_id": "portfolio_hybrid_v1_1_benchmark_v2_release_1",
                "case_id": case.get("case_id"),
                "screen_group": case.get("screen_group"),
                "partition": case.get("partition"),
                "source_kind": "privacy_safe_synthetic",
            },
            "operation_context": context,
            "capture_live": False,
            "image_path": str(image_path),
        }
    )
    payload = task.model_dump(mode="json")
    payload["_benchmark_v2_window_binding"] = binding
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        validate_spawned_worker_observation_payload,
    )

    validate_spawned_worker_observation_payload(payload=payload, serialized=binding)
    return payload


def compose_benchmark_v2_incumbent_payload_projection(
    *,
    provider_case_resolver: object,
    provider_case_ref: Mapping[str, object],
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    serialized_window_binding: Mapping[str, object],
) -> dict[str, Any]:
    if not hasattr(provider_case_resolver, "resolve"):
        raise ValueError("provider case resolver is invalid")
    case = provider_case_resolver.resolve(provider_case_ref)
    corpus_file_ref = provider_case_resolver_corpus_file_ref(provider_case_resolver)
    binding_ref = _identity_ref(window_binding_ref, "benchmark window binding ref")
    capture = _identity_ref(capture_ref, "benchmark capture ref")
    payload = _compose_payload(
        case=case,
        corpus_file_ref=corpus_file_ref,
        window_binding_ref=binding_ref,
        capture_ref=capture,
        serialized_window_binding=serialized_window_binding,
    )
    source = _seal(
        {
            "contract_version": BENCHMARK_V2_INCUMBENT_SOURCE_CONTRACT,
            "provider_corpus_file_ref": corpus_file_ref,
            "provider_case_ref": deepcopy(dict(provider_case_ref)),
            "projection_contract_version": BENCHMARK_V2_INCUMBENT_PROJECTION_CONTRACT,
            "projection_rules_content_sha256": content_sha256(
                BENCHMARK_V2_INCUMBENT_PAYLOAD_PROJECTION_RULES
            ),
            "window_binding_ref": binding_ref,
            "capture_ref": capture,
            "handler_payload_sha256": _payload_sha256(payload),
            "predecessor_content_sha256": corpus_file_ref["content_sha256"],
        }
    )
    source = validate_benchmark_v2_incumbent_handler_payload_source(source)
    return {
        "handler_payload_source": source,
        "handler_payload_source_ref": {
            "contract_version": BENCHMARK_V2_INCUMBENT_SOURCE_REF_CONTRACT,
            "content_sha256": source["content_sha256"],
        },
        "authoritative_payload": payload,
    }


def validate_benchmark_v2_incumbent_payload_projection(
    *,
    payload: Mapping[str, object],
    handler_payload_source: Mapping[str, object],
    provider_case_resolver: object,
    serialized_window_binding: Mapping[str, object],
) -> dict[str, Any]:
    source = validate_benchmark_v2_incumbent_handler_payload_source(
        handler_payload_source
    )
    case = provider_case_resolver.resolve(source["provider_case_ref"])
    expected = _compose_payload(
        case=case,
        corpus_file_ref=source["provider_corpus_file_ref"],
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"],
        serialized_window_binding=serialized_window_binding,
    )
    if deepcopy(dict(payload)) != expected or _payload_sha256(expected) != source[
        "handler_payload_sha256"
    ]:
        raise ValueError("benchmark payload projection does not match source")
    return expected


def _validate_worker_ref(value: object) -> dict[str, Any]:
    worker = _closed(
        value,
        {
            "worker_id",
            "model_request_id",
            "payload_sha256",
            "execution_nonce",
            "reservation_ref",
            "supervision_ref",
        },
        "benchmark worker ref",
    )
    _text(worker["worker_id"], "benchmark worker id")
    _text(worker["model_request_id"], "benchmark model request id")
    _sha(worker["payload_sha256"], "benchmark worker payload SHA")
    if not isinstance(worker["execution_nonce"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", worker["execution_nonce"]
    ):
        raise ValueError("benchmark worker execution nonce is invalid")
    worker["reservation_ref"] = _content_ref(
        worker["reservation_ref"], "benchmark worker reservation ref"
    )
    if worker["supervision_ref"] is not None:
        worker["supervision_ref"] = _content_ref(
            worker["supervision_ref"], "benchmark worker supervision ref"
        )
    return worker


def compose_benchmark_v2_incumbent_operation(
    *,
    run_id: str,
    stage: str,
    operation_id: str,
    operation_anchor_ref: Mapping[str, object],
    reservation_ref: Mapping[str, object],
    supervision_inputs_ref: Mapping[str, object],
    expected_supervision_ref: Mapping[str, object],
    prepared_revision: int,
    handler_payload_source: Mapping[str, object],
    handler_payload_source_ref: Mapping[str, object],
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    execution_nonce: str,
    worker_ref: Mapping[str, object],
) -> dict[str, Any]:
    source = validate_benchmark_v2_incumbent_handler_payload_source(
        handler_payload_source
    )
    body = {
        "contract_version": BENCHMARK_V2_INCUMBENT_OPERATION_CONTRACT,
        "mode": BENCHMARK_V2_INCUMBENT_MODE,
        "run_id": run_id,
        "stage": stage,
        "operation_id": operation_id,
        "operation_anchor_ref": deepcopy(dict(operation_anchor_ref)),
        "reservation_ref": deepcopy(dict(reservation_ref)),
        "supervision_inputs_ref": deepcopy(dict(supervision_inputs_ref)),
        "expected_supervision_ref": deepcopy(dict(expected_supervision_ref)),
        "acquisition_intent_ref": None,
        "runtime_owner_ref": None,
        "prepared_revision": prepared_revision,
        "current_document_revision": prepared_revision,
        "task_kind": "vision_observe_screen",
        "handler_payload_source": source,
        "handler_payload_source_ref": deepcopy(dict(handler_payload_source_ref)),
        "handler_payload_sha256": source["handler_payload_sha256"],
        "window_binding_ref": deepcopy(dict(window_binding_ref)),
        "capture_ref": deepcopy(dict(capture_ref)),
        "execution_nonce": execution_nonce,
        "phase": "prepared",
        "worker_ref": deepcopy(dict(worker_ref)),
        "result_identity_ref": None,
        "window_adoption_ref": None,
        "worker_cleanup_ref": None,
        "provider_cleanup_ref": None,
        "terminal_intent": None,
        "cancel_intent": None,
        "generic_adoption_ref": None,
        "terminal_receipt": None,
        "predecessor_content_sha256": None,
    }
    return validate_benchmark_v2_incumbent_operation(_seal(body))


def validate_benchmark_v2_incumbent_terminal_intent(value: object) -> dict[str, Any]:
    intent = _closed(value, _TERMINAL_INTENT_FIELDS, "benchmark terminal intent")
    if intent["contract_version"] != BENCHMARK_V2_INCUMBENT_TERMINAL_INTENT_CONTRACT:
        raise ValueError("benchmark terminal intent contract is invalid")
    for name in ("run_id", "stage", "operation_id", "worker_id", "model_request_id", "intent_at"):
        _text(intent[name], f"benchmark terminal intent {name}")
    for name in ("payload_sha256", "result_sha256", "predecessor_content_sha256", "content_sha256"):
        _sha(intent[name], f"benchmark terminal intent {name}")
    for name in (
        "normal_binding_evidence_ref",
        "provider_cleanup_evidence_ref",
        "worker_cleanup_evidence_ref",
    ):
        intent[name] = _sealed_parent(intent[name], f"benchmark terminal intent {name}")
    _revision(intent["intent_revision"], "benchmark terminal intent revision")
    if intent["content_sha256"] != content_sha256(intent):
        raise ValueError("benchmark terminal intent content SHA mismatch")
    return intent


def validate_benchmark_v2_incumbent_cancel_intent(value: object) -> dict[str, Any]:
    intent = _closed(value, _CANCEL_INTENT_FIELDS, "benchmark cancel intent")
    if intent["contract_version"] != BENCHMARK_V2_INCUMBENT_CANCEL_INTENT_CONTRACT:
        raise ValueError("benchmark cancel intent contract is invalid")
    for name in (
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "reason",
        "intent_at",
    ):
        _text(intent[name], f"benchmark cancel intent {name}")
    for name in ("payload_sha256", "predecessor_content_sha256", "content_sha256"):
        _sha(intent[name], f"benchmark cancel intent {name}")
    if not isinstance(intent["execution_nonce"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", intent["execution_nonce"]
    ):
        raise ValueError("benchmark cancel intent execution nonce is invalid")
    for name in ("reservation_ref", "operation_anchor_ref"):
        intent[name] = _content_ref(intent[name], f"benchmark cancel intent {name}")
    for name in ("acquisition_intent_ref", "runtime_owner_ref"):
        if intent[name] is not None:
            intent[name] = _sealed_parent(intent[name], f"benchmark cancel intent {name}")
    if intent["process_identity"] is not None:
        process = _closed(
            intent["process_identity"],
            {"pid", "create_time_ns"},
            "benchmark cancel process identity",
        )
        if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in process.values()):
            raise ValueError("benchmark cancel process identity is invalid")
        intent["process_identity"] = process
    if intent["scope_name"] is not None:
        _text(intent["scope_name"], "benchmark cancel scope name")
    if intent["assignment_proven_ref"] is not None:
        intent["assignment_proven_ref"] = _sealed_parent(
            intent["assignment_proven_ref"],
            "benchmark cancel assignment ref",
        )
    if (intent["process_identity"] is None) != (intent["scope_name"] is None) or (
        intent["process_identity"] is None
    ) != (intent["assignment_proven_ref"] is None):
        raise ValueError("benchmark cancel process fields must be all null or all present")
    _revision(intent["intent_revision"], "benchmark cancel intent revision")
    if intent["content_sha256"] != content_sha256(intent):
        raise ValueError("benchmark cancel intent content SHA mismatch")
    return intent


def validate_benchmark_v2_incumbent_terminal_receipt(value: object) -> dict[str, Any]:
    receipt = _closed(value, _TERMINAL_RECEIPT_FIELDS, "benchmark terminal receipt")
    if receipt["contract_version"] != BENCHMARK_V2_INCUMBENT_TERMINAL_RECEIPT_CONTRACT:
        raise ValueError("benchmark terminal receipt contract is invalid")
    if receipt["outcome"] not in {
        "benchmark_v2_incumbent_observe_complete",
        "benchmark_v2_incumbent_cancelled",
    }:
        raise ValueError("benchmark terminal receipt outcome is invalid")
    for name in ("run_id", "stage", "operation_id", "worker_id", "model_request_id", "terminal_at"):
        _text(receipt[name], f"benchmark terminal receipt {name}")
    for name in ("payload_sha256", "predecessor_content_sha256", "content_sha256"):
        _sha(receipt[name], f"benchmark terminal receipt {name}")
    if receipt["result_sha256"] is not None:
        _sha(receipt["result_sha256"], "benchmark terminal receipt result SHA")
    for name in (
        "terminal_intent_ref",
        "cancel_intent_ref",
        "generic_adoption_ref",
        "window_adoption_ref",
        "worker_cleanup_ref",
        "provider_cleanup_ref",
    ):
        if receipt[name] is not None:
            receipt[name] = _sealed_parent(receipt[name], f"benchmark terminal receipt {name}")
    if receipt["artifact_is_authorization"] is not False or receipt["execute_binding_enabled"] is not False:
        raise ValueError("benchmark terminal receipt cannot authorize actions")
    if receipt["outcome"] == "benchmark_v2_incumbent_observe_complete":
        required = (
            "result_sha256",
            "terminal_intent_ref",
            "generic_adoption_ref",
            "window_adoption_ref",
            "worker_cleanup_ref",
            "provider_cleanup_ref",
        )
        if any(receipt[name] is None for name in required) or receipt["cancel_intent_ref"] is not None:
            raise ValueError("benchmark complete receipt parents are invalid")
        if receipt["provider_cleanup_outcome"] != "verified_exact_process_exited":
            raise ValueError("benchmark complete provider cleanup outcome is invalid")
    else:
        required = ("cancel_intent_ref", "worker_cleanup_ref", "provider_cleanup_ref")
        if any(receipt[name] is None for name in required) or any(
            receipt[name] is not None
            for name in (
                "result_sha256",
                "terminal_intent_ref",
                "generic_adoption_ref",
                "window_adoption_ref",
            )
        ):
            raise ValueError("benchmark cancelled receipt parents are invalid")
        if receipt["provider_cleanup_outcome"] not in {
            "verified_not_acquired",
            "verified_exact_process_exited",
        }:
            raise ValueError("benchmark cancelled provider cleanup outcome is invalid")
    if receipt["content_sha256"] != content_sha256(receipt):
        raise ValueError("benchmark terminal receipt content SHA mismatch")
    return receipt


def validate_benchmark_v2_incumbent_operation(value: object) -> dict[str, Any]:
    operation = _closed(value, _OPERATION_FIELDS, "benchmark incumbent operation")
    if operation["contract_version"] != BENCHMARK_V2_INCUMBENT_OPERATION_CONTRACT:
        raise ValueError("benchmark incumbent operation contract is invalid")
    if operation["mode"] != BENCHMARK_V2_INCUMBENT_MODE:
        raise ValueError("benchmark incumbent operation mode is invalid")
    for name in ("run_id", "stage", "operation_id"):
        _text(operation[name], f"benchmark incumbent operation {name}")
    for name in (
        "operation_anchor_ref",
        "reservation_ref",
        "supervision_inputs_ref",
        "expected_supervision_ref",
    ):
        operation[name] = _content_ref(operation[name], f"benchmark operation {name}")
    if (operation["acquisition_intent_ref"] is None) != (operation["runtime_owner_ref"] is None):
        raise ValueError("benchmark provider owner refs must be both null or both present")
    for name in ("acquisition_intent_ref", "runtime_owner_ref"):
        if operation[name] is not None:
            operation[name] = _sealed_parent(operation[name], f"benchmark operation {name}")
    prepared_revision = _revision(operation["prepared_revision"], "benchmark prepared revision")
    current_revision = _revision(
        operation["current_document_revision"], "benchmark current document revision"
    )
    if current_revision < prepared_revision:
        raise ValueError("benchmark operation revision moved backwards")
    if operation["task_kind"] != "vision_observe_screen":
        raise ValueError("benchmark incumbent task kind is invalid")
    source = validate_benchmark_v2_incumbent_handler_payload_source(
        operation["handler_payload_source"]
    )
    source_ref = _validate_source_ref(operation["handler_payload_source_ref"])
    if source_ref["content_sha256"] != source["content_sha256"]:
        raise ValueError("benchmark source ref differs from source")
    if operation["handler_payload_sha256"] != source["handler_payload_sha256"]:
        raise ValueError("benchmark operation payload SHA differs from source")
    operation["window_binding_ref"] = _identity_ref(
        operation["window_binding_ref"], "benchmark operation window binding ref"
    )
    operation["capture_ref"] = _identity_ref(
        operation["capture_ref"], "benchmark operation capture ref"
    )
    if operation["window_binding_ref"] != source["window_binding_ref"] or operation[
        "capture_ref"
    ] != source["capture_ref"]:
        raise ValueError("benchmark operation Task5 refs differ from source")
    if not isinstance(operation["execution_nonce"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", operation["execution_nonce"]
    ):
        raise ValueError("benchmark operation execution nonce is invalid")
    phase = operation["phase"]
    if phase not in _PHASES:
        raise ValueError("benchmark operation phase is invalid")
    worker = _validate_worker_ref(operation["worker_ref"])
    if (
        worker["payload_sha256"] != operation["handler_payload_sha256"]
        or worker["execution_nonce"] != operation["execution_nonce"]
        or worker["reservation_ref"] != operation["reservation_ref"]
    ):
        raise ValueError("benchmark worker ref differs from operation")
    if phase in {"worker_bound", "result_ready", "terminal_intent", "adopted", "complete"} and worker[
        "supervision_ref"
    ] is None:
        raise ValueError("benchmark bound operation requires supervision ref")
    if phase == "prepared" and (
        operation["acquisition_intent_ref"] is not None
        or operation["runtime_owner_ref"] is not None
    ):
        raise ValueError("benchmark prepared operation cannot have provider owner refs")
    if phase in {
        "provider_owner_prepared",
        "worker_starting",
        "worker_bound",
        "result_ready",
        "terminal_intent",
        "adopted",
        "complete",
    } and operation["acquisition_intent_ref"] is None:
        raise ValueError("benchmark operation requires provider owner refs")
    if operation["result_identity_ref"] is not None:
        operation["result_identity_ref"] = _sealed_parent(
            operation["result_identity_ref"], "benchmark result identity ref"
        )
    for name in (
        "window_adoption_ref",
        "worker_cleanup_ref",
        "provider_cleanup_ref",
        "generic_adoption_ref",
    ):
        if operation[name] is not None:
            operation[name] = _sealed_parent(operation[name], f"benchmark operation {name}")
    if operation["terminal_intent"] is not None:
        operation["terminal_intent"] = validate_benchmark_v2_incumbent_terminal_intent(
            operation["terminal_intent"]
        )
        intent = operation["terminal_intent"]
        if any(
            intent[name] != operation[name]
            for name in ("run_id", "stage", "operation_id")
        ) or any(
            intent[name] != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        ):
            raise ValueError("benchmark terminal intent identity differs from operation")
        if intent["intent_revision"] > current_revision:
            raise ValueError("benchmark terminal intent revision is from the future")
        if phase == "terminal_intent" and (
            intent["intent_revision"] != current_revision
            or intent["predecessor_content_sha256"]
            != operation["predecessor_content_sha256"]
        ):
            raise ValueError("benchmark terminal intent predecessor differs")
    if operation["cancel_intent"] is not None:
        operation["cancel_intent"] = validate_benchmark_v2_incumbent_cancel_intent(
            operation["cancel_intent"]
        )
        intent = operation["cancel_intent"]
        if any(
            intent[name] != operation[name]
            for name in ("run_id", "stage", "operation_id", "execution_nonce")
        ) or any(
            intent[name] != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        ):
            raise ValueError("benchmark cancel intent identity differs from operation")
        if (
            intent["reservation_ref"] != operation["reservation_ref"]
            or intent["operation_anchor_ref"] != operation["operation_anchor_ref"]
            or intent["acquisition_intent_ref"]
            != operation["acquisition_intent_ref"]
            or intent["runtime_owner_ref"] != operation["runtime_owner_ref"]
            or intent["intent_revision"] > current_revision
        ):
            raise ValueError("benchmark cancel intent parents differ from operation")
        if phase == "cancel_intent" and (
            intent["intent_revision"] != current_revision
            or intent["predecessor_content_sha256"]
            != operation["predecessor_content_sha256"]
        ):
            raise ValueError("benchmark cancel intent predecessor differs")
    if operation["terminal_intent"] is not None and operation["cancel_intent"] is not None:
        raise ValueError("benchmark terminal_intent xor cancel_intent invariant failed")
    if phase in {"terminal_intent", "adopted", "complete"} and operation["terminal_intent"] is None:
        raise ValueError("benchmark complete path requires terminal intent")
    if phase in {"cancel_intent", "cleanup_pending", "cancelled"} and operation["cancel_intent"] is None:
        raise ValueError("benchmark cancel path requires cancel intent")
    if operation["terminal_receipt"] is not None:
        operation["terminal_receipt"] = validate_benchmark_v2_incumbent_terminal_receipt(
            operation["terminal_receipt"]
        )
        receipt = operation["terminal_receipt"]
        if any(
            receipt[name] != operation[name]
            for name in ("run_id", "stage", "operation_id")
        ) or any(
            receipt[name] != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        ) or receipt["predecessor_content_sha256"] != operation[
            "predecessor_content_sha256"
        ]:
            raise ValueError("benchmark terminal receipt identity differs from operation")
        if phase == "complete":
            if (
                receipt["outcome"] != "benchmark_v2_incumbent_observe_complete"
                or receipt["terminal_intent_ref"]
                != {"content_sha256": operation["terminal_intent"]["content_sha256"]}
                or receipt["generic_adoption_ref"] != operation["generic_adoption_ref"]
                or receipt["window_adoption_ref"] != operation["window_adoption_ref"]
                or receipt["worker_cleanup_ref"] != operation["worker_cleanup_ref"]
                or receipt["provider_cleanup_ref"] != operation["provider_cleanup_ref"]
            ):
                raise ValueError("benchmark complete receipt parents differ from operation")
        if phase == "cancelled":
            if (
                receipt["outcome"] != "benchmark_v2_incumbent_cancelled"
                or receipt["cancel_intent_ref"]
                != {"content_sha256": operation["cancel_intent"]["content_sha256"]}
                or receipt["worker_cleanup_ref"] != operation["worker_cleanup_ref"]
                or receipt["provider_cleanup_ref"] != operation["provider_cleanup_ref"]
            ):
                raise ValueError("benchmark cancelled receipt parents differ from operation")
    if phase in {"complete", "cancelled"} and operation["terminal_receipt"] is None:
        raise ValueError("benchmark terminal operation requires terminal receipt")
    if phase not in {"complete", "cancelled"} and operation["terminal_receipt"] is not None:
        raise ValueError("benchmark nonterminal operation cannot have terminal receipt")
    predecessor = operation["predecessor_content_sha256"]
    if current_revision == prepared_revision:
        if predecessor is not None:
            raise ValueError("benchmark first operation predecessor must be null")
    else:
        _sha(predecessor, "benchmark operation predecessor SHA")
    _sha(operation["content_sha256"], "benchmark operation content SHA")
    if operation["content_sha256"] != content_sha256(operation):
        raise ValueError("benchmark operation content SHA mismatch")
    operation["handler_payload_source"] = source
    operation["handler_payload_source_ref"] = source_ref
    operation["worker_ref"] = worker
    return operation


def compose_benchmark_v2_incumbent_terminal_intent(
    *,
    operation: Mapping[str, object],
    result_sha256: str,
    normal_binding_evidence_ref: Mapping[str, object],
    provider_cleanup_evidence_ref: Mapping[str, object],
    worker_cleanup_evidence_ref: Mapping[str, object],
    intent_at: str,
) -> dict[str, Any]:
    current = validate_benchmark_v2_incumbent_operation(operation)
    if current["phase"] != "result_ready" or current["cancel_intent"] is not None:
        raise ValueError("benchmark terminal intent requires result_ready")
    result_identity = current["result_identity_ref"]
    if isinstance(result_identity, Mapping):
        expected_result_sha256 = result_identity.get("result_sha256")
        if expected_result_sha256 is None and set(result_identity) == {"content_sha256"}:
            expected_result_sha256 = result_identity.get("content_sha256")
        if expected_result_sha256 != result_sha256:
            raise ValueError("benchmark terminal result SHA differs from A inspection")
    worker = current["worker_ref"]
    return validate_benchmark_v2_incumbent_terminal_intent(
        _seal(
            {
                "contract_version": BENCHMARK_V2_INCUMBENT_TERMINAL_INTENT_CONTRACT,
                "run_id": current["run_id"],
                "stage": current["stage"],
                "operation_id": current["operation_id"],
                "worker_id": worker["worker_id"],
                "model_request_id": worker["model_request_id"],
                "payload_sha256": worker["payload_sha256"],
                "result_sha256": result_sha256,
                "normal_binding_evidence_ref": deepcopy(dict(normal_binding_evidence_ref)),
                "provider_cleanup_evidence_ref": deepcopy(dict(provider_cleanup_evidence_ref)),
                "worker_cleanup_evidence_ref": deepcopy(dict(worker_cleanup_evidence_ref)),
                "intent_revision": current["current_document_revision"] + 1,
                "intent_at": intent_at,
                "predecessor_content_sha256": current["content_sha256"],
            }
        )
    )


def compose_benchmark_v2_incumbent_cancel_intent(
    *,
    operation: Mapping[str, object],
    reason: str,
    intent_at: str,
    process_identity: Mapping[str, object] | None,
    scope_name: str | None,
    assignment_proven_ref: Mapping[str, object] | None,
) -> dict[str, Any]:
    current = validate_benchmark_v2_incumbent_operation(operation)
    if current["phase"] not in {
        "prepared",
        "provider_owner_prepared",
        "worker_starting",
        "worker_bound",
        "result_ready",
    } or current["terminal_intent"] is not None:
        raise ValueError("benchmark cancel intent requires cancellable phase")
    worker = current["worker_ref"]
    return validate_benchmark_v2_incumbent_cancel_intent(
        _seal(
            {
                "contract_version": BENCHMARK_V2_INCUMBENT_CANCEL_INTENT_CONTRACT,
                "run_id": current["run_id"],
                "stage": current["stage"],
                "operation_id": current["operation_id"],
                "worker_id": worker["worker_id"],
                "model_request_id": worker["model_request_id"],
                "payload_sha256": worker["payload_sha256"],
                "execution_nonce": current["execution_nonce"],
                "reservation_ref": current["reservation_ref"],
                "operation_anchor_ref": current["operation_anchor_ref"],
                "acquisition_intent_ref": current["acquisition_intent_ref"],
                "runtime_owner_ref": current["runtime_owner_ref"],
                "process_identity": None if process_identity is None else deepcopy(dict(process_identity)),
                "scope_name": scope_name,
                "assignment_proven_ref": None if assignment_proven_ref is None else deepcopy(dict(assignment_proven_ref)),
                "reason": reason,
                "intent_revision": current["current_document_revision"] + 1,
                "intent_at": intent_at,
                "predecessor_content_sha256": current["content_sha256"],
            }
        )
    )


def compose_benchmark_v2_incumbent_terminal_receipt(
    *,
    operation: Mapping[str, object],
    outcome: str,
    window_adoption_ref: Mapping[str, object] | None,
    worker_cleanup_ref: Mapping[str, object],
    provider_cleanup_ref: Mapping[str, object],
    terminal_at: str,
) -> dict[str, Any]:
    current = validate_benchmark_v2_incumbent_operation(operation)
    worker = current["worker_ref"]
    provider_cleanup = _sealed_parent(
        provider_cleanup_ref, "benchmark terminal provider cleanup ref"
    )
    provider_outcome = provider_cleanup.get("outcome")
    if outcome == "benchmark_v2_incumbent_observe_complete":
        if (
            current["phase"] != "adopted"
            or current["terminal_intent"] is None
            or current["cancel_intent"] is not None
            or current["generic_adoption_ref"] is None
            or window_adoption_ref is None
            or provider_outcome != "verified_exact_process_exited"
        ):
            raise ValueError("benchmark complete receipt parents are invalid")
        result_sha256 = current["terminal_intent"]["result_sha256"]
        terminal_intent_ref = {
            "content_sha256": current["terminal_intent"]["content_sha256"]
        }
        cancel_intent_ref = None
        generic_adoption_ref = current["generic_adoption_ref"]
        window_ref = deepcopy(dict(window_adoption_ref))
    elif outcome == "benchmark_v2_incumbent_cancelled":
        if (
            current["phase"] not in {"cancel_intent", "cleanup_pending"}
            or current["cancel_intent"] is None
            or current["terminal_intent"] is not None
            or provider_outcome
            not in {"verified_not_acquired", "verified_exact_process_exited"}
        ):
            raise ValueError("benchmark cancelled receipt parents are invalid")
        result_sha256 = None
        terminal_intent_ref = None
        cancel_intent_ref = {
            "content_sha256": current["cancel_intent"]["content_sha256"]
        }
        generic_adoption_ref = None
        window_ref = None
    else:
        raise ValueError("benchmark terminal receipt outcome is invalid")
    return validate_benchmark_v2_incumbent_terminal_receipt(
        _seal(
            {
                "contract_version": BENCHMARK_V2_INCUMBENT_TERMINAL_RECEIPT_CONTRACT,
                "outcome": outcome,
                "run_id": current["run_id"],
                "stage": current["stage"],
                "operation_id": current["operation_id"],
                "worker_id": worker["worker_id"],
                "model_request_id": worker["model_request_id"],
                "payload_sha256": worker["payload_sha256"],
                "result_sha256": result_sha256,
                "terminal_intent_ref": terminal_intent_ref,
                "cancel_intent_ref": cancel_intent_ref,
                "generic_adoption_ref": generic_adoption_ref,
                "window_adoption_ref": window_ref,
                "worker_cleanup_ref": deepcopy(dict(worker_cleanup_ref)),
                "provider_cleanup_ref": provider_cleanup,
                "provider_cleanup_outcome": provider_outcome,
                "terminal_at": terminal_at,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "predecessor_content_sha256": current["content_sha256"],
            }
        )
    )


def transition_benchmark_v2_incumbent_operation(
    operation: Mapping[str, object],
    *,
    to_phase: str,
    changes: Mapping[str, object],
) -> dict[str, Any]:
    current = validate_benchmark_v2_incumbent_operation(operation)
    if to_phase in _TERMINAL_PHASES and current["phase"] == to_phase:
        if changes:
            raise ValueError("terminal replay cannot mutate operation")
        return deepcopy(current)
    if to_phase not in _LEGAL_TRANSITIONS.get(current["phase"], set()):
        raise ValueError("benchmark operation has no legal transition for requested edge")
    if not isinstance(changes, Mapping) or not set(changes).issubset(_MUTABLE_FIELDS):
        raise ValueError("benchmark transition changes are not closed")
    body = deepcopy(current)
    body.pop("content_sha256")
    for name, value in changes.items():
        body[name] = deepcopy(value)
    body["phase"] = to_phase
    body["predecessor_content_sha256"] = current["content_sha256"]
    body["current_document_revision"] = current["current_document_revision"] + 1
    if to_phase == "terminal_intent" and (
        body["terminal_intent"] is None or body["cancel_intent"] is not None
    ):
        raise ValueError("benchmark terminal intent transition is invalid")
    if to_phase == "cancel_intent" and (
        body["cancel_intent"] is None or body["terminal_intent"] is not None
    ):
        raise ValueError("benchmark cancel intent transition is invalid")
    return validate_benchmark_v2_incumbent_operation(_seal(body))


def advance_benchmark_v2_incumbent_cancel_cleanup(
    operation: Mapping[str, object],
    *,
    worker_cleanup_ref: Mapping[str, object] | None,
    provider_cleanup_ref: Mapping[str, object] | None,
    provider_materialization_state: str,
    provider_lease_acquired: bool,
    terminal_at: str,
) -> dict[str, Any]:
    current = validate_benchmark_v2_incumbent_operation(operation)
    if current["phase"] not in {"cancel_intent", "cleanup_pending"}:
        raise ValueError("benchmark cancel cleanup requires cancel intent")
    changes = {
        "worker_cleanup_ref": worker_cleanup_ref,
        "provider_cleanup_ref": provider_cleanup_ref,
    }
    if (
        worker_cleanup_ref is None
        or provider_cleanup_ref is None
        or (
            provider_materialization_state == "materialization_possible"
            and provider_lease_acquired is False
        )
    ):
        return transition_benchmark_v2_incumbent_operation(
            current,
            to_phase="cleanup_pending",
            changes=changes,
        )
    provider_cleanup = _sealed_parent(
        provider_cleanup_ref, "benchmark cancel provider cleanup ref"
    )
    provider_outcome = provider_cleanup.get("outcome")
    compatible = (
        provider_materialization_state == "aborted_never_materialized"
        and provider_lease_acquired is False
        and provider_outcome == "verified_not_acquired"
    ) or (
        provider_lease_acquired is True
        and provider_outcome == "verified_exact_process_exited"
    )
    if not compatible:
        raise ValueError("benchmark provider cleanup outcome is state-incompatible")
    current_with_cleanup = transition_benchmark_v2_incumbent_operation(
        current,
        to_phase="cleanup_pending",
        changes=changes,
    )
    receipt = compose_benchmark_v2_incumbent_terminal_receipt(
        operation=current_with_cleanup,
        outcome="benchmark_v2_incumbent_cancelled",
        window_adoption_ref=None,
        worker_cleanup_ref=worker_cleanup_ref,
        provider_cleanup_ref=provider_cleanup,
        terminal_at=terminal_at,
    )
    return transition_benchmark_v2_incumbent_operation(
        current_with_cleanup,
        to_phase="cancelled",
        changes={"terminal_receipt": receipt},
    )


def replay_benchmark_v2_incumbent_terminal(
    operation: Mapping[str, object],
) -> dict[str, Any]:
    current = validate_benchmark_v2_incumbent_operation(operation)
    if current["phase"] not in _TERMINAL_PHASES:
        raise ValueError("benchmark operation is not terminal")
    return deepcopy(current)


class BenchmarkV2IncumbentWorkflowService:
    """以同一composition暴露closed文档、运行恢复和终态重放。"""

    def __init__(self, composition: object) -> None:
        self._composition = composition

    @property
    def composition(self) -> object:
        return self._composition

    def operation_lock(self, *, run_id: str, operation_id: str):
        from app.learn.workflow_service import get_learning_workflow_operation_lock

        return get_learning_workflow_operation_lock(
            store=self._composition.store,
            run_id=run_id,
            operation_id=operation_id,
        )

    def validate_document(self, value: Mapping[str, object]) -> dict[str, Any]:
        return validate_benchmark_v2_incumbent_operation(value)

    def replay_terminal(self, value: Mapping[str, object]) -> dict[str, Any]:
        return replay_benchmark_v2_incumbent_terminal(value)

    def start(self, **kwargs: Any) -> dict[str, Any]:
        from app.learn.workflow_service import (
            _start_benchmark_v2_incumbent_operation,
        )

        return _start_benchmark_v2_incumbent_operation(
            composition=self._composition,
            **kwargs,
        )

    def resume(self, **kwargs: Any) -> dict[str, Any]:
        from app.learn.workflow_service import (
            _resume_benchmark_v2_incumbent_operation,
        )

        return _resume_benchmark_v2_incumbent_operation(
            composition=self._composition,
            **kwargs,
        )

    def cancel(self, **kwargs: Any) -> dict[str, Any]:
        from app.learn.workflow_service import (
            _cancel_benchmark_v2_incumbent_operation,
        )

        return _cancel_benchmark_v2_incumbent_operation(
            composition=self._composition,
            **kwargs,
        )


_PRODUCTION_BENCHMARK_V2_WORKFLOW_SERVICE: BenchmarkV2IncumbentWorkflowService | None = None


def get_production_benchmark_v2_workflow_service() -> BenchmarkV2IncumbentWorkflowService:
    global _PRODUCTION_BENCHMARK_V2_WORKFLOW_SERVICE
    if _PRODUCTION_BENCHMARK_V2_WORKFLOW_SERVICE is None:
        from app.learn.workflow_service import (
            get_production_learning_workflow_service_composition,
        )

        _PRODUCTION_BENCHMARK_V2_WORKFLOW_SERVICE = BenchmarkV2IncumbentWorkflowService(
            get_production_learning_workflow_service_composition()
        )
    return _PRODUCTION_BENCHMARK_V2_WORKFLOW_SERVICE
