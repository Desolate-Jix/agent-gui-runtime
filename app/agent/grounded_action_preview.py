"""不可执行的当前 grounded action 人审快照。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from app.agent.reviewed_workflow_replay import (
    _review_selection_field_keys,
    _capture_lineage,
    _finite_number,
    _review_selection_hash,
    _semantic_hash,
)
from app.agent.action_parameters import reviewed_action_parameter_fields, validate_reviewed_action_grounding_geometry
from app.agent.text_execution import validate_text_execution_reference
from app.agent.text_field_evidence import validate_text_field_expectation_reference
from app.agent.runtime_contracts import (
    WorkflowRefV1,
    validate_agent_observation_v1,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KEYS = {
    "contract_version",
    "status",
    "review_only",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "grants_action_authority",
    "session_id",
    "observation_id",
    "intent_id",
    "workflow",
    "target_window_handle",
    "target_process_id",
    "current_observation",
    "review_selection",
    "grounding_preview",
    "content_sha256",
}
_GROUNDING_PREVIEW_KEYS = {
    "contract_version",
    "status",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "grants_action_authority",
    "review_only",
    "asset_id",
    "asset_content_sha256",
    "source_workflow_sha256",
    "reviewed_revision_hash",
    "canonical_origin",
    "transition_id",
    "source_state_id",
    "target_state_id",
    "semantic_action",
    "element_ref",
    "capture_lineage",
    "review_selection_sha256",
    "gate_selection_sha256",
    "candidate_id",
    "confidence",
    "score_margin",
    "bbox",
    "click_point",
    "grounding_evidence_refs",
    "gate_evidence_refs",
    "gate_decision_ref",
    "evidence_refs",
    "preview_sha256",
}
_REQUIREMENT_KEYS = {
    "current_capture_required",
    "fresh_grounding_required",
    "gate_required",
    "gate_endpoint",
    "post_action_verification_required",
    "semantic_success_rule_ids",
}


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_sha(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_bytes({key: value for key, value in payload.items() if key != "content_sha256"})
    ).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_refs(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_is_nonempty_text(item) for item in value)
        and value == sorted(value)
    )


def _validated_review_selection(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != _review_selection_field_keys(value):
        raise ValueError("grounded action preview review selection shape is invalid")
    selection = dict(value)
    if (
        selection.get("contract_version") != "review_transition_selection_v1"
        or selection.get("status") != "selected"
        or selection.get("review_only") is not True
        or selection.get("artifact_is_authorization") is not False
        or selection.get("execute_binding_enabled") is not False
        or selection.get("grants_action_authority") is not False
        or type(selection.get("requires_user_confirmation")) is not bool
    ):
        raise ValueError("grounded action preview review selection boundary is invalid")
    for key in (
        "asset_id",
        "transition_id",
        "source_state_id",
        "target_state_id",
        "semantic_action",
        "element_ref",
    ):
        if not _is_nonempty_text(selection.get(key)):
            raise ValueError("grounded action preview review selection field is invalid")
    for key in (
        "asset_content_sha256",
        "source_workflow_sha256",
        "reviewed_revision_hash",
        "review_selection_sha256",
        "selection_sha256",
    ):
        if not _is_sha(selection.get(key)):
            raise ValueError("grounded action preview review selection hash is invalid")
    if not isinstance(selection.get("canonical_origin"), str):
        raise ValueError("grounded action preview review selection origin is invalid")
    lineage = _capture_lineage(
        selection.get("capture_lineage")
        if isinstance(selection.get("capture_lineage"), Mapping)
        else {},
        require_exact=True,
    )
    if lineage is None:
        raise ValueError("grounded action preview review selection capture is invalid")
    requirements = selection.get("requirements")
    if not isinstance(requirements, Mapping) or set(requirements) != _REQUIREMENT_KEYS:
        raise ValueError("grounded action preview review selection requirements shape is invalid")
    if any(
        requirements.get(key) is not True
        for key in (
            "current_capture_required",
            "fresh_grounding_required",
            "gate_required",
            "post_action_verification_required",
        )
    ) or requirements.get("gate_endpoint") != "POST /action/execute_recognition_plan":
        raise ValueError("grounded action preview review selection requirements are invalid")
    rule_ids = requirements.get("semantic_success_rule_ids")
    if (
        not isinstance(rule_ids, list)
        or not rule_ids
        or not all(_is_nonempty_text(item) for item in rule_ids)
        or rule_ids != sorted(set(rule_ids))
    ):
        raise ValueError("grounded action preview review selection requirements are invalid")
    try:
        expected_hash = _review_selection_hash(selection)
    except (TypeError, ValueError) as exc:
        raise ValueError("grounded action preview review selection hash is invalid") from exc
    if (
        selection["review_selection_sha256"] != expected_hash
        or selection["selection_sha256"] != expected_hash
    ):
        raise ValueError("grounded action preview review selection hash is invalid")
    return selection


def _validated_grounding_preview(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != _GROUNDING_PREVIEW_KEYS | reviewed_action_parameter_fields(value).keys():
        raise ValueError("grounded action preview grounding preview shape is invalid")
    preview = dict(value)
    if (
        preview.get("contract_version") != "review_grounding_preview_v1"
        or preview.get("status") != "validated"
        or preview.get("review_only") is not True
        or preview.get("artifact_is_authorization") is not False
        or preview.get("execute_binding_enabled") is not False
        or preview.get("grants_action_authority") is not False
    ):
        raise ValueError("grounded action preview grounding preview boundary is invalid")
    for key in (
        "asset_id",
        "transition_id",
        "source_state_id",
        "target_state_id",
        "semantic_action",
        "element_ref",
        "candidate_id",
        "gate_decision_ref",
    ):
        if not _is_nonempty_text(preview.get(key)):
            raise ValueError("grounded action preview grounding preview field is invalid")
    for key in (
        "asset_content_sha256",
        "source_workflow_sha256",
        "reviewed_revision_hash",
        "review_selection_sha256",
        "gate_selection_sha256",
        "preview_sha256",
    ):
        if not _is_sha(preview.get(key)):
            raise ValueError("grounded action preview grounding preview hash is invalid")
    if not isinstance(preview.get("canonical_origin"), str):
        raise ValueError("grounded action preview grounding preview origin is invalid")
    lineage = _capture_lineage(
        preview.get("capture_lineage")
        if isinstance(preview.get("capture_lineage"), Mapping)
        else {},
        require_exact=True,
    )
    if lineage is None:
        raise ValueError("grounded action preview grounding preview capture is invalid")
    confidence = preview.get("confidence")
    margin = preview.get("score_margin")
    if not all(
        _finite_number(item, minimum=0.0, maximum=1.0)
        for item in (confidence, margin)
    ):
        raise ValueError("grounded action preview grounding preview score is invalid")
    bbox = preview.get("bbox")
    point = preview.get("click_point")
    if (
        not isinstance(bbox, Mapping)
        or set(bbox) != {"x", "y", "w", "h"}
        or not isinstance(point, Mapping)
        or set(point) != {"x", "y"}
        or not all(_finite_number(bbox.get(key), minimum=0.0) for key in ("x", "y", "w", "h"))
        or bbox["w"] <= 0
        or bbox["h"] <= 0
        or not all(_finite_number(point.get(key), minimum=0.0) for key in ("x", "y"))
    ):
        raise ValueError("grounded action preview grounding preview geometry is invalid")
    viewport = lineage["viewport_size"]
    validate_reviewed_action_grounding_geometry(preview, {**preview, "viewport_size": viewport})
    if (
        bbox["x"] + bbox["w"] > viewport["width"]
        or bbox["y"] + bbox["h"] > viewport["height"]
        or not (
            bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"]
            and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]
        )
    ):
        raise ValueError("grounded action preview grounding preview geometry is invalid")
    grounding_refs = preview.get("grounding_evidence_refs")
    gate_refs = preview.get("gate_evidence_refs")
    evidence_refs = preview.get("evidence_refs")
    if (
        not _valid_refs(grounding_refs)
        or not _valid_refs(gate_refs)
        or not _valid_refs(evidence_refs)
        or preview["gate_decision_ref"] != gate_refs[0]
        or evidence_refs != sorted(set(grounding_refs) | set(gate_refs))
    ):
        raise ValueError("grounded action preview grounding preview evidence is invalid")
    try:
        expected_hash = _semantic_hash(preview, excluded={"preview_sha256"})
    except (TypeError, ValueError) as exc:
        raise ValueError("grounded action preview grounding preview hash is invalid") from exc
    if preview["preview_sha256"] != expected_hash:
        raise ValueError("grounded action preview grounding preview hash is invalid")
    return preview


def _validate_cross_layer_binding(
    payload: Mapping[str, Any],
    workflow: WorkflowRefV1,
    current_observation: Any,
    selection: Mapping[str, Any],
    preview: Mapping[str, Any],
) -> None:
    workflow_json = workflow.model_dump(mode="json")
    if (
        current_observation.session_id != payload["session_id"]
        or current_observation.observation_id == payload["observation_id"]
        or current_observation.workflow.model_dump(mode="json") != workflow_json
        or dict(payload["workflow"]) != workflow_json
    ):
        raise ValueError("grounded action preview runtime binding is invalid")
    workflow_binding = {
        "asset_id": workflow.asset_id,
        "asset_content_sha256": workflow.asset_content_sha256,
        "source_workflow_sha256": workflow.source_workflow_sha256,
        "reviewed_revision_hash": workflow.reviewed_revision_hash,
    }
    if any(selection.get(key) != value for key, value in workflow_binding.items()):
        raise ValueError("grounded action preview workflow binding is invalid")
    shared_keys = (
        "asset_id",
        "asset_content_sha256",
        "source_workflow_sha256",
        "reviewed_revision_hash",
        "canonical_origin",
        "transition_id",
        "source_state_id",
        "target_state_id",
        "semantic_action",
        "element_ref",
    )
    if (
        any(preview.get(key) != selection.get(key) for key in shared_keys)
        or reviewed_action_parameter_fields(preview) != reviewed_action_parameter_fields(selection)
        or preview.get("capture_lineage") != selection.get("capture_lineage")
        or preview.get("review_selection_sha256")
        != selection.get("review_selection_sha256")
        or preview.get("gate_selection_sha256")
        != selection.get("review_selection_sha256")
    ):
        raise ValueError("grounded action preview nested binding is invalid")
    capture = current_observation.current_capture
    lineage = selection["capture_lineage"]
    if (
        capture.capture_id != lineage["capture_id"]
        or capture.screenshot_sha256 != lineage["screenshot_sha256"]
        or current_observation.state.state_id != selection["source_state_id"]
    ):
        raise ValueError("grounded action preview capture binding is invalid")
    actions = [
        action
        for action in current_observation.available_actions
        if action.action_id == selection["transition_id"]
    ]
    if len(actions) != 1:
        raise ValueError("grounded action preview action binding is invalid")
    action = actions[0]
    if (
        action.semantic_action != selection["semantic_action"]
        or reviewed_action_parameter_fields(action.model_dump(mode="json")) != reviewed_action_parameter_fields(selection)
        or action.target_state_id != selection["target_state_id"]
        or action.requires_user_confirmation
        != selection["requires_user_confirmation"]
    ):
        raise ValueError("grounded action preview action binding is invalid")
    application = current_observation.application
    origin = selection["canonical_origin"]
    if origin:
        hostname = urlsplit(origin).hostname
        if (
            application.kind != "web"
            or not hostname
            or application.identity_ref != f"application:web:{hostname.lower()}"
        ):
            raise ValueError("grounded action preview application binding is invalid")
    elif (
        application.kind != "native"
        or not application.identity_ref.startswith("application:native:")
    ):
        raise ValueError("grounded action preview application binding is invalid")


def _validated_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("grounded action preview shape is invalid")
    is_text = isinstance(value.get("review_selection"), Mapping) and value["review_selection"].get("semantic_action") == "fill_field"
    text_keys = {"text_execution_ref"} if is_text else set()
    if is_text and "text_field_expectation_ref" in value:
        text_keys.add("text_field_expectation_ref")
    if set(value) != _KEYS | text_keys:
        raise ValueError("grounded action preview shape is invalid")
    payload = dict(value)
    if (
        payload.get("contract_version") != "grounded_action_preview_v1"
        or payload.get("status") != "prepared"
        or payload.get("review_only") is not True
        or payload.get("artifact_is_authorization") is not False
        or payload.get("execute_binding_enabled") is not False
        or payload.get("grants_action_authority") is not False
    ):
        raise ValueError("grounded action preview authority boundary is invalid")
    for key in ("session_id", "observation_id", "intent_id"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"grounded action preview {key} is invalid")
    for key in ("target_window_handle", "target_process_id"):
        if type(payload.get(key)) is not int or payload[key] <= 0:
            raise ValueError(f"grounded action preview {key} is invalid")
    for key in (
        "workflow",
        "current_observation",
        "review_selection",
        "grounding_preview",
    ):
        if not isinstance(payload.get(key), Mapping):
            raise ValueError(f"grounded action preview {key} is invalid")
    try:
        workflow = WorkflowRefV1.model_validate(payload["workflow"])
        current_observation = validate_agent_observation_v1(
            payload["current_observation"]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("grounded action preview runtime binding is invalid") from exc
    review_selection = _validated_review_selection(payload["review_selection"])
    if is_text:
        validate_text_execution_reference(payload["text_execution_ref"], review_selection["text_parameters_ref"])
    grounding_preview = _validated_grounding_preview(payload["grounding_preview"])
    if "text_field_expectation_ref" in text_keys:
        expected = validate_text_field_expectation_reference(payload["text_field_expectation_ref"], review_selection["text_parameters_ref"])
        before = expected["before"]
        identity = before["identity"]
        bbox = grounding_preview["bbox"]
        x, y, width, height = identity["control_bbox"]
        viewport = review_selection["capture_lineage"]["viewport_size"]
        if (expected["text_execution_ref"] != payload["text_execution_ref"]
                or before["capture_id"] != current_observation.current_capture.capture_id
                or identity["window_handle"] != payload["target_window_handle"]
                or identity["process_id"] != payload["target_process_id"]
                or identity["window_rect"][2:] != [viewport["width"], viewport["height"]]
                or not (x <= bbox["x"] and y <= bbox["y"] and bbox["x"] + bbox["w"] <= x + width and bbox["y"] + bbox["h"] <= y + height)):
            raise ValueError("text field expectation differs from grounded preview binding")
    _validate_cross_layer_binding(
        payload,
        workflow,
        current_observation,
        review_selection,
        grounding_preview,
    )
    expected_sha = _content_sha(payload)
    if (
        not isinstance(payload.get("content_sha256"), str)
        or not _SHA256_RE.fullmatch(payload["content_sha256"])
        or payload["content_sha256"] != expected_sha
    ):
        raise ValueError("grounded action preview content hash is invalid")
    return payload


@dataclass(frozen=True, slots=True)
class GroundedActionPreview:
    """仅持有规范字节；返回副本不能改变已准备的人审事实。"""

    _canonical_json: bytes

    def __post_init__(self) -> None:
        if type(self._canonical_json) is not bytes:
            raise ValueError("grounded action preview bytes are invalid")
        try:
            decoded = json.loads(self._canonical_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("grounded action preview bytes are invalid") from exc
        payload = _validated_payload(decoded)
        if self._canonical_json != _canonical_bytes(payload):
            raise ValueError("grounded action preview bytes are not canonical")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GroundedActionPreview":
        payload = _validated_payload(value)
        return cls(_canonical_bytes(payload))

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self._canonical_json.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("grounded action preview bytes are invalid")
        return value
