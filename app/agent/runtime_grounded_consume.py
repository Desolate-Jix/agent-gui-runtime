"""Grounded 批准后的 fresh consume 冻结记录与纯完整性校验。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any, Literal

from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.action_parameters import reviewed_action_parameter_fields
from app.agent.native_identity import validate_native_identity_fact
from app.agent.runtime_contracts import AgentObservationV1, validate_agent_observation_v1
from app.agent.reviewed_workflow_replay import (
    _GATE_KEYS,
    _GROUNDING_KEYS,
    _SELECTION_KEYS,
    _capture_lineage,
    _selection_hash,
    current_observation_contract_matches,
)


CONSUME_CONTRACT_VERSION = "runtime_grounded_confirmation_consume_started_v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_RECORD_KEYS = {
    "store_contract_version", "claim_id", "claim_content_sha256", "phase",
    "confirmation_id", "request_content_sha256", "decision_content_sha256",
    "consume_attempt_id", "owner_instance_id", "started_at", "fresh_preview",
    "current_observation", "selection", "grounding", "gate", "gate_decision_ref",
    "target_process_id", "target_window_handle", "artifact_is_authorization",
    "grants_action_authority", "consume_binding_sha256",
}


class RuntimeGroundedConsumeError(ValueError):
    pass


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeGroundedConsumeError(f"grounded consume serialization failed: {exc}") from exc


def content_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RuntimeGroundedConsumeError("grounded consume time is invalid")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise RuntimeGroundedConsumeError("grounded consume time is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise RuntimeGroundedConsumeError("grounded consume time is invalid")
    return parsed


def _clone_mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeGroundedConsumeError(f"grounded consume {label} is invalid")
    try:
        cloned = json.loads(canonical_json_bytes(value).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeGroundedConsumeError(f"grounded consume {label} is invalid") from exc
    if not isinstance(cloned, dict):
        raise RuntimeGroundedConsumeError(f"grounded consume {label} is invalid")
    return cloned


def _without_fresh_ids(preview: GroundedActionPreview) -> dict[str, Any]:
    value = preview.to_dict()
    current = value["current_observation"]
    current["observation_id"] = "<fresh-observation>"
    current["state_resolution_ref"] = "<fresh-state-resolution>"
    current["current_capture"]["capture_id"] = "<fresh-capture>"
    current["current_capture"]["evidence_ref"] = "<fresh-capture-ref>"
    current["state"]["resolution_sha256"] = "<derived>"
    current["evidence_refs"] = []
    selection = value["review_selection"]
    selection["capture_lineage"]["capture_id"] = "<fresh-capture>"
    selection["review_selection_sha256"] = "<derived>"
    selection["selection_sha256"] = "<derived>"
    grounding = value["grounding_preview"]
    grounding["capture_lineage"]["capture_id"] = "<fresh-capture>"
    grounding["review_selection_sha256"] = "<derived>"
    grounding["gate_selection_sha256"] = "<derived>"
    grounding["grounding_evidence_refs"] = []
    grounding["gate_evidence_refs"] = []
    grounding["gate_decision_ref"] = "<fresh-gate-ref>"
    grounding["evidence_refs"] = []
    grounding["preview_sha256"] = "<derived>"
    if value["review_selection"].get("semantic_action") == "fill_field":
        expectation = value.get("text_field_expectation_ref")
        if isinstance(expectation, Mapping) and isinstance(expectation.get("before"), Mapping):
            before = expectation["before"]
            before["capture_id"] = "<fresh-text-capture>"
            before["read_id"] = "<fresh-text-read>"
            before["observed_at_ns"] = "<fresh-text-time>"
            if (
                value["review_selection"].get("text_parameters_ref", {}).get(
                    "clear_existing"
                )
                is True
            ):
                before["selection"] = "<fresh-text-selection>"
    value["content_sha256"] = "<derived>"
    return value


def _validated_text_field_expectation(
    preview: GroundedActionPreview,
) -> dict[str, Any]:
    """将填写预览的无原文期望引用绑定到已审核参数。"""
    value = preview.to_dict()
    selection = value["review_selection"]
    if selection.get("semantic_action") != "fill_field":
        if "text_field_expectation_ref" in value:
            raise RuntimeGroundedConsumeError(
                "non-fill grounded consume preview cannot carry text field expectation"
            )
        return {}
    try:
        from app.agent.text_field_evidence import (
            validate_text_field_expectation_reference,
        )

        reference = validate_text_field_expectation_reference(
            value.get("text_field_expectation_ref"),
            selection.get("text_parameters_ref"),
        )
    except (ImportError, TypeError, ValueError) as exc:
        raise RuntimeGroundedConsumeError(
            "grounded consume text field expectation is invalid"
        ) from exc
    if reference.get("text_execution_ref") != value.get("text_execution_ref"):
        raise RuntimeGroundedConsumeError(
            "grounded consume text execution reference mismatch"
        )
    return reference


def _validate_fresh_text_field_expectation(
    approved_preview: GroundedActionPreview,
    fresh_preview: GroundedActionPreview,
    *,
    fresh_capture_id: object,
) -> None:
    """只允许填写前读取代际前进，不允许改变目标、原值摘要或执行声明。"""
    approved = _validated_text_field_expectation(approved_preview)
    fresh = _validated_text_field_expectation(fresh_preview)
    if not approved and not fresh:
        return
    if not approved or not fresh:
        raise RuntimeGroundedConsumeError("grounded consume text field expectation is missing")
    old_before = approved["before"]
    new_before = fresh["before"]
    if (
        new_before.get("capture_id") != fresh_capture_id
        or new_before.get("read_id") == old_before.get("read_id")
        or type(new_before.get("observed_at_ns")) is not int
        or type(old_before.get("observed_at_ns")) is not int
        or new_before["observed_at_ns"] <= old_before["observed_at_ns"]
    ):
        raise RuntimeGroundedConsumeError(
            "grounded consume text field read is not fresh"
        )
    for key in (
        "identity",
        "source",
        "value_sha256",
        "value_length",
    ):
        if new_before.get(key) != old_before.get(key):
            raise RuntimeGroundedConsumeError(
                "grounded consume text field expectation drifted"
            )
    if (
        fresh.get("text_execution_ref") != approved.get("text_execution_ref")
        or fresh.get("expected_value_sha256")
        != approved.get("expected_value_sha256")
        or fresh.get("expected_value_length")
        != approved.get("expected_value_length")
    ):
        raise RuntimeGroundedConsumeError(
            "grounded consume text field expectation drifted"
        )
    clear_existing = approved_preview.to_dict()["review_selection"][
        "text_parameters_ref"
    ].get("clear_existing")
    if clear_existing is not True and new_before.get("selection") != old_before.get(
        "selection"
    ):
        raise RuntimeGroundedConsumeError(
            "grounded consume text field selection drifted"
        )


def validate_fresh_preview(
    approved_preview: GroundedActionPreview,
    fresh_preview: GroundedActionPreview,
) -> dict[str, Any]:
    """仅允许 observation/capture/evidence refs 及其派生 hash 更新。"""
    if not isinstance(approved_preview, GroundedActionPreview) or not isinstance(
        fresh_preview, GroundedActionPreview
    ):
        raise RuntimeGroundedConsumeError("grounded consume preview is invalid")
    before = approved_preview.to_dict()
    current = fresh_preview.to_dict()
    old_capture = before["current_observation"]["current_capture"]["capture_id"]
    new_capture = current["current_observation"]["current_capture"]["capture_id"]
    if not isinstance(new_capture, str) or not new_capture or new_capture == old_capture:
        raise RuntimeGroundedConsumeError("grounded consume requires a new capture")
    _validate_fresh_text_field_expectation(
        approved_preview,
        fresh_preview,
        fresh_capture_id=new_capture,
    )
    if _without_fresh_ids(approved_preview) != _without_fresh_ids(fresh_preview):
        raise RuntimeGroundedConsumeError("grounded consume fresh preview drifted")
    return current


@dataclass(frozen=True, slots=True)
class RuntimeGroundedConsumeSnapshot:
    consume_attempt_id: str
    content_sha256: str
    confirmation_id: str
    request_content_sha256: str
    decision_content_sha256: str
    owner_instance_id: str
    started_at: str
    gate_decision_ref: str
    target_process_id: int
    target_window_handle: int
    _fresh_preview_json: bytes = field(repr=False)
    _current_observation_json: bytes = field(repr=False)
    _selection_json: bytes = field(repr=False)
    _grounding_json: bytes = field(repr=False)
    _gate_json: bytes = field(repr=False)
    grants_action_authority: Literal[False] = False
    artifact_is_authorization: Literal[False] = False

    @property
    def evidence_ref(self) -> str:
        return f"grounded-consume:{self.content_sha256}"

    @staticmethod
    def _mapping(raw: bytes) -> dict[str, Any]:
        value = json.loads(raw.decode("utf-8"))
        assert isinstance(value, dict)
        return value

    @property
    def fresh_preview(self) -> GroundedActionPreview:
        return GroundedActionPreview.from_dict(self._mapping(self._fresh_preview_json))

    @property
    def current_observation(self) -> dict[str, Any]:
        return self._mapping(self._current_observation_json)

    @property
    def selection(self) -> dict[str, Any]:
        return self._mapping(self._selection_json)

    @property
    def grounding(self) -> dict[str, Any]:
        return self._mapping(self._grounding_json)

    @property
    def gate(self) -> dict[str, Any]:
        return self._mapping(self._gate_json)


def build_consume_record(
    *, base: Mapping[str, Any], request: Mapping[str, Any], request_raw: bytes,
    decision_raw: bytes, fresh_preview: GroundedActionPreview,
    current_observation: Mapping[str, Any], selection: Mapping[str, Any],
    grounding: Mapping[str, Any], execution_gate: Mapping[str, Any],
    gate_decision_ref: str, target_process_id: int, owner_instance_id: str,
    consume_attempt_id: str, started_at: datetime,
) -> dict[str, Any]:
    marker: dict[str, Any] = {
        "store_contract_version": CONSUME_CONTRACT_VERSION,
        "claim_id": base["claim_id"],
        "claim_content_sha256": base["claim_content_sha256"],
        "phase": "grounded_confirmation_consume_started",
        "confirmation_id": request["confirmation_id"],
        "request_content_sha256": hashlib.sha256(request_raw).hexdigest(),
        "decision_content_sha256": hashlib.sha256(decision_raw).hexdigest(),
        "consume_attempt_id": consume_attempt_id,
        "owner_instance_id": owner_instance_id,
        "started_at": started_at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fresh_preview": fresh_preview.to_dict(),
        "current_observation": _clone_mapping(current_observation, label="current observation"),
        "selection": _clone_mapping(selection, label="selection"),
        "grounding": _clone_mapping(grounding, label="grounding"),
        "gate": _clone_mapping(execution_gate, label="execution gate"),
        "gate_decision_ref": gate_decision_ref,
        "target_process_id": target_process_id,
        "target_window_handle": base["server_binding"].target_window_handle,
        "artifact_is_authorization": False,
        "grants_action_authority": False,
    }
    marker["consume_binding_sha256"] = content_sha256(marker)
    return marker


def validate_consume_record(
    value: Mapping[str, Any], *, base: Mapping[str, Any], request: Mapping[str, Any],
    request_raw: bytes, decision: Mapping[str, Any] | None, decision_raw: bytes | None,
    approved_preview: GroundedActionPreview,
) -> tuple[dict[str, Any], RuntimeGroundedConsumeSnapshot]:
    marker = _clone_mapping(value, label="record")
    digest = marker.pop("consume_binding_sha256", None)
    marker["consume_binding_sha256"] = digest
    if (
        set(marker) != _RECORD_KEYS
        or marker.get("store_contract_version") != CONSUME_CONTRACT_VERSION
        or marker.get("phase") != "grounded_confirmation_consume_started"
        or marker.get("claim_id") != base["claim_id"]
        or marker.get("claim_content_sha256") != base["claim_content_sha256"]
        or marker.get("confirmation_id") != request["confirmation_id"]
        or marker.get("request_content_sha256") != hashlib.sha256(request_raw).hexdigest()
        or decision is None or decision.get("decision") != "approved"
        or decision_raw is None
        or marker.get("decision_content_sha256") != hashlib.sha256(decision_raw).hexdigest()
        or marker.get("owner_instance_id") != request["owner_instance_id"]
        or marker.get("artifact_is_authorization") is not False
        or marker.get("grants_action_authority") is not False
        or not isinstance(digest, str) or _SHA.fullmatch(digest) is None
        or digest != content_sha256({k: v for k, v in marker.items() if k != "consume_binding_sha256"})
    ):
        raise RuntimeGroundedConsumeError("invalid or tampered grounded consume record")
    attempt = marker.get("consume_attempt_id")
    gate_ref = marker.get("gate_decision_ref")
    if (
        not isinstance(attempt, str) or not attempt.startswith("grounded-consume-attempt.")
        or _ID.fullmatch(attempt) is None
        or not isinstance(gate_ref, str) or _ID.fullmatch(gate_ref) is None
        or type(marker.get("target_process_id")) is not int
        or marker["target_process_id"] <= 0
        or type(marker.get("target_window_handle")) is not int
        or marker["target_window_handle"] != base["server_binding"].target_window_handle
    ):
        raise RuntimeGroundedConsumeError("invalid grounded consume identity")
    started = _parse_utc(marker.get("started_at"))
    decided = _parse_utc(decision.get("decided_at"))
    expires = _parse_utc(request.get("expires_at"))
    if started < decided or started >= expires:
        raise RuntimeGroundedConsumeError("grounded consume time is invalid")
    try:
        fresh = GroundedActionPreview.from_dict(marker["fresh_preview"])
        validate_fresh_preview(approved_preview, fresh)
        current_payload = _clone_mapping(marker["current_observation"], label="current observation")
        preview_current: AgentObservationV1 = validate_agent_observation_v1(
            fresh.to_dict()["current_observation"]
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeGroundedConsumeError("grounded consume fresh preview is invalid") from exc
    selection = _clone_mapping(marker["selection"], label="selection")
    grounding = _clone_mapping(marker["grounding"], label="grounding")
    gate = _clone_mapping(marker["gate"], label="execution gate")
    try:
        selection_digest = _selection_hash(selection)
    except (TypeError, ValueError) as exc:
        raise RuntimeGroundedConsumeError("grounded consume selection is invalid") from exc
    selection_lineage = selection.get("capture_lineage")
    if not isinstance(selection_lineage, Mapping):
        raise RuntimeGroundedConsumeError("grounded consume selection lineage is invalid")
    gate_evidence_refs = gate.get("evidence_refs")
    if not isinstance(gate_evidence_refs, list) or not all(
        isinstance(item, str) and item for item in gate_evidence_refs
    ):
        raise RuntimeGroundedConsumeError("grounded consume gate evidence is invalid")
    preview_value = fresh.to_dict()
    review_selection = preview_value["review_selection"]
    review_grounding = preview_value["grounding_preview"]
    current_lineage = {
        key: current_payload.get(key)
        for key in ("capture_id", "screenshot_sha256", "viewport_size")
    }
    if _capture_lineage(current_lineage, require_exact=True) is None:
        raise RuntimeGroundedConsumeError("grounded consume current observation is invalid")
    is_native = preview_current.application.kind == "native"
    if is_native:
        from app.agent.agent_observation_adapter import _capture_evidence_ref

        # 原生事实必须与当前预览的证据摘要绑定，不能仅靠外层重算摘要替换程序实例。
        native_fact = validate_native_identity_fact(
            current_payload.get("native_identity"),
            target_window_handle=marker["target_window_handle"],
            expected_process_id=marker["target_process_id"],
        )
        if (
            native_fact is None
            or current_payload.get("origin") != ""
            or review_selection.get("canonical_origin") != ""
            or _capture_evidence_ref(preview_current.workflow.asset_content_sha256, current_payload)
            != preview_current.current_capture.evidence_ref
        ):
            raise RuntimeGroundedConsumeError("grounded consume native identity is invalid")
    anchors = current_payload.get("observed_anchor_evidence")
    if (
        not current_observation_contract_matches(current_payload, preview_current.application.kind)
        or current_payload.get("asset_id") != preview_current.workflow.asset_id
        or current_payload.get("expected_asset_content_sha256")
        != preview_current.workflow.asset_content_sha256
        or current_payload.get("origin") != review_selection.get("canonical_origin")
        or not isinstance(anchors, list)
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"anchor_id", "matched", "confidence", "evidence_ref"}
            or not isinstance(item.get("anchor_id"), str)
            or not item.get("anchor_id")
            or item.get("matched") is not True
            or isinstance(item.get("confidence"), bool)
            or not isinstance(item.get("confidence"), (int, float))
            or not math.isfinite(float(item["confidence"]))
            or not 0.0 <= float(item["confidence"]) <= 1.0
            or not isinstance(item.get("evidence_ref"), str)
            or not item.get("evidence_ref")
            for item in anchors
        )
    ):
        raise RuntimeGroundedConsumeError("grounded consume current observation is invalid")
    expected_proof_ref = "grounded-confirmation-proof:" + content_sha256(
        {
            "confirmation_id": marker["confirmation_id"],
            "request_content_sha256": marker["request_content_sha256"],
            "decision_content_sha256": marker["decision_content_sha256"],
            "fresh_preview_content_sha256": preview_value["content_sha256"],
        }
    )
    selection_shared = {
        "asset_id", "asset_content_sha256", "source_workflow_sha256",
        "reviewed_revision_hash", "canonical_origin", "transition_id",
        "source_state_id", "target_state_id", "semantic_action", "element_ref",
        "capture_lineage", "requirements", "requires_user_confirmation",
    }
    grounding_shared = {
        "asset_content_sha256", "transition_id", "source_state_id",
        "element_ref", "candidate_id",
        "confidence", "score_margin", "bbox", "click_point",
    }
    try:
        parameters = reviewed_action_parameter_fields(selection)
        semantic = selection.get("semantic_action")
        if any(
            reviewed_action_parameter_fields(item, semantic_action=semantic) != parameters
            for item in (grounding, gate)
        ):
            raise ValueError("grounded consume action parameters mismatch")
    except ValueError as exc:
        raise RuntimeGroundedConsumeError(str(exc)) from exc
    selection_shared.update(parameters)
    grounding_shared.update(parameters)
    if (
        set(selection) != _SELECTION_KEYS | parameters.keys()
        or selection.get("contract_version") != "verified_transition_selection_v1"
        or selection.get("status") != "selected"
        or selection.get("artifact_is_authorization") is not False
        or selection.get("execute_binding_enabled") is not False
        or selection.get("selection_sha256") != selection_digest
        or not all(selection.get(key) == review_selection.get(key) for key in selection_shared)
        or set(grounding) != _GROUNDING_KEYS | parameters.keys()
        or grounding.get("contract_version") != "reviewed_workflow_current_grounding_v1"
        or not all(grounding.get(key) == review_grounding.get(key) for key in grounding_shared)
        or any(
            grounding.get(key) != review_grounding.get("capture_lineage", {}).get(key)
            for key in ("capture_id", "screenshot_sha256", "viewport_size")
        )
        or set(gate) != _GATE_KEYS | parameters.keys()
        or gate.get("contract_version") != "pre_click_decision_v1"
        or gate.get("allowed") is not True
        or preview_current.session_id != base["observation"].session_id
        or preview_current.workflow != base["observation"].workflow
        or preview_current.application != base["observation"].application
        or fresh.to_dict()["target_process_id"] != marker["target_process_id"]
        or selection.get("transition_id") != base["intent"].action_id
        or selection.get("human_confirmation_evidence_ref") != expected_proof_ref
        or selection.get("capture_lineage") != fresh.to_dict()["review_selection"].get("capture_lineage")
        or _capture_lineage(selection_lineage, require_exact=True) is None
        or selection.get("capture_lineage") != current_lineage
        or grounding.get("capture_id") != current_payload["capture_id"]
        or grounding.get("candidate_current") is not True
        or grounding.get("eligible") is not True
        or gate.get("selection_sha256") != selection.get("selection_sha256")
        or gate.get("selected_candidate_id") != grounding.get("candidate_id")
        or gate.get("selected_element_id") != selection.get("element_ref")
        or gate.get("selected_click_point") != grounding.get("click_point")
        or gate_ref not in gate_evidence_refs
    ):
        raise RuntimeGroundedConsumeError("grounded consume lineage mismatch")
    raw = canonical_json_bytes(marker)
    snapshot = RuntimeGroundedConsumeSnapshot(
        consume_attempt_id=attempt,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        confirmation_id=request["confirmation_id"],
        request_content_sha256=marker["request_content_sha256"],
        decision_content_sha256=marker["decision_content_sha256"],
        owner_instance_id=marker["owner_instance_id"],
        started_at=marker["started_at"],
        gate_decision_ref=gate_ref,
        target_process_id=marker["target_process_id"],
        target_window_handle=marker["target_window_handle"],
        _fresh_preview_json=canonical_json_bytes(marker["fresh_preview"]),
        _current_observation_json=canonical_json_bytes(current_payload),
        _selection_json=canonical_json_bytes(selection),
        _grounding_json=canonical_json_bytes(grounding),
        _gate_json=canonical_json_bytes(gate),
    )
    return marker, snapshot


__all__ = [
    "CONSUME_CONTRACT_VERSION", "RuntimeGroundedConsumeError",
    "RuntimeGroundedConsumeSnapshot", "build_consume_record",
    "canonical_json_bytes", "content_sha256", "validate_consume_record",
    "validate_fresh_preview",
]
