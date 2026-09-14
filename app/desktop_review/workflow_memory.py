"""Agent 选择已审核记忆的只读视图；不授予执行权限，也不选择下一步。"""
from __future__ import annotations

import base64
import hashlib
import json

from app.agent import workflow_versions
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from .workspace import DesktopReviewError


PAGE_SIZE = 16
MAX_RESPONSE_BYTES = 1_000_000
_FLAGS = {"contract_version": "agent_workflow_memory_v1", "artifact_is_authorization": False,
          "execute_binding_enabled": False, "requires_current_grounding": True}
_SCOPE_KEYS = {"kind", "executable", "executable_path", "product_identity", "origin", "domain"}
_PRIVATE_KEYS = {"path", "png_base64", "png_bytes", "image_bytes", "screenshot_path", "image_path"}


class WorkflowMemoryError(DesktopReviewError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _scope(ids, application_scope=None, query="") -> tuple[list[str], dict, str]:
    try:
        if not isinstance(ids, list) or len(ids) > 128:
            raise ValueError("invalid scope")
        allowed = sorted({workflow_versions.logical_id(item) for item in ids})
        application = {} if application_scope is None else application_scope
        if (not isinstance(application, dict) or set(application) - _SCOPE_KEYS
                or any(not isinstance(value, str) or not value or len(value) > 2048 for value in application.values())
                or not isinstance(query, str) or len(query) > 4000):
            raise ValueError("invalid query")
        return allowed, application, query
    except (TypeError, ValueError) as error:
        raise WorkflowMemoryError("invalid_arguments") from error


def _view(value):
    if isinstance(value, dict):
        return {key: _view(child) for key, child in value.items()
                if key == "executable_path" or (key not in _PRIVATE_KEYS and not key.endswith(("_path", "_paths")))}
    if isinstance(value, list):
        return [_view(child) for child in value]
    return value


def _bounded(value: dict) -> dict:
    if len(_bytes(value)) > MAX_RESPONSE_BYTES:
        raise WorkflowMemoryError("memory_too_large")
    return value


class WorkflowMemoryReader:
    def __init__(self, facade):
        self.facade = facade
        self.store = ReviewedWorkflowAssetStore(project_root=facade._artifact_root)

    def _registry(self):
        try:
            return self.store.registry()
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            raise WorkflowMemoryError("memory_source_unavailable") from error

    def _read(self, workflow_id, version, registry):
        selected = version or registry.get("current_version_by_workflow", {}).get(workflow_id)
        record = registry.get("workflow_versions", {}).get(selected)
        if not isinstance(record, dict) or record["logical_workflow_id"] != workflow_id:
            raise WorkflowMemoryError("not_found")
        try:
            from .exact_review import ExactReviewService
            publication = self.store.load_workflow_version(workflow_id, selected)
            if publication["registry_revision"] != registry["registry_revision"]:
                raise WorkflowMemoryError("stale_revision")
            verified = ExactReviewService(self.facade).inspect_published_version(publication)
            graph = verified["graph_snapshot"]
            result = {**_FLAGS, "workflow_id": workflow_id, "version_id": selected,
                      "version_status": publication["status"], "registry_revision": registry["registry_revision"],
                      "graph_revision": publication["graph_revision"], "graph_sha256": publication["graph_sha256"],
                      "asset_id": publication["asset_id"], "asset_sha256": publication["asset_sha256"],
                      "review_ref": publication["review_ref"], "approval_revision": publication["approval_revision"],
                      "approval_status": "reviewed_at_publication", "approval_current": verified["approval_current"],
                      "source_state": "present", "application_scope": _view(publication["asset"]["application"]),
                      "display_name": graph["graph"]["workflow"].get("goal") or workflow_id,
                      "application_display_name": verified["application_identity"].get("display_name", ""),
                      "graph_is_canonical": False, "asset_is_canonical": False,
                      "graph_view": _view(graph["graph"]), "asset_view": _view(publication["asset"])}
        except WorkflowMemoryError:
            raise
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            raise WorkflowMemoryError("memory_source_unavailable") from error
        return result

    def _unchanged(self, revision):
        if self._registry()["registry_revision"] != revision:
            raise WorkflowMemoryError("stale_revision")

    def get(self, allowed_workflow_ids, workflow_id, version=None):
        allowed, _, _ = _scope(allowed_workflow_ids)
        try:
            workflow_versions.logical_id(workflow_id)
            if version is not None:
                workflow_versions.version_id(version)
        except (ValueError, TypeError) as error:
            raise WorkflowMemoryError("invalid_arguments") from error
        if workflow_id not in allowed:
            raise WorkflowMemoryError("not_found")
        registry = self._registry()
        result = self._read(workflow_id, version, registry)
        self._unchanged(registry["registry_revision"])
        return _bounded(result)

    def search(self, allowed_workflow_ids, application_scope, query="", cursor=None):
        allowed, application, query = _scope(allowed_workflow_ids, application_scope, query)
        registry = self._registry()
        revision = registry["registry_revision"]
        binding = hashlib.sha256(_bytes([allowed, application, query])).hexdigest()
        offset = 0
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or not cursor or len(cursor) > 1024:
                    raise ValueError("invalid cursor")
                raw = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
                page = json.loads(raw.decode("utf-8"))
                if (not isinstance(page, dict) or set(page) != {"binding", "revision", "offset"}
                        or page["binding"] != binding or type(page["revision"]) is not int
                        or type(page["offset"]) is not int or not 0 <= page["offset"] <= len(allowed)):
                    raise ValueError("invalid cursor binding")
                if page["revision"] != revision:
                    raise WorkflowMemoryError("stale_revision")
                offset = page["offset"]
            except WorkflowMemoryError:
                raise
            except (ValueError, TypeError, UnicodeError) as error:
                raise WorkflowMemoryError("invalid_arguments") from error
        items = []
        scan_end = min(len(allowed), offset + PAGE_SIZE)
        while offset < scan_end:
            identity = allowed[offset]
            offset += 1
            if identity not in registry.get("current_version_by_workflow", {}):
                continue
            result = self._read(identity, None, registry)
            candidate_scope = result["application_scope"]
            if any(candidate_scope.get(key, "").casefold() != value.casefold() for key, value in application.items()):
                continue
            if query.casefold() not in (result["display_name"] + " " + result["application_display_name"] + " " + _bytes(candidate_scope).decode("utf-8")).casefold():
                continue
            items.append({key: value for key, value in result.items() if key not in {"graph_view", "asset_view"}})
        self._unchanged(revision)
        next_cursor = base64.urlsafe_b64encode(_bytes({"binding": binding, "revision": revision, "offset": offset})).decode("ascii") if offset < len(allowed) else None
        return _bounded({**_FLAGS, "registry_revision": revision, "items": items, "next_cursor": next_cursor})
