from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.learn.workflow_evidence import LearningWorkflowEvidenceError
from app.learn.workflow_service import transition_learning_workflow_run
from app.learn.workflow_state import LearningWorkflowTransitionError
from app.learn.workflow_store import LearningWorkflowRunStore


LEARNING_WORKFLOW_READONLY_TAIL_CONTRACT_VERSION = (
    "learning_workflow_readonly_tail_v1"
)
ArtifactBuilder = Callable[..., dict[str, Any]]


def run_learning_workflow_readonly_tail(
    *,
    run_id: str,
    expected_revision: int,
    source_path: str | Path,
    project_root: str | Path,
    store: LearningWorkflowRunStore,
    page_detail_builder: ArtifactBuilder,
    scaffold_builder: ArtifactBuilder,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """由后端连续执行学习流程的只读收尾阶段。"""

    root = Path(project_root).resolve()
    source = _resolve_runtime_path(source_path, project_root=root, require_file=True)
    output_dir = (
        _resolve_runtime_path(out_dir, project_root=root, require_file=False)
        if out_dir is not None
        else source.parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    state = transition_learning_workflow_run(
        store=store,
        project_root=root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage="page_details",
        outcome="running",
        reason="backend runner generating read-only page details",
    )
    page_detail_result, state, failure = _execute_artifact_stage(
        store=store,
        project_root=root,
        run_id=run_id,
        state=state,
        stage="page_details",
        completion_field="source_path",
        completion_reason="backend runner page details ready",
        builder=page_detail_builder,
        builder_source=source,
        output_dir=output_dir,
    )
    if failure is not None:
        return failure

    page_detail_path = _result_report_path(page_detail_result, "page details")
    state = transition_learning_workflow_run(
        store=store,
        project_root=root,
        run_id=run_id,
        expected_revision=state["revision"],
        stage="pathgraph_draft",
        outcome="running",
        reason="backend runner generating read-only PathGraph draft",
    )
    scaffold_result, state, failure = _execute_artifact_stage(
        store=store,
        project_root=root,
        run_id=run_id,
        state=state,
        stage="pathgraph_draft",
        completion_field="scaffold_path",
        completion_reason="backend runner read-only PathGraph draft ready",
        builder=scaffold_builder,
        builder_source=Path(page_detail_path),
        output_dir=output_dir,
    )
    if failure is not None:
        return failure

    state = transition_learning_workflow_run(
        store=store,
        project_root=root,
        run_id=run_id,
        expected_revision=state["revision"],
        stage="complete",
        outcome="running",
        reason="backend runner finalizing read-only learning draft",
    )
    state = transition_learning_workflow_run(
        store=store,
        project_root=root,
        run_id=run_id,
        expected_revision=state["revision"],
        stage="complete",
        outcome="completed",
        reason="backend runner completed read-only learning draft",
    )
    return {
        "contract_version": LEARNING_WORKFLOW_READONLY_TAIL_CONTRACT_VERSION,
        "success": True,
        "workflow_state": state,
        "page_detail": page_detail_result,
        "scaffold": scaffold_result,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
        "runtime_pathgraph_promotion": False,
    }


def _execute_artifact_stage(
    *,
    store: LearningWorkflowRunStore,
    project_root: Path,
    run_id: str,
    state: dict[str, Any],
    stage: str,
    completion_field: str,
    completion_reason: str,
    builder: ArtifactBuilder,
    builder_source: Path,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    try:
        result = builder(
            source_path=builder_source,
            out_dir=output_dir,
            project_root=project_root,
        )
        report_path = _result_report_path(result, stage)
    except Exception as exc:
        failed_state = _mark_stage_failed(
            store=store,
            project_root=project_root,
            run_id=run_id,
            state=state,
            stage=stage,
            reason=f"{stage} execution failed: {exc}",
        )
        return {}, failed_state, _failure_result(
            state=failed_state,
            stage=stage,
            category="stage_execution_failed",
            error=exc,
        )

    try:
        completed_state = transition_learning_workflow_run(
            store=store,
            project_root=project_root,
            run_id=run_id,
            expected_revision=state["revision"],
            stage=stage,
            outcome="completed",
            reason=completion_reason,
            evidence_refs={completion_field: report_path},
        )
    except LearningWorkflowEvidenceError as exc:
        failed_state = _mark_stage_failed(
            store=store,
            project_root=project_root,
            run_id=run_id,
            state=state,
            stage=stage,
            reason=f"{stage} evidence rejected: {exc}",
        )
        return result, failed_state, _failure_result(
            state=failed_state,
            stage=stage,
            category="stage_evidence_invalid",
            error=exc,
        )
    except LearningWorkflowTransitionError:
        raise
    return result, completed_state, None


def _mark_stage_failed(
    *,
    store: LearningWorkflowRunStore,
    project_root: Path,
    run_id: str,
    state: dict[str, Any],
    stage: str,
    reason: str,
) -> dict[str, Any]:
    return transition_learning_workflow_run(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=state["revision"],
        stage=stage,
        outcome="failed",
        reason=reason,
    )


def _failure_result(
    *,
    state: dict[str, Any],
    stage: str,
    category: str,
    error: Exception,
) -> dict[str, Any]:
    return {
        "contract_version": LEARNING_WORKFLOW_READONLY_TAIL_CONTRACT_VERSION,
        "success": False,
        "failed_stage": stage,
        "failure_category": category,
        "error": str(error),
        "workflow_state": state,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
        "runtime_pathgraph_promotion": False,
    }


def _result_report_path(result: Any, label: str) -> str:
    if not isinstance(result, dict):
        raise ValueError(f"{label} builder returned no result object")
    report_path = str(result.get("report_path") or "").strip()
    if not report_path:
        raise ValueError(f"{label} builder returned no report_path")
    return report_path


def _resolve_runtime_path(
    path_value: str | Path,
    *,
    project_root: Path,
    require_file: bool,
) -> Path:
    path = Path(path_value)
    resolved = (path if path.is_absolute() else project_root / path).resolve()
    allowed_roots = (
        (project_root / "artifacts").resolve(),
        (project_root / "logs").resolve(),
    )
    if not any(resolved.is_relative_to(allowed_root) for allowed_root in allowed_roots):
        raise ValueError(f"workflow runtime path is outside artifacts/logs: {path_value}")
    if require_file and (not resolved.exists() or not resolved.is_file()):
        raise ValueError(f"workflow source file does not exist: {path_value}")
    return resolved
