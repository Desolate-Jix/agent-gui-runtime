"""Grounded 人审持久记录的纯校验与不可变快照。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Literal

from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.runtime_contracts import (
    AgentIntentV1,
    AgentObservationV1,
    validate_agent_observation_v1,
)


REQUEST_CONTRACT_VERSION = "runtime_grounded_confirmation_request_v1"
DECISION_CONTRACT_VERSION = "runtime_grounded_confirmation_decision_v1"
CLOSED_CONTRACT_VERSION = "runtime_grounded_confirmation_closed_v1"
GROUNDED_CONFIRMATION_TTL_SECONDS = 300
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OWNER_ID = re.compile(r"^owner\.[0-9a-f]{32}$")
_REQUEST_KEYS = {
    "store_contract_version",
    "claim_id",
    "claim_content_sha256",
    "phase",
    "confirmation_id",
    "session_id",
    "observation_id",
    "intent_id",
    "preview",
    "owner_instance_id",
    "requested_at",
    "expires_at",
    "artifact_is_authorization",
    "grants_action_authority",
    "request_binding_sha256",
}
_DECISION_KEYS = {
    "store_contract_version",
    "claim_id",
    "claim_content_sha256",
    "phase",
    "confirmation_id",
    "request_content_sha256",
    "decision",
    "decided_at",
    "artifact_is_authorization",
    "grants_action_authority",
    "decision_binding_sha256",
}
_CLOSED_KEYS = {
    "store_contract_version",
    "claim_id",
    "claim_content_sha256",
    "phase",
    "confirmation_id",
    "request_content_sha256",
    "decision_content_sha256",
    "reason_code",
    "closed_at",
    "artifact_is_authorization",
    "grants_action_authority",
    "closed_binding_sha256",
}
_REASONS = {
    "grounded_confirmation_cancelled",
    "grounded_confirmation_expired",
    "grounded_confirmation_stale",
    "grounded_confirmation_restarted",
}


class RuntimeGroundedConfirmationError(ValueError):
    """Grounded marker 结构、hash 或血缘无效。"""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeGroundedConfirmationError("grounded record serialization failed") from exc


def content_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def binding_sha256(value: Mapping[str, Any], field: str) -> str:
    return content_sha256({key: item for key, item in value.items() if key != field})


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RuntimeGroundedConfirmationError("grounded confirmation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise RuntimeGroundedConfirmationError(
            "grounded confirmation timestamp is invalid"
        ) from exc
    if parsed.tzinfo != timezone.utc or format_utc(parsed) != value:
        raise RuntimeGroundedConfirmationError("grounded confirmation timestamp is invalid")
    return parsed


def _claim_fields(base: Mapping[str, Any]) -> tuple[str, str, AgentObservationV1, AgentIntentV1]:
    claim_id = base.get("claim_id")
    claim_sha = base.get("claim_content_sha256")
    observation = base.get("observation")
    intent = base.get("intent")
    if (
        not isinstance(claim_id, str)
        or not claim_id.startswith("claim.")
        or _SHA256.fullmatch(claim_id.removeprefix("claim.")) is None
        or not isinstance(claim_sha, str)
        or _SHA256.fullmatch(claim_sha) is None
        or not isinstance(observation, AgentObservationV1)
        or not isinstance(intent, AgentIntentV1)
    ):
        raise RuntimeGroundedConfirmationError("grounded confirmation base claim is invalid")
    return claim_id, claim_sha, observation, intent


def validate_preview_binding(
    preview: GroundedActionPreview,
    *,
    base: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(preview, GroundedActionPreview):
        raise RuntimeGroundedConfirmationError("grounded confirmation preview is invalid")
    # 重新构造会再次校验完整 nested shape/hash/cross-layer binding。
    try:
        payload = preview.to_dict()
        validated = GroundedActionPreview.from_dict(payload)
        fresh = validate_agent_observation_v1(payload["current_observation"])
    except (TypeError, ValueError) as exc:
        raise RuntimeGroundedConfirmationError(
            "grounded confirmation preview is invalid or tampered"
        ) from exc
    claim_id, _claim_sha, observation, intent = _claim_fields(base)
    binding = base.get("server_binding")
    if binding is None or not hasattr(binding, "target_window_handle"):
        raise RuntimeGroundedConfirmationError("grounded confirmation base binding is invalid")
    if (
        payload["session_id"] != observation.session_id
        or payload["observation_id"] != observation.observation_id
        or payload["intent_id"] != intent.intent_id
        or payload["workflow"] != observation.workflow.model_dump(mode="json")
        or payload["target_window_handle"] != binding.target_window_handle
        or fresh.session_id != observation.session_id
        or fresh.workflow != observation.workflow
        or fresh.application != observation.application
        or claim_id.removeprefix("claim.") == ""
    ):
        raise RuntimeGroundedConfirmationError(
            "grounded confirmation preview does not match base claim"
        )
    selection = payload["review_selection"]
    initial_actions = [
        action for action in observation.available_actions if action.action_id == intent.action_id
    ]
    fresh_actions = [
        action
        for action in fresh.available_actions
        if action.action_id == selection["transition_id"]
    ]
    if (
        len(initial_actions) != 1
        or len(fresh_actions) != 1
        or selection["transition_id"] != intent.action_id
    ):
        raise RuntimeGroundedConfirmationError(
            "grounded confirmation preview does not match base claim action"
        )
    initial_action = initial_actions[0]
    fresh_action = fresh_actions[0]
    if (
        fresh_action.model_dump(mode="json")
        != initial_action.model_dump(mode="json")
        or selection["semantic_action"] != initial_action.semantic_action
        or selection["target_state_id"] != initial_action.target_state_id
        or selection["requires_user_confirmation"]
        is not initial_action.requires_user_confirmation
    ):
        raise RuntimeGroundedConfirmationError(
            "grounded confirmation preview does not match base claim action policy"
        )
    return validated.to_dict()


def build_request_record(
    *,
    base: Mapping[str, Any],
    confirmation_id: str,
    preview: GroundedActionPreview,
    owner_instance_id: str,
    requested_at: datetime,
) -> dict[str, Any]:
    claim_id, claim_sha, observation, intent = _claim_fields(base)
    preview_payload = validate_preview_binding(preview, base=base)
    record: dict[str, Any] = {
        "store_contract_version": REQUEST_CONTRACT_VERSION,
        "claim_id": claim_id,
        "claim_content_sha256": claim_sha,
        "phase": "grounded_confirmation_pending",
        "confirmation_id": confirmation_id,
        "session_id": observation.session_id,
        "observation_id": observation.observation_id,
        "intent_id": intent.intent_id,
        "preview": preview_payload,
        "owner_instance_id": owner_instance_id,
        "requested_at": format_utc(requested_at),
        "expires_at": format_utc(
            requested_at + timedelta(seconds=GROUNDED_CONFIRMATION_TTL_SECONDS)
        ),
        "artifact_is_authorization": False,
        "grants_action_authority": False,
    }
    record["request_binding_sha256"] = binding_sha256(record, "request_binding_sha256")
    return record


def validate_request_record(
    value: Mapping[str, Any],
    *,
    base: Mapping[str, Any],
    identity_hash: str,
) -> tuple[dict[str, Any], GroundedActionPreview, datetime, datetime]:
    claim_id, claim_sha, observation, intent = _claim_fields(base)
    marker = dict(value)
    if (
        set(marker) != _REQUEST_KEYS
        or marker.get("store_contract_version") != REQUEST_CONTRACT_VERSION
        or marker.get("phase") != "grounded_confirmation_pending"
        or marker.get("claim_id") != claim_id
        or marker.get("claim_content_sha256") != claim_sha
        or marker.get("confirmation_id") != f"grounded-confirmation.{identity_hash}"
        or marker.get("session_id") != observation.session_id
        or marker.get("observation_id") != observation.observation_id
        or marker.get("intent_id") != intent.intent_id
        or marker.get("artifact_is_authorization") is not False
        or marker.get("grants_action_authority") is not False
        or marker.get("request_binding_sha256")
        != binding_sha256(marker, "request_binding_sha256")
    ):
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation request"
        )
    owner = marker.get("owner_instance_id")
    if not isinstance(owner, str) or _OWNER_ID.fullmatch(owner) is None:
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation request owner"
        )
    preview_value = marker.get("preview")
    if not isinstance(preview_value, Mapping):
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation request preview"
        )
    try:
        preview = GroundedActionPreview.from_dict(preview_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation request preview"
        ) from exc
    validate_preview_binding(preview, base=base)
    requested = parse_utc(marker.get("requested_at"))
    expires = parse_utc(marker.get("expires_at"))
    if expires - requested != timedelta(seconds=GROUNDED_CONFIRMATION_TTL_SECONDS):
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation request TTL"
        )
    return marker, preview, requested, expires


def build_decision_record(
    *,
    base: Mapping[str, Any],
    confirmation_id: str,
    request_content_sha256: str,
    decision: Literal["approved", "denied"],
    decided_at: datetime,
) -> dict[str, Any]:
    claim_id, claim_sha, _observation, _intent = _claim_fields(base)
    record: dict[str, Any] = {
        "store_contract_version": DECISION_CONTRACT_VERSION,
        "claim_id": claim_id,
        "claim_content_sha256": claim_sha,
        "phase": "grounded_confirmation_decided",
        "confirmation_id": confirmation_id,
        "request_content_sha256": request_content_sha256,
        "decision": decision,
        "decided_at": format_utc(decided_at),
        "artifact_is_authorization": False,
        "grants_action_authority": False,
    }
    record["decision_binding_sha256"] = binding_sha256(record, "decision_binding_sha256")
    return record


def validate_decision_record(
    value: Mapping[str, Any],
    *,
    base: Mapping[str, Any],
    request: Mapping[str, Any],
    request_raw: bytes,
) -> tuple[dict[str, Any], datetime]:
    claim_id, claim_sha, _observation, _intent = _claim_fields(base)
    marker = dict(value)
    request_sha = hashlib.sha256(request_raw).hexdigest()
    if (
        set(marker) != _DECISION_KEYS
        or marker.get("store_contract_version") != DECISION_CONTRACT_VERSION
        or marker.get("phase") != "grounded_confirmation_decided"
        or marker.get("claim_id") != claim_id
        or marker.get("claim_content_sha256") != claim_sha
        or marker.get("confirmation_id") != request.get("confirmation_id")
        or marker.get("request_content_sha256") != request_sha
        or marker.get("decision") not in ("approved", "denied")
        or marker.get("artifact_is_authorization") is not False
        or marker.get("grants_action_authority") is not False
        or marker.get("decision_binding_sha256")
        != binding_sha256(marker, "decision_binding_sha256")
    ):
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation decision"
        )
    decided = parse_utc(marker.get("decided_at"))
    requested = parse_utc(request.get("requested_at"))
    expires = parse_utc(request.get("expires_at"))
    if decided < requested or decided >= expires:
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation decision time"
        )
    return marker, decided


def build_closed_record(
    *,
    base: Mapping[str, Any],
    confirmation_id: str,
    request_content_sha256: str,
    decision_content_sha256: str | None,
    reason_code: str,
    closed_at: datetime,
) -> dict[str, Any]:
    claim_id, claim_sha, _observation, _intent = _claim_fields(base)
    record: dict[str, Any] = {
        "store_contract_version": CLOSED_CONTRACT_VERSION,
        "claim_id": claim_id,
        "claim_content_sha256": claim_sha,
        "phase": "grounded_confirmation_closed",
        "confirmation_id": confirmation_id,
        "request_content_sha256": request_content_sha256,
        "decision_content_sha256": decision_content_sha256,
        "reason_code": reason_code,
        "closed_at": format_utc(closed_at),
        "artifact_is_authorization": False,
        "grants_action_authority": False,
    }
    record["closed_binding_sha256"] = binding_sha256(record, "closed_binding_sha256")
    return record


def validate_closed_record(
    value: Mapping[str, Any],
    *,
    base: Mapping[str, Any],
    request: Mapping[str, Any],
    request_raw: bytes,
    decision_raw: bytes | None,
) -> tuple[dict[str, Any], datetime]:
    claim_id, claim_sha, _observation, _intent = _claim_fields(base)
    marker = dict(value)
    expected_decision_sha = hashlib.sha256(decision_raw).hexdigest() if decision_raw else None
    if (
        set(marker) != _CLOSED_KEYS
        or marker.get("store_contract_version") != CLOSED_CONTRACT_VERSION
        or marker.get("phase") != "grounded_confirmation_closed"
        or marker.get("claim_id") != claim_id
        or marker.get("claim_content_sha256") != claim_sha
        or marker.get("confirmation_id") != request.get("confirmation_id")
        or marker.get("request_content_sha256") != hashlib.sha256(request_raw).hexdigest()
        or marker.get("decision_content_sha256") != expected_decision_sha
        or not isinstance(marker.get("reason_code"), str)
        or marker.get("reason_code") not in _REASONS
        or marker.get("artifact_is_authorization") is not False
        or marker.get("grants_action_authority") is not False
        or marker.get("closed_binding_sha256")
        != binding_sha256(marker, "closed_binding_sha256")
    ):
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation close"
        )
    closed = parse_utc(marker.get("closed_at"))
    requested = parse_utc(request.get("requested_at"))
    expires = parse_utc(request.get("expires_at"))
    decided = None
    if decision_raw is not None:
        # decision 已由调用方先行严格校验，这里只固定关闭时序。
        decision_value = json.loads(decision_raw.decode("utf-8"))
        if decision_value.get("decision") == "denied":
            raise RuntimeGroundedConfirmationError(
                "invalid grounded confirmation close after denial"
            )
        decided_value = decision_value.get("decided_at")
        decided = parse_utc(decided_value)
    if (
        closed < requested
        or (decided is not None and closed < decided)
        or (
            marker.get("reason_code") == "grounded_confirmation_expired"
            and closed < expires
        )
    ):
        raise RuntimeGroundedConfirmationError(
            "invalid or tampered grounded confirmation close time"
        )
    return marker, closed


@dataclass(frozen=True, slots=True)
class RuntimeGroundedConfirmationSnapshot:
    confirmation_id: str
    request_content_sha256: str
    preview: GroundedActionPreview
    requested_at: str
    expires_at: str
    owner_instance_id: str
    owner_is_current: bool
    decision: Literal["approved", "denied"] | None = None
    decision_content_sha256: str | None = None
    decided_at: str | None = None
    closed_reason_code: str | None = None
    closed_at: str | None = None
    grants_action_authority: Literal[False] = False
    artifact_is_authorization: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.confirmation_id, str)
            or not self.confirmation_id.startswith("grounded-confirmation.")
            or _SHA256.fullmatch(
                self.confirmation_id.removeprefix("grounded-confirmation.")
            )
            is None
            or not isinstance(self.request_content_sha256, str)
            or _SHA256.fullmatch(self.request_content_sha256) is None
            or not isinstance(self.preview, GroundedActionPreview)
            or not isinstance(self.owner_instance_id, str)
            or _OWNER_ID.fullmatch(self.owner_instance_id) is None
            or type(self.owner_is_current) is not bool
            or self.decision not in (None, "approved", "denied")
            or self.grants_action_authority is not False
            or self.artifact_is_authorization is not False
        ):
            raise RuntimeGroundedConfirmationError(
                "grounded confirmation snapshot is invalid"
            )
        requested = parse_utc(self.requested_at)
        expires = parse_utc(self.expires_at)
        if expires - requested != timedelta(seconds=GROUNDED_CONFIRMATION_TTL_SECONDS):
            raise RuntimeGroundedConfirmationError(
                "grounded confirmation snapshot TTL is invalid"
            )
        if self.decision is None:
            if self.decision_content_sha256 is not None or self.decided_at is not None:
                raise RuntimeGroundedConfirmationError(
                    "grounded confirmation snapshot decision is invalid"
                )
        elif (
            not isinstance(self.decision_content_sha256, str)
            or _SHA256.fullmatch(self.decision_content_sha256) is None
            or self.decided_at is None
        ):
            raise RuntimeGroundedConfirmationError(
                "grounded confirmation snapshot decision is invalid"
            )
        if self.closed_reason_code is None:
            if self.closed_at is not None:
                raise RuntimeGroundedConfirmationError(
                    "grounded confirmation snapshot close is invalid"
                )
        elif (
            not isinstance(self.closed_reason_code, str)
            or self.closed_reason_code not in _REASONS
            or self.closed_at is None
        ):
            raise RuntimeGroundedConfirmationError(
                "grounded confirmation snapshot close is invalid"
            )


def snapshot_from_records(
    *,
    request_raw: bytes,
    request: Mapping[str, Any],
    preview: GroundedActionPreview,
    current_owner_instance_id: str,
    decision_raw: bytes | None,
    decision: Mapping[str, Any] | None,
    closed: Mapping[str, Any] | None,
) -> RuntimeGroundedConfirmationSnapshot:
    return RuntimeGroundedConfirmationSnapshot(
        confirmation_id=request["confirmation_id"],
        request_content_sha256=hashlib.sha256(request_raw).hexdigest(),
        preview=GroundedActionPreview.from_dict(preview.to_dict()),
        requested_at=request["requested_at"],
        expires_at=request["expires_at"],
        owner_instance_id=request["owner_instance_id"],
        owner_is_current=request["owner_instance_id"] == current_owner_instance_id,
        decision=decision.get("decision") if decision else None,
        decision_content_sha256=(
            hashlib.sha256(decision_raw).hexdigest() if decision_raw else None
        ),
        decided_at=decision.get("decided_at") if decision else None,
        closed_reason_code=closed.get("reason_code") if closed else None,
        closed_at=closed.get("closed_at") if closed else None,
    )


__all__ = [
    "CLOSED_CONTRACT_VERSION",
    "DECISION_CONTRACT_VERSION",
    "GROUNDED_CONFIRMATION_TTL_SECONDS",
    "REQUEST_CONTRACT_VERSION",
    "RuntimeGroundedConfirmationError",
    "RuntimeGroundedConfirmationSnapshot",
    "build_closed_record",
    "build_decision_record",
    "build_request_record",
    "canonical_json_bytes",
    "content_sha256",
    "format_utc",
    "parse_utc",
    "snapshot_from_records",
    "validate_closed_record",
    "validate_decision_record",
    "validate_preview_binding",
    "validate_request_record",
]
