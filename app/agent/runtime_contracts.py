"""Portfolio v1 Agent/Runtime public contracts.

这些合同只传递语义身份、不可变 lineage 和结果状态。它们不包含坐标、
不授予执行权，也不实现 Session、Gate、Controller 或桌面输入。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


StableId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
OpaqueRef = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Description = Annotated[str, Field(min_length=1, max_length=512)]

SemanticActionV1 = Literal[
    "open_detail",
    "open_apply_flow",
    "back",
    "close_modal",
    "safe_stop",
]
RuntimeOutcomeV1 = Literal[
    "VERIFIED",
    "BLOCKED",
    "SAFE_STOP",
    "NEEDS_REVIEW",
    "EXECUTION_FAILED",
    "VERIFICATION_FAILED",
    "INDETERMINATE",
]
RuntimeReasonCodeV1 = Literal[
    "none",
    "policy_blocked",
    "human_confirmation_required",
    "current_state_unresolved",
    "current_state_ambiguous",
    "stop_boundary",
    "capture_lineage_mismatch",
    "stale_candidate",
    "grounding_ambiguous",
    "target_unresolved",
    "pre_click_rejected",
    "foreground_window_changed",
    "target_occluded",
    "backend_not_started",
    "backend_failed",
    "backend_result_lost",
    "post_capture_not_new",
    "post_action_failure",
    "destination_mismatch",
    "safe_stop_boundary",
    "needs_human_review",
]

_PROHIBITED_KEYS = {
    "bbox",
    "bounding_box",
    "click_point",
    "clickpoint",
    "point",
    "coordinates",
    "source_bbox",
    "expected_bbox",
    "expected_point",
    "viewport_size",
    "window_rect",
    "hwnd",
    "transform",
    "screen_point",
    "target_point",
    "parameters",
    "metadata",
    "command",
    "script",
    "tool_call",
    "backend_command",
    "skip_gate",
    "bypass_gate",
    "gate_allowed",
    "approved_to_click",
    "execute",
    "dispatch",
    "authorization",
    "confirmation",
    "human_confirmation",
}
_RFC3339_UTC_PATTERN = (
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_STRUCTURAL_SCHEMA_COMMENT = (
    "Closed structural transport schema. Pydantic validators are authoritative "
    "for cross-field semantics."
)
_BLOCKED_REASON_CODES = {
    "policy_blocked",
    "capture_lineage_mismatch",
    "stale_candidate",
    "grounding_ambiguous",
    "target_unresolved",
    "pre_click_rejected",
    "foreground_window_changed",
    "target_occluded",
}
_NON_DISPATCH_SAFE_STOP_REASON_CODES = {
    "current_state_unresolved",
    "current_state_ambiguous",
    "stop_boundary",
    "safe_stop_boundary",
}
_DISPATCHED_SAFE_STOP_REASON_CODES = {"stop_boundary", "safe_stop_boundary"}


def _normalized_key(value: object) -> str:
    return str(value).replace("-", "_").casefold()


def _reject_prohibited_keys(value: object, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normalized_key(key)
            if normalized in _PROHIBITED_KEYS:
                raise ValueError(f"prohibited runtime authority field: {path}.{key}")
            _reject_prohibited_keys(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_prohibited_keys(child, path=f"{path}[{index}]")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class _StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_authority_injection(cls, value: object) -> object:
        _reject_prohibited_keys(value)
        return value


class WorkflowRefV1(_StrictContractModel):
    workflow_id: StableId
    asset_id: StableId
    asset_content_sha256: Sha256
    source_workflow_sha256: Sha256
    reviewed_revision_hash: Sha256


class AgentCaptureRefV1(_StrictContractModel):
    capture_id: StableId
    screenshot_sha256: Sha256
    evidence_ref: OpaqueRef


class AgentStateMatchV1(_StrictContractModel):
    status: Literal["matched", "ambiguous", "unknown", "stop_boundary"]
    state_id: StableId | None
    state_availability: Literal["reviewed", "stop_boundary"] | None
    resolution_sha256: Sha256 | None

    @model_validator(mode="after")
    def _validate_state_shape(self) -> "AgentStateMatchV1":
        if self.status == "matched":
            _require(self.state_id is not None, "matched state requires state_id")
            _require(
                self.state_availability == "reviewed",
                "matched state must be reviewed",
            )
            _require(
                self.resolution_sha256 is not None,
                "matched state requires resolution_sha256",
            )
        elif self.status == "stop_boundary":
            _require(self.state_id is not None, "stop boundary requires state_id")
            _require(
                self.state_availability == "stop_boundary",
                "stop boundary requires stop_boundary availability",
            )
            _require(
                self.resolution_sha256 is not None,
                "stop boundary requires resolution_sha256",
            )
        else:
            _require(self.state_id is None, "unresolved state must not expose state_id")
            _require(
                self.state_availability is None,
                "unresolved state must not expose availability",
            )
            _require(
                self.resolution_sha256 is None,
                "unresolved state must not expose resolution_sha256",
            )
        return self


class AgentAvailableActionV1(_StrictContractModel):
    action_id: StableId
    semantic_action: SemanticActionV1
    description: Description
    target_state_id: StableId | None
    risk_level: Literal["low", "medium", "high"]
    requires_user_confirmation: bool

    @field_validator("description")
    @classmethod
    def _normalized_description(cls, value: str) -> str:
        if value != " ".join(value.split()):
            raise ValueError("description must be normalized single-line text")
        return value

    @model_validator(mode="after")
    def _validate_action_shape(self) -> "AgentAvailableActionV1":
        if self.semantic_action == "safe_stop":
            _require(
                self.action_id == "runtime.safe_stop",
                "safe_stop action_id must be runtime.safe_stop",
            )
            _require(self.target_state_id is None, "safe_stop has no target state")
            _require(self.risk_level == "low", "safe_stop risk must be low")
            _require(
                self.requires_user_confirmation is False,
                "safe_stop cannot require confirmation",
            )
        else:
            _require(
                self.target_state_id is not None,
                "non-safe action requires target_state_id",
            )
        if self.semantic_action == "open_apply_flow":
            _require(
                self.requires_user_confirmation is True,
                "open_apply_flow requires user confirmation",
            )
            _require(
                self.risk_level in {"medium", "high"},
                "open_apply_flow risk must be medium or high",
            )
        return self


class AgentSafeStopBoundaryV1(_StrictContractModel):
    required: bool
    reason_code: Literal[
        "none",
        "state_ambiguous",
        "state_unknown",
        "stop_boundary",
        "no_available_action",
        "policy_blocked",
        "human_review_required",
    ]

    @model_validator(mode="after")
    def _validate_reason(self) -> "AgentSafeStopBoundaryV1":
        _require(
            self.required == (self.reason_code != "none"),
            "safe-stop required flag and reason must agree",
        )
        return self


class AgentObservationV1(_StrictContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        json_schema_extra={"$comment": _STRUCTURAL_SCHEMA_COMMENT},
    )

    contract_version: Literal["agent_observation_v1"]
    observation_id: StableId
    session_id: StableId
    workflow: WorkflowRefV1
    state_resolution_ref: OpaqueRef
    current_capture: AgentCaptureRefV1
    state: AgentStateMatchV1
    available_actions: Annotated[
        list[AgentAvailableActionV1],
        Field(min_length=1, max_length=32),
    ]
    safe_stop: AgentSafeStopBoundaryV1
    artifact_is_authorization: Literal[False]

    @model_validator(mode="after")
    def _validate_projection(self) -> "AgentObservationV1":
        action_ids = [item.action_id for item in self.available_actions]
        _require(len(action_ids) == len(set(action_ids)), "action_id must be unique")
        safe_actions = [
            item for item in self.available_actions if item.semantic_action == "safe_stop"
        ]
        _require(len(safe_actions) == 1, "exactly one safe_stop action is required")

        non_actionable_state = self.state.status in {
            "ambiguous",
            "unknown",
            "stop_boundary",
        }
        if non_actionable_state:
            _require(self.safe_stop.required, "non-actionable state requires safe stop")
        if self.safe_stop.required:
            _require(
                action_ids == ["runtime.safe_stop"],
                "safe-stop boundary exposes only runtime.safe_stop",
            )
        else:
            _require(
                self.state.status == "matched",
                "actionable observation requires a matched state",
            )
            _require(
                any(item.semantic_action != "safe_stop" for item in self.available_actions),
                "actionable observation requires a semantic action",
            )
        return self


class AgentIntentV1(_StrictContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        json_schema_extra={"$comment": _STRUCTURAL_SCHEMA_COMMENT},
    )

    contract_version: Literal["agent_intent_v1"]
    intent_id: StableId
    session_id: StableId
    observation_id: StableId
    workflow: WorkflowRefV1
    action_id: StableId


class RuntimeReceiptActionV1(_StrictContractModel):
    action_id: StableId
    semantic_action: SemanticActionV1


class RuntimeReceiptEvidenceV1(_StrictContractModel):
    state_resolution_ref: OpaqueRef
    selection_ref: OpaqueRef | None
    candidate_ref: OpaqueRef | None
    gate_decision_ref: OpaqueRef | None
    backend_receipt_ref: OpaqueRef | None
    verification_ref: OpaqueRef | None
    trace_refs: Annotated[list[OpaqueRef], Field(min_length=1, max_length=32)]

    @field_validator("trace_refs")
    @classmethod
    def _unique_trace_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("trace_refs must be unique")
        return value


class RuntimeReceiptSafeStopV1(_StrictContractModel):
    required: bool
    reason_code: RuntimeReasonCodeV1

    @model_validator(mode="after")
    def _validate_reason(self) -> "RuntimeReceiptSafeStopV1":
        _require(
            self.required == (self.reason_code != "none"),
            "safe-stop required flag and reason must agree",
        )
        return self


class RuntimeResultReceiptV1(_StrictContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        json_schema_extra={"$comment": _STRUCTURAL_SCHEMA_COMMENT},
    )

    contract_version: Literal["runtime_result_receipt_v1"]
    receipt_id: StableId
    issued_at: Annotated[
        str,
        Field(min_length=20, max_length=32, pattern=_RFC3339_UTC_PATTERN),
    ]
    session_id: StableId
    observation_id: StableId
    intent_id: StableId
    workflow: WorkflowRefV1
    action: RuntimeReceiptActionV1
    outcome: RuntimeOutcomeV1
    reason_code: RuntimeReasonCodeV1
    attempt_count: Literal[0, 1]
    gate_status: Literal["not_evaluated", "allowed", "blocked"]
    dispatch_status: Literal["not_started", "dispatched", "indeterminate"]
    effect_status: Literal[
        "not_evaluated",
        "verified",
        "not_verified",
        "indeterminate",
    ]
    destination_status: Literal[
        "not_evaluated",
        "verified",
        "not_verified",
        "indeterminate",
    ]
    evidence: RuntimeReceiptEvidenceV1
    next_observation_id: StableId | None
    safe_stop: RuntimeReceiptSafeStopV1
    artifact_is_authorization: Literal[False]

    @field_validator("issued_at")
    @classmethod
    def _utc_rfc3339(cls, value: str) -> str:
        if not re.fullmatch(_RFC3339_UTC_PATTERN, value):
            raise ValueError("issued_at must be an RFC3339 UTC string ending in Z")
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
        if parsed.tzinfo != timezone.utc:
            raise ValueError("issued_at must use UTC")
        return value

    @model_validator(mode="after")
    def _validate_outcome_matrix(self) -> "RuntimeResultReceiptV1":
        _require(
            self.safe_stop.reason_code == self.reason_code,
            "safe-stop reason must match outcome reason",
        )
        if self.outcome == "VERIFIED":
            self._require_verified()
        elif self.outcome == "BLOCKED":
            self._require_blocked()
        elif self.outcome == "SAFE_STOP":
            self._require_safe_stop()
        elif self.outcome == "NEEDS_REVIEW":
            self._require_needs_review()
        elif self.outcome == "EXECUTION_FAILED":
            self._require_execution_failed()
        elif self.outcome == "VERIFICATION_FAILED":
            self._require_verification_failed()
        else:
            self._require_indeterminate()
        return self

    def _require_common_execution_refs(self) -> None:
        _require(self.evidence.selection_ref is not None, "selection_ref is required")
        _require(self.evidence.candidate_ref is not None, "candidate_ref is required")
        _require(self.evidence.gate_decision_ref is not None, "gate_decision_ref is required")

    def _require_verified(self) -> None:
        _require(self.reason_code == "none", "VERIFIED reason must be none")
        _require(self.attempt_count == 1, "VERIFIED requires one attempt")
        _require(self.gate_status == "allowed", "VERIFIED requires allowed Gate")
        _require(self.dispatch_status == "dispatched", "VERIFIED requires dispatch")
        _require(self.effect_status == "verified", "VERIFIED requires effect verification")
        _require(self.destination_status == "verified", "VERIFIED requires destination verification")
        self._require_common_execution_refs()
        _require(self.evidence.backend_receipt_ref is not None, "backend_receipt_ref is required")
        _require(self.evidence.verification_ref is not None, "verification_ref is required")
        _require(self.next_observation_id is not None, "VERIFIED requires next observation")
        _require(not self.safe_stop.required, "VERIFIED cannot require safe stop")

    def _require_blocked(self) -> None:
        _require(
            self.reason_code in _BLOCKED_REASON_CODES,
            "BLOCKED reason must describe a pre-dispatch block",
        )
        _require(self.attempt_count == 0, "BLOCKED cannot consume an attempt")
        _require(self.gate_status in {"not_evaluated", "blocked"}, "BLOCKED Gate state is invalid")
        _require(self.dispatch_status == "not_started", "BLOCKED cannot dispatch")
        _require(self.effect_status == "not_evaluated", "BLOCKED cannot verify effect")
        _require(self.destination_status == "not_evaluated", "BLOCKED cannot verify destination")
        if self.gate_status == "blocked":
            _require(self.evidence.gate_decision_ref is not None, "blocked Gate requires a ref")
        _require(self.evidence.backend_receipt_ref is None, "BLOCKED cannot have backend receipt")
        _require(self.evidence.verification_ref is None, "BLOCKED cannot have verification ref")
        _require(self.next_observation_id is None, "BLOCKED cannot advance observation")
        _require(self.safe_stop.required, "BLOCKED requires safe stop")

    def _require_safe_stop(self) -> None:
        _require(self.reason_code != "none", "SAFE_STOP requires a reason")
        _require(self.safe_stop.required, "SAFE_STOP must require safe stop")
        if self.attempt_count == 0:
            _require(
                self.reason_code in _NON_DISPATCH_SAFE_STOP_REASON_CODES,
                "non-dispatch SAFE_STOP reason is invalid",
            )
            _require(
                self.action.semantic_action == "safe_stop",
                "non-dispatch SAFE_STOP requires synthetic safe_stop",
            )
            _require(self.gate_status == "not_evaluated", "non-dispatch SAFE_STOP cannot evaluate Gate")
            _require(self.dispatch_status == "not_started", "non-dispatch SAFE_STOP cannot dispatch")
            _require(self.effect_status == "not_evaluated", "non-dispatch SAFE_STOP has no effect")
            _require(self.destination_status == "not_evaluated", "non-dispatch SAFE_STOP has no destination")
            _require(self.evidence.backend_receipt_ref is None, "non-dispatch SAFE_STOP has no backend receipt")
            _require(self.evidence.verification_ref is None, "non-dispatch SAFE_STOP has no verification")
            _require(self.next_observation_id is None, "non-dispatch SAFE_STOP cannot advance")
        else:
            _require(
                self.reason_code in _DISPATCHED_SAFE_STOP_REASON_CODES,
                "dispatched SAFE_STOP reason must be a stop boundary",
            )
            _require(
                self.action.semantic_action != "safe_stop",
                "synthetic safe_stop is never dispatched",
            )
            _require(self.gate_status == "allowed", "dispatched SAFE_STOP requires allowed Gate")
            _require(self.dispatch_status == "dispatched", "dispatched SAFE_STOP requires dispatch")
            _require(self.effect_status == "verified", "dispatched SAFE_STOP requires verified effect")
            _require(self.destination_status == "verified", "dispatched SAFE_STOP requires verified destination")
            self._require_common_execution_refs()
            _require(self.evidence.backend_receipt_ref is not None, "backend_receipt_ref is required")
            _require(self.evidence.verification_ref is not None, "verification_ref is required")
            _require(self.next_observation_id is not None, "dispatched SAFE_STOP requires next observation")

    def _require_needs_review(self) -> None:
        _require(
            self.reason_code in {"human_confirmation_required", "needs_human_review"},
            "NEEDS_REVIEW reason is invalid",
        )
        _require(self.attempt_count == 0, "NEEDS_REVIEW cannot consume an attempt")
        _require(self.gate_status == "not_evaluated", "NEEDS_REVIEW cannot evaluate Gate")
        _require(self.dispatch_status == "not_started", "NEEDS_REVIEW cannot dispatch")
        _require(self.effect_status == "not_evaluated", "NEEDS_REVIEW has no effect")
        _require(self.destination_status == "not_evaluated", "NEEDS_REVIEW has no destination")
        _require(self.evidence.backend_receipt_ref is None, "NEEDS_REVIEW has no backend receipt")
        _require(self.evidence.verification_ref is None, "NEEDS_REVIEW has no verification")
        _require(self.next_observation_id is None, "NEEDS_REVIEW cannot advance")
        _require(self.safe_stop.required, "NEEDS_REVIEW requires safe stop")

    def _require_execution_failed(self) -> None:
        _require(
            self.reason_code in {"backend_not_started", "backend_failed"},
            "EXECUTION_FAILED reason is invalid",
        )
        _require(self.attempt_count == 1, "EXECUTION_FAILED requires one attempt")
        _require(self.gate_status == "allowed", "EXECUTION_FAILED requires allowed Gate")
        _require(self.dispatch_status == "not_started", "EXECUTION_FAILED must confirm no dispatch")
        _require(self.effect_status == "not_evaluated", "EXECUTION_FAILED has no effect")
        _require(self.destination_status == "not_evaluated", "EXECUTION_FAILED has no destination")
        self._require_common_execution_refs()
        _require(self.evidence.backend_receipt_ref is not None, "backend_receipt_ref is required")
        _require(self.evidence.verification_ref is None, "EXECUTION_FAILED has no verification")
        _require(self.next_observation_id is None, "EXECUTION_FAILED cannot advance")
        _require(self.safe_stop.required, "EXECUTION_FAILED requires safe stop")

    def _require_verification_failed(self) -> None:
        _require(
            self.reason_code in {"post_capture_not_new", "post_action_failure", "destination_mismatch"},
            "VERIFICATION_FAILED reason is invalid",
        )
        _require(self.attempt_count == 1, "VERIFICATION_FAILED requires one attempt")
        _require(self.gate_status == "allowed", "VERIFICATION_FAILED requires allowed Gate")
        _require(self.dispatch_status == "dispatched", "VERIFICATION_FAILED requires dispatch")
        _require(
            "not_verified" in {self.effect_status, self.destination_status},
            "VERIFICATION_FAILED requires an explicit failed verification",
        )
        _require(
            "indeterminate" not in {self.effect_status, self.destination_status},
            "VERIFICATION_FAILED cannot be indeterminate",
        )
        self._require_common_execution_refs()
        _require(self.evidence.backend_receipt_ref is not None, "backend_receipt_ref is required")
        _require(self.evidence.verification_ref is not None, "verification_ref is required")
        _require(self.next_observation_id is None, "VERIFICATION_FAILED cannot advance")
        _require(self.safe_stop.required, "VERIFICATION_FAILED requires safe stop")

    def _require_indeterminate(self) -> None:
        _require(self.reason_code == "backend_result_lost", "INDETERMINATE reason is invalid")
        _require(self.attempt_count == 1, "INDETERMINATE requires one attempt")
        _require(self.gate_status == "allowed", "INDETERMINATE requires allowed Gate")
        _require(self.dispatch_status == "indeterminate", "dispatch must be indeterminate")
        _require(self.effect_status == "indeterminate", "effect must be indeterminate")
        _require(self.destination_status == "indeterminate", "destination must be indeterminate")
        self._require_common_execution_refs()
        _require(self.evidence.backend_receipt_ref is not None, "backend_receipt_ref is required")
        _require(self.next_observation_id is None, "INDETERMINATE cannot advance")
        _require(self.safe_stop.required, "INDETERMINATE requires safe stop")


def validate_agent_observation_v1(
    payload: Mapping[str, object],
) -> AgentObservationV1:
    """严格验证 Runtime 发给 Agent 的 geometry-free Observation。"""

    return AgentObservationV1.model_validate(payload)


def validate_agent_intent_v1(
    payload: Mapping[str, object],
    *,
    observation: AgentObservationV1,
) -> AgentIntentV1:
    """验证 Intent 严格绑定指定 Observation 的一个 semantic action ID。"""

    intent = AgentIntentV1.model_validate(payload)
    _require(intent.session_id == observation.session_id, "intent session mismatch")
    _require(intent.observation_id == observation.observation_id, "intent observation mismatch")
    _require(intent.workflow == observation.workflow, "intent workflow revision mismatch")
    action_ids = {item.action_id for item in observation.available_actions}
    _require(intent.action_id in action_ids, "intent action is not available")
    if observation.safe_stop.required:
        _require(intent.action_id == "runtime.safe_stop", "safe-stop boundary rejects other actions")
    return intent


def validate_runtime_result_receipt_v1(
    payload: Mapping[str, object],
    *,
    observation: AgentObservationV1,
    intent: AgentIntentV1,
) -> RuntimeResultReceiptV1:
    """验证 Receipt lineage、选中动作和 fail-closed outcome matrix。"""

    receipt = RuntimeResultReceiptV1.model_validate(payload)
    _require(receipt.session_id == observation.session_id, "receipt session mismatch")
    _require(receipt.observation_id == observation.observation_id, "receipt observation mismatch")
    _require(receipt.intent_id == intent.intent_id, "receipt intent mismatch")
    _require(receipt.workflow == observation.workflow == intent.workflow, "receipt workflow revision mismatch")
    _require(
        receipt.evidence.state_resolution_ref == observation.state_resolution_ref,
        "receipt state resolution mismatch",
    )
    selected = next(
        (item for item in observation.available_actions if item.action_id == intent.action_id),
        None,
    )
    _require(selected is not None, "receipt intent action is unavailable")
    _require(receipt.action.action_id == intent.action_id, "receipt action mismatch")
    _require(
        receipt.action.semantic_action == selected.semantic_action,
        "receipt semantic action mismatch",
    )
    if receipt.outcome == "VERIFIED":
        _require(selected.semantic_action != "safe_stop", "safe_stop cannot be VERIFIED")
    if receipt.outcome == "SAFE_STOP" and receipt.attempt_count == 0:
        _require(selected.semantic_action == "safe_stop", "non-dispatch SAFE_STOP requires safe_stop action")
    return receipt


__all__ = [
    "AgentIntentV1",
    "AgentObservationV1",
    "RuntimeResultReceiptV1",
    "validate_agent_intent_v1",
    "validate_agent_observation_v1",
    "validate_runtime_result_receipt_v1",
]
