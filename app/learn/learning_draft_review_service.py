from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from app.learn.draft_review import _resolve_source_path, load_learning_draft_review
from app.learn.interface_workflow_review import build_interface_workflow_review
from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review
from app.learn.workflow_service import prepare_learning_selection_review_replay
from app.learn.workflow_state import (
    LearningWorkflowTransitionError,
    validate_learning_workflow_state,
)


def authoritative_hybrid_workflow_expectations(
    workflow_run_id: str | None,
    *,
    source_path: str,
    project_root: Path,
    workflow_store: Any,
) -> tuple[str | None, int | None, dict[str, str] | None]:
    """仅从既有服务端工作流存储恢复 Hybrid 新鲜度与来源绑定。"""

    normalized_run_id = str(workflow_run_id or "").strip()
    if not normalized_run_id:
        return None, None, None
    try:
        state = validate_learning_workflow_state(
            workflow_store.get(normalized_run_id)
        )
    except (LearningWorkflowTransitionError, TypeError, ValueError):
        return None, None, None
    revision = state.get("revision")
    if (
        state.get("run_id") != normalized_run_id
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
    ):
        return None, None, None
    try:
        resolved_sources = _authoritative_hybrid_source_binding_paths(
            source_path, project_root=project_root
        )
    except (OSError, TypeError, ValueError):
        return None, None, None
    source_keys = {
        "trial_path",
        "source_path",
        "original_draft_path",
        "review_path",
        "scaffold_path",
    }
    source_bound = False
    bound_source_path: Path | None = None
    for event in state.get("events", []):
        refs = event.get("evidence_refs") if isinstance(event, dict) else None
        if not isinstance(refs, dict):
            continue
        for key in source_keys:
            evidence_path = refs.get(key)
            if not isinstance(evidence_path, str) or not evidence_path.strip():
                continue
            try:
                resolved_evidence = _resolve_source_path(evidence_path, project_root)
                source_bound = resolved_evidence in resolved_sources
            except (OSError, TypeError, ValueError):
                continue
            if source_bound:
                bound_source_path = resolved_evidence
                break
        if source_bound:
            break
    if not source_bound:
        return None, None, None
    lineage_ref = _authoritative_hybrid_capture_lineage_from_source(
        str(bound_source_path), project_root=project_root
    )
    if lineage_ref is None:
        return None, None, None
    managed_present, managed_revision, managed_lineage_ref = (
        _authoritative_managed_hybrid_trial_expectations(
            state=state,
            trial_path=bound_source_path,
            capture_lineage_ref=lineage_ref,
            project_root=project_root,
        )
    )
    if managed_present:
        if managed_revision is None or managed_lineage_ref is None:
            return None, None, None
        return str(state["run_id"]), managed_revision, managed_lineage_ref
    return str(state["run_id"]), revision, lineage_ref


def _authoritative_managed_hybrid_trial_expectations(
    *,
    state: dict[str, Any],
    trial_path: Path,
    capture_lineage_ref: dict[str, str],
    project_root: Path,
) -> tuple[bool, int | None, dict[str, str] | None]:
    """从服务端绑定的 managed trial 恢复生成投影时的操作版本。"""

    resolved_trial = trial_path.resolve()
    managed_completions: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for event in state.get("events", []):
        if not isinstance(event, dict):
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, dict):
            continue
        continuation = refs.get("worker_continuation")
        event_trial = refs.get("trial_path")
        try:
            event_trial_path = (
                _resolve_source_path(event_trial, project_root)
                if isinstance(event_trial, str) and event_trial.strip()
                else None
            )
        except (OSError, TypeError, ValueError):
            event_trial_path = None
        if (
            event_trial_path == resolved_trial
            and isinstance(continuation, dict)
            and continuation.get("task_kind")
            == "panel_learning_hybrid_review_projection"
        ):
            managed_completions.append((event, refs, continuation))
    if not managed_completions:
        return False, None, None
    if len(managed_completions) != 1:
        return True, None, None
    completion_event, completion_refs, continuation = managed_completions[0]
    if (
        completion_event.get("stage") != "screen_understanding"
        or completion_event.get("outcome") != "completed"
    ):
        return True, None, None
    try:
        payload = json.loads(trial_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True, None, None
    if not isinstance(payload, dict) or "managed_hybrid_lineage" not in payload:
        return True, None, None
    managed = payload.get("managed_hybrid_lineage")
    expected_managed_fields = {
        "run_id",
        "workflow_revision",
        "operation_id",
        "worker_id",
        "result_sha256",
        "capture_lineage_ref",
        "hybrid_capture_bundle_ref",
    }
    if not isinstance(managed, dict) or set(managed) != expected_managed_fields:
        return True, None, None
    run_id = managed.get("run_id")
    operation_revision = managed.get("workflow_revision")
    operation_id = managed.get("operation_id")
    worker_id = managed.get("worker_id")
    result_sha256 = managed.get("result_sha256")
    if (
        run_id != state.get("run_id")
        or isinstance(operation_revision, bool)
        or not isinstance(operation_revision, int)
        or operation_revision < 0
        or not all(
            isinstance(value, str) and value
            for value in (operation_id, worker_id, result_sha256)
        )
        or len(result_sha256) != 64
        or managed.get("capture_lineage_ref") != capture_lineage_ref
        or managed.get("hybrid_capture_bundle_ref")
        != completion_refs.get("hybrid_capture_bundle_ref")
        or continuation.get("operation_id") != operation_id
        or continuation.get("worker_id") != worker_id
        or continuation.get("result_sha256") != result_sha256
    ):
        return True, None, None
    operation_bound = False
    for event in state.get("events", []):
        if not isinstance(event, dict):
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, dict):
            continue
        execution = refs.get("stage_execution")
        if (
            event.get("revision") == operation_revision
            and isinstance(execution, dict)
            and execution.get("operation_id") == operation_id
            and execution.get("stage") == "screen_understanding"
        ):
            operation_bound = True
    if (
        not operation_bound
        or not isinstance(completion_event.get("revision"), int)
        or completion_event["revision"] <= operation_revision
    ):
        return True, None, None
    return True, operation_revision, deepcopy(capture_lineage_ref)


def _authoritative_hybrid_source_binding_paths(
    source_path: str,
    *,
    project_root: Path,
) -> set[Path]:
    """只允许服务端受管审核件回溯到工作流已经记录的原始来源。"""

    resolved = _resolve_source_path(source_path, project_root)
    paths = {resolved}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return paths
    if (
        not isinstance(payload, dict)
        or payload.get("contract_version") != "reviewed_template_candidate_v1"
    ):
        return paths
    source = payload.get("source")
    original = source.get("original_draft_path") if isinstance(source, dict) else None
    if isinstance(original, str) and original.strip():
        paths.add(_resolve_source_path(original, project_root))
    return paths


def _authoritative_hybrid_capture_lineage_from_source(
    source_path: str,
    *,
    project_root: Path,
) -> dict[str, str] | None:
    resolved = _resolve_source_path(source_path, project_root)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    candidates = [payload]
    for key in ("draft", "learning_draft", "best_learning_draft"):
        child = payload.get(key)
        if isinstance(child, dict):
            candidates.append(child)
    refs: dict[tuple[str, str], dict[str, str]] = {}
    for candidate in candidates:
        values = [candidate.get("capture_lineage_ref")]
        page_details = candidate.get("page_details")
        if isinstance(page_details, dict):
            values.append(page_details.get("capture_lineage_ref"))
        for value in values:
            if (
                isinstance(value, dict)
                and set(value) == {"id", "content_sha256"}
                and all(
                    isinstance(value.get(field), str) and value[field]
                    for field in ("id", "content_sha256")
                )
            ):
                ref = {"id": value["id"], "content_sha256": value["content_sha256"]}
                refs[(ref["id"], ref["content_sha256"])] = ref
    return next(iter(refs.values())) if len(refs) == 1 else None


def load_learning_draft_review_transaction(
    *,
    source_path: str,
    workflow_run_id: str | None,
    discover_related_sidecars: bool,
    project_root: Path,
    workflow_store: Any,
) -> dict[str, Any]:
    """加载单份草稿并仅在服务端绑定 Hybrid 新鲜度。"""

    prepared = prepare_learning_selection_review_replay(
        project_root=project_root,
        source_path=source_path,
    )
    selected_source_path = (
        prepared["trial_path"] if prepared is not None else source_path
    )
    expected_run_id, expected_revision, expected_lineage_ref = (
        authoritative_hybrid_workflow_expectations(
            workflow_run_id,
            source_path=selected_source_path,
            project_root=project_root,
            workflow_store=workflow_store,
        )
    )
    load_options: dict[str, Any] = {
        "project_root": project_root,
        "discover_related_sidecars": discover_related_sidecars,
    }
    if expected_run_id is not None and expected_revision is not None:
        load_options.update(
            expected_hybrid_run_id=expected_run_id,
            expected_hybrid_workflow_revision=expected_revision,
            expected_current_capture_lineage_ref=expected_lineage_ref,
        )
    result = load_learning_draft_review(selected_source_path, **load_options)
    if prepared is not None:
        result.update(prepared)
    return result


def load_interface_workflow_review_transaction(
    *,
    draft_source_paths: list[str],
    workflow_run_ids_by_source: dict[str, str],
    discover_related_sidecars: bool,
    goal: str,
    application_identity: dict[str, Any],
    project_root: Path,
    workflow_store: Any,
) -> dict[str, Any]:
    """加载多份草稿并生成只读的单软件流程审核图。"""

    loaded_reviews: list[dict[str, Any]] = []
    invalid_sources: list[dict[str, Any]] = []
    for source_path in draft_source_paths:
        normalized_path = str(source_path or "").strip()
        if not normalized_path:
            invalid_sources.append(
                {
                    "source_path": "",
                    "failure_category": "invalid_review_source",
                    "reason": "source path is empty",
                }
            )
            continue
        try:
            expected_run_id, expected_revision, expected_lineage_ref = (
                authoritative_hybrid_workflow_expectations(
                    workflow_run_ids_by_source.get(normalized_path),
                    source_path=normalized_path,
                    project_root=project_root,
                    workflow_store=workflow_store,
                )
            )
            load_options: dict[str, Any] = {
                "project_root": project_root,
                "discover_related_sidecars": discover_related_sidecars,
            }
            if expected_run_id is not None and expected_revision is not None:
                load_options.update(
                    expected_hybrid_run_id=expected_run_id,
                    expected_hybrid_workflow_revision=expected_revision,
                    expected_current_capture_lineage_ref=expected_lineage_ref,
                )
            loaded_reviews.append(
                load_learning_draft_review(normalized_path, **load_options)
            )
        except Exception as exc:
            invalid_sources.append(
                {
                    "source_path": normalized_path,
                    "failure_category": "invalid_review_source",
                    "reason": str(exc),
                }
            )
    result = build_interface_workflow_review(
        goal=goal,
        application_identity=application_identity,
        draft_sources=loaded_reviews,
    )
    result["invalid_sources"].extend(invalid_sources)
    return result


def save_learning_draft_review_transaction(
    *,
    source_path: str,
    review_patch: dict[str, Any],
    project_root: Path,
    workflow_store: Any,
) -> dict[str, Any]:
    """保存审核补丁；客户端不得提供 Hybrid 服务器期望。"""

    prepared_patch = deepcopy(review_patch)
    workflow_run_id = prepared_patch.pop("_hybrid_workflow_run_id", None)
    expected_run_id, expected_revision, expected_lineage_ref = (
        authoritative_hybrid_workflow_expectations(
            workflow_run_id,
            source_path=source_path,
            project_root=project_root,
            workflow_store=workflow_store,
        )
    )
    prepared_patch.pop("_server_hybrid_expectations", None)
    if (
        expected_run_id is not None
        and expected_revision is not None
        and expected_lineage_ref is not None
    ):
        prepared_patch["_server_hybrid_expectations"] = {
            "run_id": expected_run_id,
            "workflow_revision": expected_revision,
            "capture_lineage_ref": expected_lineage_ref,
        }
    return build_pathgraph_candidate_from_review(
        source_path,
        prepared_patch,
        project_root=project_root,
    )
