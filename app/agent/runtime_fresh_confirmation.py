"""首次学习确认标记的严格无派发记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Literal, Mapping

from app.agent.fresh_learning_action_contracts import canonical_json_bytes
from app.agent.fresh_learning_action_preview import FreshLearningActionPreview


REQUEST_CONTRACT_VERSION = "runtime_fresh_learning_grounded_confirmation_request_v1"
DECISION_CONTRACT_VERSION = "runtime_fresh_learning_grounded_confirmation_decision_v1"
CLOSED_CONTRACT_VERSION = "runtime_fresh_learning_grounded_confirmation_closed_v1"


class RuntimeFreshConfirmationError(ValueError):
    """首次学习确认记录不满足同一来源绑定。"""


def content_sha256(value: Mapping[str, Any]) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeFreshLearningGroundedConfirmationSnapshot:
    confirmation_id: str
    phase: Literal["pending", "approved", "denied", "closed"]
    preview: FreshLearningActionPreview
    owner_instance_id: str
    owner_is_current: bool
    request_content_sha256: str
    requested_at: datetime
    expires_at: datetime
    decision: Literal["approved", "denied"] | None
    closed_reason_code: str | None
    artifact_is_authorization: bool = False
    grants_action_authority: bool = False

    @property
    def closed_reason(self) -> str | None:
        return self.closed_reason_code


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeFreshConfirmationError(f"fresh confirmation {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeFreshConfirmationError(f"fresh confirmation {label} is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeFreshConfirmationError(f"fresh confirmation {label} is invalid")
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise RuntimeFreshConfirmationError("fresh confirmation timestamp is invalid")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _strict_preview(value: object) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise RuntimeFreshConfirmationError("fresh confirmation preview is invalid")
    return dict(value)


def build_request_record(*, base, confirmation_id: str, preview, owner_instance_id: str,
                         requested_at: datetime, ttl_seconds: int) -> dict[str, Any]:
    if not isinstance(confirmation_id, str) or not confirmation_id:
        raise RuntimeFreshConfirmationError("fresh confirmation identity is invalid")
    if not isinstance(owner_instance_id, str) or not owner_instance_id:
        raise RuntimeFreshConfirmationError("fresh confirmation owner is invalid")
    if type(ttl_seconds) is not int or ttl_seconds != 300:
        raise RuntimeFreshConfirmationError("fresh confirmation TTL is invalid")
    preview_payload = _strict_preview(preview)
    requested = _format_time(requested_at)
    expires = _format_time(requested_at + timedelta(seconds=ttl_seconds))
    return {
        "contract_version": REQUEST_CONTRACT_VERSION,
        "confirmation_id": confirmation_id,
        "session_id": base.observation.session_id,
        "observation_id": base.observation.observation_id,
        "claim_id": base.claim_id,
        "claim_content_sha256": base.claim_content_sha256,
        "intent_sha256": content_sha256(base.intent.to_dict()),
        "source_sha256": base.server_binding.source_sha256,
        "preview": preview_payload,
        "preview_sha256": content_sha256(preview_payload),
        "owner_instance_id": owner_instance_id,
        "requested_at": requested,
        "expires_at": expires,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_executed": False,
    }


def validate_request_record(value: object, *, base, identity_hash: str) -> tuple[dict[str, Any], dict[str, Any], datetime, datetime]:
    required = {"contract_version", "confirmation_id", "session_id", "observation_id",
                "claim_id", "claim_content_sha256", "intent_sha256", "source_sha256",
                "preview", "preview_sha256", "owner_instance_id", "requested_at",
                "expires_at", "artifact_is_authorization", "execute_binding_enabled", "action_executed"}
    if not isinstance(value, Mapping) or set(value) != required or value.get("contract_version") != REQUEST_CONTRACT_VERSION:
        raise RuntimeFreshConfirmationError("fresh confirmation request contract is invalid")
    if value.get("confirmation_id") != f"grounded-confirmation.{identity_hash}":
        raise RuntimeFreshConfirmationError("fresh confirmation request identity is invalid")
    expected = {"session_id": base.observation.session_id, "observation_id": base.observation.observation_id,
                "claim_id": base.claim_id, "claim_content_sha256": base.claim_content_sha256,
                "intent_sha256": content_sha256(base.intent.to_dict()), "source_sha256": base.server_binding.source_sha256}
    if any(value.get(key) != item for key, item in expected.items()):
        raise RuntimeFreshConfirmationError("fresh confirmation request binding mismatch")
    preview = _strict_preview(value.get("preview"))
    if value.get("preview_sha256") != content_sha256(preview):
        raise RuntimeFreshConfirmationError("fresh confirmation preview hash is invalid")
    if not isinstance(value.get("owner_instance_id"), str) or not value["owner_instance_id"]:
        raise RuntimeFreshConfirmationError("fresh confirmation owner is invalid")
    if any(value.get(key) is not False for key in ("artifact_is_authorization", "execute_binding_enabled", "action_executed")):
        raise RuntimeFreshConfirmationError("fresh confirmation crosses authorization boundary")
    requested, expires = _time(value.get("requested_at"), "requested time"), _time(value.get("expires_at"), "expiry")
    if expires - requested != timedelta(seconds=300):
        raise RuntimeFreshConfirmationError("fresh confirmation TTL is invalid")
    return dict(value), preview, requested, expires


def build_decision_record(*, confirmation_id: str, request_raw: bytes, decision: str, decided_at: datetime) -> dict[str, Any]:
    if decision not in {"approved", "denied"}:
        raise RuntimeFreshConfirmationError("fresh confirmation decision is invalid")
    return {"contract_version": DECISION_CONTRACT_VERSION, "confirmation_id": confirmation_id,
            "request_content_sha256": sha256(request_raw).hexdigest(), "decision": decision,
            "decided_at": _format_time(decided_at), "artifact_is_authorization": False,
            "execute_binding_enabled": False, "action_executed": False}


def validate_decision_record(value: object, *, request: Mapping[str, Any], request_raw: bytes) -> dict[str, Any]:
    required = {"contract_version", "confirmation_id", "request_content_sha256", "decision",
                "decided_at", "artifact_is_authorization", "execute_binding_enabled", "action_executed"}
    if not isinstance(value, Mapping) or set(value) != required or value.get("contract_version") != DECISION_CONTRACT_VERSION:
        raise RuntimeFreshConfirmationError("fresh confirmation decision contract is invalid")
    if (value.get("confirmation_id") != request.get("confirmation_id")
            or value.get("request_content_sha256") != sha256(request_raw).hexdigest()
            or value.get("decision") not in {"approved", "denied"}
            or any(value.get(key) is not False for key in ("artifact_is_authorization", "execute_binding_enabled", "action_executed"))):
        raise RuntimeFreshConfirmationError("fresh confirmation decision binding mismatch")
    _time(value.get("decided_at"), "decision time")
    return dict(value)


def build_closed_record(*, request: Mapping[str, Any], request_raw: bytes, decision_raw: bytes | None,
                        reason_code: str, closed_at: datetime) -> dict[str, Any]:
    return {"contract_version": CLOSED_CONTRACT_VERSION, "confirmation_id": request["confirmation_id"],
            "request_content_sha256": sha256(request_raw).hexdigest(),
            "decision_content_sha256": sha256(decision_raw).hexdigest() if decision_raw else None,
            "reason_code": reason_code, "closed_at": _format_time(closed_at),
            "artifact_is_authorization": False, "execute_binding_enabled": False, "action_executed": False}


def validate_closed_record(value: object, *, request: Mapping[str, Any], request_raw: bytes,
                           decision_raw: bytes | None) -> dict[str, Any]:
    required = {"contract_version", "confirmation_id", "request_content_sha256", "decision_content_sha256",
                "reason_code", "closed_at", "artifact_is_authorization", "execute_binding_enabled", "action_executed"}
    if (not isinstance(value, Mapping) or set(value) != required
            or value.get("contract_version") != CLOSED_CONTRACT_VERSION
            or value.get("confirmation_id") != request.get("confirmation_id")
            or value.get("request_content_sha256") != sha256(request_raw).hexdigest()
            or value.get("decision_content_sha256") != (sha256(decision_raw).hexdigest() if decision_raw else None)
            or value.get("reason_code") not in {"grounded_confirmation_cancelled", "grounded_confirmation_expired", "grounded_confirmation_stale", "grounded_confirmation_restarted"}
            or any(value.get(key) is not False for key in ("artifact_is_authorization", "execute_binding_enabled", "action_executed"))):
        raise RuntimeFreshConfirmationError("fresh confirmation close binding mismatch")
    _time(value.get("closed_at"), "close time")
    return dict(value)
