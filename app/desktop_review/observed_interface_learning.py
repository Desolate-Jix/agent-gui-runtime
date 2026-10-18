"""将首次观察中的 Agent 语义安全地写入同一张独立界面。"""
from __future__ import annotations

import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

from app.agent_link.contracts import AgentLinkError, RegionInput
from .external_mapping import canonical_json_bytes
from .workspace import DesktopReviewError


def submit_observed_interface_learning(
    facade, *, connection_id: str, task_id: str, segment_id: str, batch_id: str,
    expected_revision: int, expected_sha256: str, meaning: str,
    recognition_text: str | None, regions: list[dict], idempotency_key: str,
) -> dict:
    """只允许把未填充的首次观察界面完成一次；不覆盖人工修订。"""
    if type(expected_revision) is not int or expected_revision < 1:
        raise AgentLinkError("invalid_arguments", "expected_revision is invalid")
    if (not isinstance(idempotency_key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}", idempotency_key) is None
            or not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            or not isinstance(meaning, str) or not meaning.strip() or len(meaning) > 4000
            or (recognition_text is not None and (not isinstance(recognition_text, str) or len(recognition_text) > 4000))):
        raise AgentLinkError("invalid_arguments", "observed interface arguments are invalid")
    if not isinstance(regions, list) or not regions:
        raise AgentLinkError("invalid_arguments", "regions must contain at least one region")
    with facade._guard:
        owner = facade._service._store.read(lambda state: state["connections"].get(connection_id, {}))
        segment = owner.get("learning_segments", {}).get(segment_id) if isinstance(owner, dict) else None
        if not isinstance(segment, dict) or owner.get("task_id") != task_id or segment.get("status") != "active":
            raise AgentLinkError("not_found", "learning segment was not found")
        if not any(item.get("batch_id") == batch_id for item in segment.get("observations", [])):
            raise AgentLinkError("not_found", "observed batch was not found in this segment")
        batch = facade._load_source_batch(task_id, batch_id)
        interface = next((item for item in batch.get("interfaces", []) if item.get("interface_id") == "observed-screen"), None)
        if not isinstance(interface, dict) or interface.get("regions") != []:
            raise AgentLinkError("stale_revision", "observed interface is already completed or modified")
        current = facade.import_interface_content(task_id, batch_id, "observed-screen")
        from .interface_content import InterfaceContentService
        content_service = InterfaceContentService(facade)
        manifest = content_service._current(current["interface_id"])
        normalized = []
        for region in regions:
            value = dict(region) if isinstance(region, dict) else region
            if not isinstance(value, dict):
                raise AgentLinkError("invalid_arguments", "region is invalid")
            # 区域 ID 由服务端生成，保证相同提案重试稳定。
            seed = f"{batch_id}|{value.get('bbox')}|{value.get('name') or value.get('label') or value.get('kind')}|{value.get('meaning')}|{value.get('recognition_text','')}"
            value = {**value, "region_id": "region-user-" + str(uuid5(NAMESPACE_URL, seed))}
            value.setdefault("recognition_text", "")
            try:
                checked = RegionInput.model_validate(value)
            except (TypeError, ValueError) as error:
                raise AgentLinkError("invalid_arguments", "region is invalid") from error
            normalized.append(checked.model_dump(exclude_none=True))
        changes = {"meaning": meaning, "recognition_text": recognition_text or "", "regions": normalized}
        request_sha = hashlib.sha256(canonical_json_bytes({
            "revision": expected_revision, "sha": expected_sha256, "changes": changes,
        })).hexdigest()
        prior = manifest.get("requests", {}).get(idempotency_key)
        if isinstance(prior, dict):
            if prior.get("request_sha256") != request_sha:
                raise AgentLinkError("idempotency_conflict", "idempotency key was already used with different content")
            if isinstance(prior.get("version_id"), str):
                content_service.load(current["interface_id"], prior["version_id"])
                return _record_completion(content_service, current["interface_id"], prior["request_sha256"])
        if current["revision"] != 1 or current["revision"] != expected_revision or current["content_sha256"] != expected_sha256:
            raise AgentLinkError("stale_revision", "observed interface must still be the original revision")
        if current["content"].get("regions") or current.get("review_status") == "reviewed":
            raise AgentLinkError("stale_revision", "observed interface is already completed or reviewed")
        try:
            facade.save_interface_content(
                current["interface_id"], expected_revision, expected_sha256, changes, idempotency_key,
            )
            return _record_completion(content_service, current["interface_id"], request_sha)
        except DesktopReviewError as error:
            code = str(error)
            if code == "stale_revision":
                raise AgentLinkError("stale_revision", "observed interface revision is stale") from error
            if code == "idempotency_conflict":
                raise AgentLinkError("idempotency_conflict", "idempotency key was already used with different content") from error
            raise AgentLinkError("invalid_arguments", "observed interface content is invalid") from error
        except OSError as error:
            raise AgentLinkError("persistence_failed", "observed interface content could not be persisted") from error


def _record_completion(content_service, interface_id: str, request_sha256: str) -> dict:
    """首次提交和幂等补写使用同一错误边界，不隐藏磁盘失败。"""
    try:
        return content_service._record_initial_learning_completion(interface_id, request_sha256=request_sha256)
    except OSError as error:
        raise AgentLinkError("persistence_failed", "observed interface completion marker could not be persisted") from error
    except DesktopReviewError as error:
        raise AgentLinkError("invalid_evidence", "observed interface completion identity is invalid") from error
