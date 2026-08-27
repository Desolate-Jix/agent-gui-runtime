"""Benchmark-v2 incumbent的closed documents与纯重放核心。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

from app.learn.hybrid.benchmark_v2_contracts import (
    BENCHMARK_RELEASE_ID,
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (
    provider_case_resolver_corpus_file_ref,
)
from app.learn.recognition.uei.canonical import (
    content_sha256 as runtime_content_sha256,
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
BENCHMARK_V2_WORKFLOW_WINDOW_BINDING_CONTRACT = (
    "benchmark_v2_workflow_window_binding_v1"
)
BENCHMARK_V2_HYBRID_SCREEN_GROUP_START_CONTRACT = (
    "benchmark_v2_hybrid_screen_group_start_v1"
)
BENCHMARK_V2_WORKFLOW_SERVICE_OPERATION_REF_CONTRACT = (
    "benchmark_v2_workflow_service_operation_ref_v1"
)
BENCHMARK_V2_WORKFLOW_SERVICE_STEP_CONTRACT = (
    "benchmark_v2_workflow_service_step_v1"
)
BENCHMARK_V2_ADOPTED_RESULT_PROJECTION_CONTRACT = (
    "benchmark_v2_adopted_result_projection_v1"
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
    "provider_reservation_ref",
    "acquisition_owner_ref",
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
    "provider_reservation_ref",
    "acquisition_owner_ref",
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
_WORKFLOW_WINDOW_BINDING_FIELDS = {
    "contract_version",
    "run_id",
    "stage",
    "operation_id",
    "window_binding_ref",
    "capture_ref",
    "owner_journal_ref",
    "expected_uia_root_ref",
    "safety",
    "content_sha256",
}
_HYBRID_SCREEN_GROUP_START_FIELDS = {
    "contract_version",
    "benchmark_release_id",
    "attempt_ref",
    "partition",
    "screen_group",
    "provider_corpus_ref",
    "case_refs",
    "hybrid_capture_bundle_ref",
    "request_ref",
    "registration_ref",
    "manifest_ref",
    "capture_image_path",
    "hybrid_config",
    "capture_bundle",
    "safety",
    "content_sha256",
}
_WORKFLOW_SERVICE_OPERATION_REF_FIELDS = {
    "contract_version",
    "mode",
    "run_id",
    "stage",
    "operation_id",
    "workflow_state_ref",
    "stage_execution_ref",
    "request_ref",
    "window_binding_ref",
    "capture_ref",
    "worker_ref",
    "status",
    "predecessor_content_sha256",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_ADOPTED_RESULT_PROJECTION_FIELDS = {
    "contract_version",
    "mode",
    "run_id",
    "stage",
    "operation_id",
    "worker_ref",
    "model_request_ref",
    "payload_ref",
    "result_ref",
    "adoption_ref",
    "response",
    "response_canonical_json",
    "response_canonical_sha256",
    "terminal_receipt",
    "window_adoption_ref",
    "worker_cleanup_ref",
    "provider_cleanup_ref",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_WORKFLOW_SERVICE_STEP_FIELDS = {
    "contract_version",
    "mode",
    "status",
    "operation_ref",
    "worker_ref",
    "observed_task_kind",
    "adopted_result_projection",
    "terminal_receipt",
    "cleanup_refs",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_WORKFLOW_SERVICE_MODES = frozenset({"hybrid_v1_1", "incumbent_qwen_only"})
_WORKFLOW_SERVICE_STATUSES = frozenset(
    {"pending", "advanced", "complete", "safe_stopped", "cancelled", "cleanup_pending"}
)
_NON_AUTHORIZING_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
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


def _runtime_sealed_parent(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a sealed mapping")
    result = deepcopy(dict(value))
    digest = result.get("content_sha256")
    _sha(digest, f"{name}.content_sha256")
    if len(result) > 1 and runtime_content_sha256(result) != digest:
        raise ValueError(f"{name} content SHA mismatch")
    return result


def _seal(body: Mapping[str, object]) -> dict[str, Any]:
    result = deepcopy(dict(body))
    result["content_sha256"] = content_sha256(result)
    return result


def _payload_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _validate_non_authorizing_safety(value: object, name: str) -> dict[str, bool]:
    safety = _closed(
        value,
        {"artifact_is_authorization", "execute_binding_enabled"},
        name,
    )
    if safety != _NON_AUTHORIZING_SAFETY:
        raise ValueError(f"{name} cannot authorize actions")
    return safety


def _validate_provider_case_ref(value: object) -> dict[str, Any]:
    ref = _closed(
        value,
        {"case_id", "case_content_sha256"},
        "benchmark provider case ref",
    )
    _text(ref["case_id"], "benchmark provider case id")
    _sha(ref["case_content_sha256"], "benchmark provider case SHA")
    return ref


def validate_benchmark_v2_workflow_window_binding(value: object) -> dict[str, Any]:
    binding = _closed(
        value,
        _WORKFLOW_WINDOW_BINDING_FIELDS,
        "benchmark workflow window binding",
    )
    if binding["contract_version"] != BENCHMARK_V2_WORKFLOW_WINDOW_BINDING_CONTRACT:
        raise ValueError("benchmark workflow window binding contract is invalid")
    for name in ("run_id", "operation_id"):
        _text(binding[name], f"benchmark workflow window binding {name}")
    if binding["stage"] != "screen_understanding":
        raise ValueError("benchmark workflow window binding stage is invalid")
    binding["window_binding_ref"] = _identity_ref(
        binding["window_binding_ref"], "benchmark workflow window binding ref"
    )
    binding["capture_ref"] = _identity_ref(
        binding["capture_ref"], "benchmark workflow capture ref"
    )
    for name in ("owner_journal_ref", "expected_uia_root_ref"):
        binding[name] = _runtime_sealed_parent(
            binding[name], f"benchmark workflow window binding {name}"
        )
    binding["safety"] = _validate_non_authorizing_safety(
        binding["safety"], "benchmark workflow window binding safety"
    )
    _sha(binding["content_sha256"], "benchmark workflow window binding SHA")
    if binding["content_sha256"] != content_sha256(binding):
        raise ValueError("benchmark workflow window binding content SHA mismatch")
    return binding


def compose_benchmark_v2_workflow_window_binding(
    *,
    run_id: str,
    operation_id: str,
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    owner_journal_ref: Mapping[str, object],
    expected_uia_root_ref: Mapping[str, object],
) -> dict[str, Any]:
    body = {
        "contract_version": BENCHMARK_V2_WORKFLOW_WINDOW_BINDING_CONTRACT,
        "run_id": run_id,
        "stage": "screen_understanding",
        "operation_id": operation_id,
        "window_binding_ref": deepcopy(dict(window_binding_ref)),
        "capture_ref": deepcopy(dict(capture_ref)),
        "owner_journal_ref": deepcopy(dict(owner_journal_ref)),
        "expected_uia_root_ref": deepcopy(dict(expected_uia_root_ref)),
        "safety": deepcopy(_NON_AUTHORIZING_SAFETY),
    }
    return validate_benchmark_v2_workflow_window_binding(_seal(body))


def validate_benchmark_v2_hybrid_screen_group_start(value: object) -> dict[str, Any]:
    start = _closed(
        value,
        _HYBRID_SCREEN_GROUP_START_FIELDS,
        "benchmark hybrid screen group start",
    )
    if start["contract_version"] != BENCHMARK_V2_HYBRID_SCREEN_GROUP_START_CONTRACT:
        raise ValueError("benchmark hybrid screen group start contract is invalid")
    if start["benchmark_release_id"] != BENCHMARK_RELEASE_ID:
        raise ValueError("benchmark hybrid screen group release is invalid")
    for name in ("partition", "screen_group", "capture_image_path"):
        _text(start[name], f"benchmark hybrid screen group {name}")
    if (
        "\\" in start["capture_image_path"]
        or Path(start["capture_image_path"]).is_absolute()
        or ".." in Path(start["capture_image_path"]).parts
    ):
        raise ValueError("benchmark hybrid capture image path is invalid")
    for name in ("attempt_ref", "provider_corpus_ref"):
        start[name] = _runtime_sealed_parent(
            start[name], f"benchmark hybrid screen group {name}"
        )
    case_refs = start["case_refs"]
    if not isinstance(case_refs, list) or len(case_refs) != 5:
        raise ValueError("benchmark hybrid screen group requires exactly five case refs")
    start["case_refs"] = [_validate_provider_case_ref(item) for item in case_refs]
    case_ids = [item["case_id"] for item in start["case_refs"]]
    if len(set(case_ids)) != 5:
        raise ValueError("benchmark hybrid screen group case refs must be unique")
    for name in (
        "hybrid_capture_bundle_ref",
        "request_ref",
        "registration_ref",
        "manifest_ref",
    ):
        start[name] = _identity_ref(
            start[name], f"benchmark hybrid screen group {name}"
        )
    for name in ("hybrid_config", "capture_bundle"):
        if not isinstance(start[name], Mapping):
            raise ValueError(f"benchmark hybrid screen group {name} must be a mapping")
        start[name] = deepcopy(dict(start[name]))
    start["safety"] = _validate_non_authorizing_safety(
        start["safety"], "benchmark hybrid screen group safety"
    )
    _sha(start["content_sha256"], "benchmark hybrid screen group SHA")
    if start["content_sha256"] != content_sha256(start):
        raise ValueError("benchmark hybrid screen group content SHA mismatch")
    return start


def compose_benchmark_v2_hybrid_screen_group_start(
    *,
    attempt_ref: Mapping[str, object],
    partition: str,
    screen_group: str,
    provider_corpus_ref: Mapping[str, object],
    case_refs: list[Mapping[str, object]],
    hybrid_capture_bundle_ref: Mapping[str, object],
    request_ref: Mapping[str, object],
    registration_ref: Mapping[str, object],
    manifest_ref: Mapping[str, object],
    capture_image_path: str,
    hybrid_config: Mapping[str, object],
    capture_bundle: Mapping[str, object],
) -> dict[str, Any]:
    body = {
        "contract_version": BENCHMARK_V2_HYBRID_SCREEN_GROUP_START_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "attempt_ref": deepcopy(dict(attempt_ref)),
        "partition": partition,
        "screen_group": screen_group,
        "provider_corpus_ref": deepcopy(dict(provider_corpus_ref)),
        "case_refs": [deepcopy(dict(item)) for item in case_refs],
        "hybrid_capture_bundle_ref": deepcopy(dict(hybrid_capture_bundle_ref)),
        "request_ref": deepcopy(dict(request_ref)),
        "registration_ref": deepcopy(dict(registration_ref)),
        "manifest_ref": deepcopy(dict(manifest_ref)),
        "capture_image_path": capture_image_path,
        "hybrid_config": deepcopy(dict(hybrid_config)),
        "capture_bundle": deepcopy(dict(capture_bundle)),
        "safety": deepcopy(_NON_AUTHORIZING_SAFETY),
    }
    return validate_benchmark_v2_hybrid_screen_group_start(_seal(body))


def validate_benchmark_v2_workflow_service_operation_ref(
    value: object,
) -> dict[str, Any]:
    operation_ref = _closed(
        value,
        _WORKFLOW_SERVICE_OPERATION_REF_FIELDS,
        "benchmark workflow service operation ref",
    )
    if (
        operation_ref["contract_version"]
        != BENCHMARK_V2_WORKFLOW_SERVICE_OPERATION_REF_CONTRACT
    ):
        raise ValueError("benchmark workflow service operation ref contract is invalid")
    if operation_ref["mode"] not in _WORKFLOW_SERVICE_MODES:
        raise ValueError("benchmark workflow service mode is invalid")
    for name in ("run_id", "stage", "operation_id"):
        _text(operation_ref[name], f"benchmark workflow service operation {name}")
    workflow_state_ref = _closed(
        operation_ref["workflow_state_ref"],
        {"run_id", "revision", "content_sha256"},
        "benchmark workflow state ref",
    )
    if workflow_state_ref["run_id"] != operation_ref["run_id"]:
        raise ValueError("benchmark workflow state run identity is stale")
    _revision(workflow_state_ref["revision"], "benchmark workflow state revision")
    _sha(workflow_state_ref["content_sha256"], "benchmark workflow state SHA")
    stage_execution_ref = _closed(
        operation_ref["stage_execution_ref"],
        {"run_id", "stage", "operation_id", "revision", "content_sha256"},
        "benchmark stage execution ref",
    )
    for name in ("run_id", "stage", "operation_id"):
        if stage_execution_ref[name] != operation_ref[name]:
            raise ValueError(f"benchmark stage execution {name} identity is stale")
    _revision(stage_execution_ref["revision"], "benchmark stage execution revision")
    _sha(stage_execution_ref["content_sha256"], "benchmark stage execution SHA")
    if stage_execution_ref["revision"] != workflow_state_ref["revision"]:
        raise ValueError("benchmark workflow service revision lineage is stale")
    operation_ref["workflow_state_ref"] = workflow_state_ref
    operation_ref["stage_execution_ref"] = stage_execution_ref
    for name in ("request_ref", "window_binding_ref", "capture_ref"):
        operation_ref[name] = _identity_ref(
            operation_ref[name], f"benchmark workflow service {name}"
        )
    if operation_ref["worker_ref"] is not None:
        operation_ref["worker_ref"] = _runtime_sealed_parent(
            operation_ref["worker_ref"], "benchmark workflow service worker ref"
        )
    if operation_ref["status"] not in _WORKFLOW_SERVICE_STATUSES:
        raise ValueError("benchmark workflow service operation status is invalid")
    predecessor = operation_ref["predecessor_content_sha256"]
    if predecessor is not None:
        _sha(predecessor, "benchmark workflow service predecessor SHA")
        if predecessor == operation_ref.get("content_sha256"):
            raise ValueError("benchmark workflow service predecessor cannot be self")
    if (
        operation_ref["artifact_is_authorization"] is not False
        or operation_ref["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark workflow service operation ref cannot authorize actions")
    _sha(operation_ref["content_sha256"], "benchmark workflow service operation SHA")
    if operation_ref["content_sha256"] != content_sha256(operation_ref):
        raise ValueError("benchmark workflow service operation ref content SHA mismatch")
    return operation_ref


def compose_benchmark_v2_workflow_service_operation_ref(
    *,
    mode: str,
    run_id: str,
    stage: str,
    operation_id: str,
    workflow_state_ref: Mapping[str, object],
    stage_execution_ref: Mapping[str, object],
    request_ref: Mapping[str, object],
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    worker_ref: Mapping[str, object] | None,
    status: str,
    predecessor_operation_ref: Mapping[str, object] | None = None,
    predecessor_content_sha256: str | None = None,
) -> dict[str, Any]:
    if predecessor_operation_ref is not None and predecessor_content_sha256 is not None:
        raise ValueError("benchmark workflow service predecessor is ambiguous")
    predecessor_sha256 = predecessor_content_sha256
    if predecessor_operation_ref is not None:
        predecessor_sha256 = validate_benchmark_v2_workflow_service_operation_ref(
            predecessor_operation_ref
        )["content_sha256"]
    if predecessor_sha256 is not None:
        _sha(predecessor_sha256, "benchmark workflow service predecessor SHA")
    body = {
        "contract_version": BENCHMARK_V2_WORKFLOW_SERVICE_OPERATION_REF_CONTRACT,
        "mode": mode,
        "run_id": run_id,
        "stage": stage,
        "operation_id": operation_id,
        "workflow_state_ref": deepcopy(dict(workflow_state_ref)),
        "stage_execution_ref": deepcopy(dict(stage_execution_ref)),
        "request_ref": deepcopy(dict(request_ref)),
        "window_binding_ref": deepcopy(dict(window_binding_ref)),
        "capture_ref": deepcopy(dict(capture_ref)),
        "worker_ref": deepcopy(dict(worker_ref)) if worker_ref is not None else None,
        "status": status,
        "predecessor_content_sha256": predecessor_sha256,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    return validate_benchmark_v2_workflow_service_operation_ref(_seal(body))


def validate_benchmark_v2_adopted_result_projection(value: object) -> dict[str, Any]:
    projection = _closed(
        value,
        _ADOPTED_RESULT_PROJECTION_FIELDS,
        "benchmark adopted result projection",
    )
    if (
        projection["contract_version"]
        != BENCHMARK_V2_ADOPTED_RESULT_PROJECTION_CONTRACT
    ):
        raise ValueError("benchmark adopted result projection contract is invalid")
    if projection["mode"] not in _WORKFLOW_SERVICE_MODES:
        raise ValueError("benchmark adopted result projection mode is invalid")
    for name in ("run_id", "stage", "operation_id"):
        _text(projection[name], f"benchmark adopted result projection {name}")
    projection["worker_ref"] = _runtime_sealed_parent(
        projection["worker_ref"], "benchmark adopted result worker ref"
    )
    projection["model_request_ref"] = _identity_ref(
        projection["model_request_ref"], "benchmark adopted model request ref"
    )
    for name in ("payload_ref", "result_ref"):
        projection[name] = _content_ref(
            projection[name], f"benchmark adopted result {name}"
        )
    projection["adoption_ref"] = _runtime_sealed_parent(
        projection["adoption_ref"], "benchmark adopted generic adoption ref"
    )
    if not isinstance(projection["response"], Mapping):
        raise ValueError("benchmark adopted response body must be a mapping")
    projection["response"] = deepcopy(dict(projection["response"]))
    expected_response_bytes = canonical_json_bytes(projection["response"])
    if (
        not isinstance(projection["response_canonical_json"], str)
        or projection["response_canonical_json"].encode("utf-8")
        != expected_response_bytes
    ):
        raise ValueError("benchmark adopted canonical response bytes mismatch")
    _sha(
        projection["response_canonical_sha256"],
        "benchmark adopted canonical response SHA",
    )
    expected_response_sha256 = hashlib.sha256(expected_response_bytes).hexdigest()
    if projection["response_canonical_sha256"] != expected_response_sha256:
        raise ValueError("benchmark adopted response SHA mismatch")
    terminal_names = (
        "terminal_receipt",
        "window_adoption_ref",
        "worker_cleanup_ref",
        "provider_cleanup_ref",
    )
    terminal_presence = {projection[name] is not None for name in terminal_names}
    if len(terminal_presence) != 1:
        raise ValueError("benchmark adopted terminal parents must be all null or all present")
    for name in terminal_names:
        if projection[name] is not None:
            if (
                name == "terminal_receipt"
                and isinstance(projection[name], Mapping)
                and projection[name].get("contract_version")
                == BENCHMARK_V2_INCUMBENT_TERMINAL_RECEIPT_CONTRACT
            ):
                projection[name] = validate_benchmark_v2_incumbent_terminal_receipt(
                    projection[name]
                )
            else:
                projection[name] = _runtime_sealed_parent(
                    projection[name], f"benchmark adopted result {name}"
                )
    terminal_receipt = projection["terminal_receipt"]
    if (
        isinstance(terminal_receipt, Mapping)
        and terminal_receipt.get("contract_version")
        == BENCHMARK_V2_INCUMBENT_TERMINAL_RECEIPT_CONTRACT
    ):
        worker = projection["worker_ref"]
        if (
            any(
                terminal_receipt.get(name) != projection[name]
                for name in ("run_id", "stage", "operation_id")
            )
            or terminal_receipt.get("worker_id") != worker.get("worker_id")
            or terminal_receipt.get("model_request_id")
            != projection["model_request_ref"]["id"]
            or terminal_receipt.get("payload_sha256")
            != projection["payload_ref"]["content_sha256"]
            or terminal_receipt.get("result_sha256")
            != projection["result_ref"]["content_sha256"]
            or terminal_receipt.get("generic_adoption_ref")
            != projection["adoption_ref"]
            or terminal_receipt.get("window_adoption_ref")
            != projection["window_adoption_ref"]
            or terminal_receipt.get("worker_cleanup_ref")
            != projection["worker_cleanup_ref"]
            or terminal_receipt.get("provider_cleanup_ref")
            != projection["provider_cleanup_ref"]
        ):
            raise ValueError("benchmark adopted terminal lineage is stale")
    if (
        projection["artifact_is_authorization"] is not False
        or projection["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark adopted result projection cannot authorize actions")
    _sha(projection["content_sha256"], "benchmark adopted result projection SHA")
    if projection["content_sha256"] != content_sha256(projection):
        raise ValueError("benchmark adopted result projection content SHA mismatch")
    return projection


def compose_benchmark_v2_adopted_result_projection(
    *,
    mode: str,
    run_id: str,
    stage: str,
    operation_id: str,
    worker_ref: Mapping[str, object],
    model_request_ref: Mapping[str, object],
    payload_ref: Mapping[str, object],
    result_ref: Mapping[str, object],
    adoption_ref: Mapping[str, object],
    response: Mapping[str, object],
    terminal_receipt: Mapping[str, object] | None,
    window_adoption_ref: Mapping[str, object] | None,
    worker_cleanup_ref: Mapping[str, object] | None,
    provider_cleanup_ref: Mapping[str, object] | None,
) -> dict[str, Any]:
    copied_response = deepcopy(dict(response))
    response_bytes = canonical_json_bytes(copied_response)
    body = {
        "contract_version": BENCHMARK_V2_ADOPTED_RESULT_PROJECTION_CONTRACT,
        "mode": mode,
        "run_id": run_id,
        "stage": stage,
        "operation_id": operation_id,
        "worker_ref": deepcopy(dict(worker_ref)),
        "model_request_ref": deepcopy(dict(model_request_ref)),
        "payload_ref": deepcopy(dict(payload_ref)),
        "result_ref": deepcopy(dict(result_ref)),
        "adoption_ref": deepcopy(dict(adoption_ref)),
        "response": copied_response,
        "response_canonical_json": response_bytes.decode("utf-8"),
        "response_canonical_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "terminal_receipt": (
            deepcopy(dict(terminal_receipt)) if terminal_receipt is not None else None
        ),
        "window_adoption_ref": (
            deepcopy(dict(window_adoption_ref))
            if window_adoption_ref is not None
            else None
        ),
        "worker_cleanup_ref": (
            deepcopy(dict(worker_cleanup_ref)) if worker_cleanup_ref is not None else None
        ),
        "provider_cleanup_ref": (
            deepcopy(dict(provider_cleanup_ref))
            if provider_cleanup_ref is not None
            else None
        ),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    return validate_benchmark_v2_adopted_result_projection(_seal(body))


def validate_benchmark_v2_workflow_service_step(value: object) -> dict[str, Any]:
    step = _closed(
        value,
        _WORKFLOW_SERVICE_STEP_FIELDS,
        "benchmark workflow service step",
    )
    if step["contract_version"] != BENCHMARK_V2_WORKFLOW_SERVICE_STEP_CONTRACT:
        raise ValueError("benchmark workflow service step contract is invalid")
    operation_ref = validate_benchmark_v2_workflow_service_operation_ref(
        step["operation_ref"]
    )
    if step["mode"] != operation_ref["mode"]:
        raise ValueError("benchmark workflow service step mode does not match operation")
    if step["status"] != operation_ref["status"]:
        raise ValueError("benchmark workflow service step status does not match operation")
    step["operation_ref"] = operation_ref
    if step["worker_ref"] != operation_ref["worker_ref"]:
        raise ValueError("benchmark workflow service step worker does not match operation")
    if step["worker_ref"] is not None:
        step["worker_ref"] = _runtime_sealed_parent(
            step["worker_ref"], "benchmark workflow service step worker ref"
        )
    if step["observed_task_kind"] is not None:
        _text(step["observed_task_kind"], "benchmark workflow service observed task kind")
    projection = step["adopted_result_projection"]
    if projection is not None:
        projection = validate_benchmark_v2_adopted_result_projection(projection)
        for name in ("mode", "run_id", "stage", "operation_id", "worker_ref"):
            expected = operation_ref[name] if name != "mode" else step["mode"]
            if projection[name] != expected:
                raise ValueError(
                    f"benchmark workflow service adopted projection {name} is stale"
                )
        step["adopted_result_projection"] = projection
    if step["terminal_receipt"] is not None:
        if (
            isinstance(step["terminal_receipt"], Mapping)
            and step["terminal_receipt"].get("contract_version")
            == BENCHMARK_V2_INCUMBENT_TERMINAL_RECEIPT_CONTRACT
        ):
            step["terminal_receipt"] = validate_benchmark_v2_incumbent_terminal_receipt(
                step["terminal_receipt"]
            )
        else:
            step["terminal_receipt"] = _runtime_sealed_parent(
                step["terminal_receipt"], "benchmark workflow service terminal receipt"
            )
    cleanup_refs = _closed(
        step["cleanup_refs"],
        {"worker_cleanup_ref", "provider_cleanup_ref"},
        "benchmark workflow service cleanup refs",
    )
    for name in ("worker_cleanup_ref", "provider_cleanup_ref"):
        if cleanup_refs[name] is not None:
            cleanup_refs[name] = _runtime_sealed_parent(
                cleanup_refs[name], f"benchmark workflow service {name}"
            )
    step["cleanup_refs"] = cleanup_refs
    if (
        isinstance(step["terminal_receipt"], Mapping)
        and step["terminal_receipt"].get("contract_version")
        == BENCHMARK_V2_INCUMBENT_TERMINAL_RECEIPT_CONTRACT
        and any(
            step["terminal_receipt"].get(name) != cleanup_refs[name]
            for name in ("worker_cleanup_ref", "provider_cleanup_ref")
        )
    ):
        raise ValueError("benchmark workflow service cleanup lineage is stale")
    if projection is not None:
        if step["terminal_receipt"] != projection["terminal_receipt"]:
            raise ValueError("benchmark workflow service terminal receipt is stale")
        for name in ("worker_cleanup_ref", "provider_cleanup_ref"):
            if cleanup_refs[name] != projection[name]:
                raise ValueError(f"benchmark workflow service {name} is stale")
    if (
        step["artifact_is_authorization"] is not False
        or step["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark workflow service step cannot authorize actions")
    _sha(step["content_sha256"], "benchmark workflow service step SHA")
    if step["content_sha256"] != content_sha256(step):
        raise ValueError("benchmark workflow service step content SHA mismatch")
    return step


def compose_benchmark_v2_workflow_service_step(
    *,
    operation_ref: Mapping[str, object],
    observed_task_kind: str | None,
    adopted_result_projection: Mapping[str, object] | None,
    terminal_receipt: Mapping[str, object] | None,
    cleanup_refs: Mapping[str, object],
) -> dict[str, Any]:
    current = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
    body = {
        "contract_version": BENCHMARK_V2_WORKFLOW_SERVICE_STEP_CONTRACT,
        "mode": current["mode"],
        "status": current["status"],
        "operation_ref": current,
        "worker_ref": deepcopy(current["worker_ref"]),
        "observed_task_kind": observed_task_kind,
        "adopted_result_projection": (
            deepcopy(dict(adopted_result_projection))
            if adopted_result_projection is not None
            else None
        ),
        "terminal_receipt": (
            deepcopy(dict(terminal_receipt)) if terminal_receipt is not None else None
        ),
        "cleanup_refs": deepcopy(dict(cleanup_refs)),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    return validate_benchmark_v2_workflow_service_step(_seal(body))


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
        "provider_reservation_ref": None,
        "acquisition_owner_ref": None,
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
        intent[name] = _runtime_sealed_parent(intent[name], f"benchmark terminal intent {name}")
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
            intent[name] = _runtime_sealed_parent(intent[name], f"benchmark cancel intent {name}")
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
        intent["assignment_proven_ref"] = _runtime_sealed_parent(
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
            receipt[name] = _runtime_sealed_parent(receipt[name], f"benchmark terminal receipt {name}")
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
    provider_parent_names = (
        "provider_reservation_ref",
        "acquisition_owner_ref",
        "acquisition_intent_ref",
        "runtime_owner_ref",
    )
    provider_parent_presence = {
        operation[name] is not None for name in provider_parent_names
    }
    if len(provider_parent_presence) != 1:
        raise ValueError("benchmark provider owner refs must be all null or all present")
    for name in provider_parent_names:
        if operation[name] is not None:
            operation[name] = _runtime_sealed_parent(operation[name], f"benchmark operation {name}")
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
    if phase == "prepared" and any(
        operation[name] is not None for name in provider_parent_names
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
    } and any(operation[name] is None for name in provider_parent_names):
        raise ValueError("benchmark operation requires provider owner refs")
    if operation["result_identity_ref"] is not None:
        operation["result_identity_ref"] = _runtime_sealed_parent(
            operation["result_identity_ref"], "benchmark result identity ref"
        )
    for name in (
        "window_adoption_ref",
        "worker_cleanup_ref",
        "provider_cleanup_ref",
        "generic_adoption_ref",
    ):
        if operation[name] is not None:
            operation[name] = _runtime_sealed_parent(operation[name], f"benchmark operation {name}")
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
    provider_cleanup = _runtime_sealed_parent(
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
    provider_cleanup = _runtime_sealed_parent(
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
    if current["phase"] == "cleanup_pending":
        if any(current[name] != value for name, value in changes.items()):
            raise ValueError("benchmark cleanup replay parents differ")
        current_with_cleanup = current
    else:
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


class BenchmarkV2WorkflowServicePortUnavailableError(RuntimeError):
    """高层端口尚未接线时拒绝伪造WorkflowService成功结果。"""


_WORKFLOW_SERVICE_PORT_UNAVAILABLE = (
    "benchmark_v2 workflow service orchestration is unavailable before Amendment S2/S3"
)


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

    def start_hybrid_operation(
        self,
        *,
        screen_group: Mapping[str, object],
        window_binding: Mapping[str, object],
    ) -> dict[str, Any]:
        group = validate_benchmark_v2_hybrid_screen_group_start(screen_group)
        binding = validate_benchmark_v2_workflow_window_binding(window_binding)
        from app.learn.workflow_service import (
            _start_benchmark_v2_hybrid_workflow_service,
        )

        return _start_benchmark_v2_hybrid_workflow_service(
            composition=self._composition,
            screen_group=group,
            window_binding=binding,
        )

    def continue_hybrid_operation(
        self,
        *,
        operation_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        current = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        from app.learn.workflow_service import (
            _continue_benchmark_v2_hybrid_workflow_service,
        )

        return _continue_benchmark_v2_hybrid_workflow_service(
            composition=self._composition,
            operation_ref=current,
        )

    def start_incumbent_observe(
        self,
        *,
        provider_case_ref: Mapping[str, object],
        window_binding: Mapping[str, object],
    ) -> dict[str, Any]:
        _validate_provider_case_ref(provider_case_ref)
        validate_benchmark_v2_workflow_window_binding(window_binding)
        from app.learn.workflow_service import (
            _start_benchmark_v2_incumbent_workflow_service,
        )

        return _start_benchmark_v2_incumbent_workflow_service(
            composition=self._composition,
            provider_case_ref=provider_case_ref,
            window_binding=window_binding,
        )

    def poll_incumbent_observe(
        self,
        *,
        operation_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        from app.learn.workflow_service import (
            _poll_benchmark_v2_incumbent_workflow_service,
        )

        return _poll_benchmark_v2_incumbent_workflow_service(
            composition=self._composition,
            operation_ref=operation_ref,
        )

    def adopt_and_terminalize_incumbent(
        self,
        *,
        operation_ref: Mapping[str, object],
        worker_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        current = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        worker = _runtime_sealed_parent(
            worker_ref, "benchmark workflow service adopted worker ref"
        )
        if current["worker_ref"] != worker:
            raise ValueError("benchmark workflow service adopted worker ref is stale")
        from app.learn.workflow_service import (
            _adopt_benchmark_v2_incumbent_workflow_service,
        )

        return _adopt_benchmark_v2_incumbent_workflow_service(
            composition=self._composition,
            operation_ref=current,
            worker_ref=worker,
        )

    def cancel_operation(
        self,
        *,
        operation_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        current = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        if current["mode"] == "hybrid_v1_1":
            from app.learn.workflow_service import (
                _cancel_benchmark_v2_hybrid_workflow_service,
            )

            return _cancel_benchmark_v2_hybrid_workflow_service(
                composition=self._composition,
                operation_ref=current,
            )
        from app.learn.workflow_service import (
            _cancel_benchmark_v2_incumbent_workflow_service,
        )

        return _cancel_benchmark_v2_incumbent_workflow_service(
            composition=self._composition,
            operation_ref=current,
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
