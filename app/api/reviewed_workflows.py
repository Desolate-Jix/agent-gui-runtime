from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.api.models.response import APIResponse, ErrorModel
from app.learn.interface_workflow_lock import interface_workflow_lock
from app.learn.interface_workflow_review import load_interface_workflow_library_registry


ROOT_DIR = Path(__file__).resolve().parents[2]


class PanelCompileReviewedWorkflowAssetRequest(BaseModel):
    """服务端解析 v1 人审流程并编译 v2 资产。"""

    model_config = ConfigDict(extra="forbid")
    application_identity_key: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    expected_source_workflow_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class PanelPublishReviewedWorkflowAssetRequest(PanelCompileReviewedWorkflowAssetRequest):
    """重新编译后以 CAS revision 发布 v2 资产。"""

    expected_registry_revision: int = Field(ge=0)


def _project_root(project_root: Path | None) -> Path:
    return ROOT_DIR if project_root is None else Path(project_root)


def _resolve_reviewed_workflow_source(
    *, application_identity_key: str, workflow_id: str, project_root: Path | None = None
) -> tuple[str, str]:
    """仅信任 v1 registry 中绑定的项目内 source workflow。"""

    root = _project_root(project_root)
    identity_key = str(application_identity_key or "").strip()
    selected_workflow_id = str(workflow_id or "").strip()
    registry = load_interface_workflow_library_registry(project_root=root)
    if not isinstance(registry, dict):
        raise ValueError("interface workflow registry is invalid")
    applications = registry.get("applications")
    workflows = registry.get("workflows")
    revision = registry.get("registry_revision")
    if not isinstance(applications, dict) or not isinstance(workflows, dict) or type(revision) is not int or revision < 0:
        raise ValueError("interface workflow registry shape is invalid")
    application = applications.get(identity_key)
    if not isinstance(application, dict):
        raise ValueError("interface workflow application identity not found")
    workflow_ids = application.get("workflow_ids")
    if not isinstance(workflow_ids, list) or any(not isinstance(item, str) for item in workflow_ids):
        raise ValueError("interface workflow application workflow_ids are invalid")
    if selected_workflow_id not in set(workflow_ids):
        raise ValueError("interface workflow does not belong to selected application")
    record = workflows.get(selected_workflow_id)
    if not isinstance(record, dict):
        raise ValueError("interface workflow not found")
    if str(record.get("application_identity_key") or "").strip() != identity_key:
        raise ValueError("interface workflow application identity mismatch")
    declared_path = Path(str(record.get("path") or ""))
    resolved_path = declared_path.resolve() if declared_path.is_absolute() else (root / declared_path).resolve()
    if root not in resolved_path.parents or not resolved_path.is_file():
        raise ValueError("interface workflow source path is invalid")
    source_sha = str(record.get("source_asset_sha256") or "").strip().lower()
    if len(source_sha) != 64 or any(character not in "0123456789abcdef" for character in source_sha):
        raise ValueError("interface workflow source SHA-256 is invalid")
    return resolved_path.relative_to(root).as_posix(), source_sha


def _compile_reviewed_workflow_request(
    request: PanelCompileReviewedWorkflowAssetRequest,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    source_path, registry_sha = _resolve_reviewed_workflow_source(
        application_identity_key=request.application_identity_key,
        workflow_id=request.workflow_id,
        project_root=root,
    )
    expected_sha = request.expected_source_workflow_sha256.lower()
    if expected_sha != registry_sha:
        return {
            "contract_version": "reviewed_workflow_compile_result_v2",
            "status": "blocked",
            "asset": None,
            "blocked_reasons": [{"code": "source_workflow_sha256_mismatch", "message": "expected source workflow SHA-256 does not match registry binding"}],
        }
    return compile_reviewed_workflow_asset_v2(
        project_root=root,
        source_workflow_path=source_path,
        expected_source_workflow_sha256=expected_sha,
    )


def _safe_blocked_compile_result(result: dict[str, Any]) -> dict[str, Any]:
    """阻断结果只暴露稳定 reason code，绝不回传编译器的文件路径文本。"""

    return {
        "contract_version": "reviewed_workflow_compile_result_v2",
        "status": "blocked",
        "asset": None,
        "blocked_reasons": [
            {"code": str(item.get("code") or "compile_blocked"), "message": "reviewed workflow compilation blocked"}
            for item in result.get("blocked_reasons", [])
            if isinstance(item, dict)
        ],
    }


def compile_reviewed_workflow_asset_endpoint(
    request: PanelCompileReviewedWorkflowAssetRequest,
    *,
    project_root: Path | None = None,
) -> APIResponse:
    """编译服务端注册的人审流程；此端点不写入 v2 CAS。"""

    root = _project_root(project_root)
    try:
        result = _compile_reviewed_workflow_request(request, project_root=root)
        registry_revision = ReviewedWorkflowAssetStore(project_root=root).registry()["registry_revision"]
    except (OSError, ValueError, json.JSONDecodeError):
        return APIResponse(success=False, message="Reviewed workflow compile failed", data=None, error=ErrorModel(code="reviewed_workflow_compile_failed", details="server-side reviewed workflow source validation failed"))
    if result.get("status") != "compiled":
        return APIResponse(success=False, message="Reviewed workflow compile blocked", data={"result": _safe_blocked_compile_result(result), "registry_revision": registry_revision, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=ErrorModel(code="reviewed_workflow_compile_blocked", details="reviewed workflow compilation did not satisfy fail-closed checks"))
    return APIResponse(success=True, message="Reviewed workflow compiled", data={"result": result, "registry_revision": registry_revision, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=None)


def publish_reviewed_workflow_asset_endpoint(
    request: PanelPublishReviewedWorkflowAssetRequest,
    *,
    project_root: Path | None = None,
) -> APIResponse:
    """在 CAS 写入前重新编译；从不接受客户端提供的 asset。"""

    root = _project_root(project_root)
    try:
        with interface_workflow_lock(request.workflow_id):
            compile_request = PanelCompileReviewedWorkflowAssetRequest(
                application_identity_key=request.application_identity_key,
                workflow_id=request.workflow_id,
                expected_source_workflow_sha256=request.expected_source_workflow_sha256,
            )
            result = _compile_reviewed_workflow_request(
                compile_request, project_root=root
            )
            if result.get("status") != "compiled" or not isinstance(result.get("asset"), dict):
                return APIResponse(success=False, message="Reviewed workflow publish blocked", data={"compile_result": _safe_blocked_compile_result(result)}, error=ErrorModel(code="reviewed_workflow_compile_blocked", details="reviewed workflow must compile immediately before publish"))
            # 在 CAS 写入前再次读取 v1 binding 与 source bytes，避免 save/delete 的 TOCTOU。
            source_path, source_sha = _resolve_reviewed_workflow_source(
                application_identity_key=request.application_identity_key,
                workflow_id=request.workflow_id,
                project_root=root,
            )
            if (
                request.workflow_id != result["asset"]["source_review_lineage"]["source_workflow_id"]
                or source_sha != result["asset"]["source_review_lineage"]["source_workflow_sha256"]
                or hashlib.sha256((root / source_path).read_bytes()).hexdigest() != source_sha
            ):
                return APIResponse(success=False, message="Reviewed workflow publish blocked", data={"compile_result": result}, error=ErrorModel(code="reviewed_workflow_source_changed", details="reviewed workflow source changed before publish"))
            publish_result = ReviewedWorkflowAssetStore(project_root=root).publish(result["asset"], expected_registry_revision=request.expected_registry_revision)
    except (OSError, ValueError, json.JSONDecodeError):
        return APIResponse(success=False, message="Reviewed workflow publish failed", data=None, error=ErrorModel(code="reviewed_workflow_publish_failed", details="server-side reviewed workflow publish validation failed"))
    return APIResponse(success=True, message="Reviewed workflow published", data={"compile_result": result, "publish_result": publish_result, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=None)


class PanelPreviewReviewedWorkflowReplayRequest(BaseModel):
    """只读地解析已发布资产的当前状态；绝不捕获或执行。"""

    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    current_observation: dict[str, Any] | None = None


def preview_reviewed_workflow_replay_endpoint(
    request: PanelPreviewReviewedWorkflowReplayRequest,
    *, project_root: Path | None = None,
) -> APIResponse:
    """只读 replay preview：仅加载 CAS 与解析 observation，绝不调用捕获或 action。"""

    root = _project_root(project_root)
    try:
        asset = ReviewedWorkflowAssetStore(project_root=root).load_active(request.asset_id)
        actual_sha = content_sha256(asset)
        preview_base = {"mode": "read_only_preview", "would_call_action_api": False, "execution_authorized": False, "artifact_is_authorization": False, "execute_binding_enabled": False}
        if actual_sha != request.expected_content_sha256.lower():
            return APIResponse(success=False, message="Reviewed workflow preview blocked", data=preview_base, error=ErrorModel(code="reviewed_workflow_preview_hash_mismatch", details="expected content SHA-256 does not match active reviewed workflow asset"))
        if not request.current_observation:
            return APIResponse(success=False, message="Reviewed workflow preview observation required", data={**preview_base, "asset_id": asset["asset_id"], "content_sha256": actual_sha}, error=ErrorModel(code="reviewed_workflow_preview_observation_required", details="a nonempty current observation is required for read-only replay preview"))
        resolution = resolve_current_state(asset, request.current_observation)
    except (OSError, ValueError, json.JSONDecodeError):
        return APIResponse(success=False, message="Reviewed workflow preview failed", data={"mode": "read_only_preview", "would_call_action_api": False, "execution_authorized": False, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=ErrorModel(code="reviewed_workflow_preview_failed", details="server-side reviewed workflow preview validation failed"))
    data = {**preview_base, "asset_id": asset["asset_id"], "content_sha256": actual_sha, "state_resolution": resolution}
    if resolution.get("status") != "resolved":
        return APIResponse(success=False, message="Reviewed workflow preview unresolved", data=data, error=ErrorModel(code="reviewed_workflow_preview_unresolved", details="current observation did not resolve one reviewed workflow state"))
    return APIResponse(success=True, message="Reviewed workflow replay preview resolved", data=data, error=None)
