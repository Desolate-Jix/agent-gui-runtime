"""首次学习已批准预览的不可变 consume 标记。"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from app.agent.fresh_learning_action_contracts import canonical_json_bytes
from app.agent.fresh_learning_action_preview import FreshLearningActionPreview

CONTRACT_VERSION = "runtime_fresh_learning_grounded_consume_v1"


class RuntimeFreshConsumeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeFreshConsumeSnapshot:
    confirmation_id: str
    content_sha256: str
    fresh_preview: FreshLearningActionPreview
    approved_preview_sha256: str
    fresh_preview_sha256: str
    source_sha256: str
    capture_id: str
    artifact_is_authorization: bool = False
    grants_action_authority: bool = False


def build_record(*, base, request: Mapping[str, Any], request_raw: bytes, decision_raw: bytes,
                 fresh_preview: Mapping[str, Any]) -> dict[str, Any]:
    if request.get("confirmation_id") is None:
        raise RuntimeFreshConsumeError("fresh consume request is invalid")
    preview_hash = fresh_preview.get("preview_sha256")
    if not isinstance(preview_hash, str):
        raise RuntimeFreshConsumeError("fresh consume preview is invalid")
    return {"contract_version": CONTRACT_VERSION, "confirmation_id": request["confirmation_id"],
            "claim_id": base.claim_id, "claim_content_sha256": base.claim_content_sha256,
            "request_content_sha256": sha256(request_raw).hexdigest(),
            "decision_content_sha256": sha256(decision_raw).hexdigest(),
            "approved_preview_sha256": request["preview_sha256"], "fresh_preview_sha256": preview_hash,
            "fresh_preview": dict(fresh_preview),
            "source_sha256": base.server_binding.source_sha256,
            "capture_id": fresh_preview.get("observation_evidence", {}).get("capture", {}).get("capture_id"),
            "artifact_is_authorization": False, "execute_binding_enabled": False, "action_executed": False}


def content_sha256(record: Mapping[str, Any]) -> str:
    return sha256(canonical_json_bytes(record)).hexdigest()
