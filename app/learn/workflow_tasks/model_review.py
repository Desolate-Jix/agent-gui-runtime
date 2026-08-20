from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.core.runtime_artifacts import write_trace
from app.learn.recognition.panel_review_pipeline import (
    run_panel_learning_model_review_repair,
)
from app.learn.workflow_contracts import (
    LearningTaskFailure,
    LearningTaskResult,
    ModelReviewTaskInput,
)

ReviewRunner = Callable[..., dict[str, Any]]
TraceWriter = Callable[..., str]
PathResolver = Callable[[str | Path], Path]


def _resolve_under_project_root(path: str | Path, *, project_root: Path) -> Path:
    root = project_root.resolve()
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = root / resolved
    resolved = resolved.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path is outside project root: {resolved}")
    return resolved


def run_model_review_task(
    task_input: ModelReviewTaskInput,
    *,
    project_root: Path,
    review_runner: ReviewRunner = run_panel_learning_model_review_repair,
    trace_writer: TraceWriter = write_trace,
    path_resolver: PathResolver | None = None,
) -> LearningTaskResult:
    """执行只读模型复核任务，并返回与传输层无关的结果。"""

    try:
        resolve_path = path_resolver or (
            lambda value: _resolve_under_project_root(
                value,
                project_root=project_root,
            )
        )
        result = review_runner(
            two_stage_report_path=resolve_path(task_input.two_stage_report_path),
            screenshot_path=resolve_path(task_input.screenshot_path),
            composite_overlay_path=resolve_path(task_input.composite_overlay_path),
            model_profile_id=task_input.model_profile_id,
            timeout_seconds=float(task_input.timeout_seconds),
        )
        result["real_clicks"] = 0
        result["live_fills"] = 0
        result["live_submits"] = 0
        result["trace_path"] = trace_writer(
            category="panel",
            operation="run-learning-model-review-repair",
            payload={
                "success": True,
                "request": task_input.model_dump(),
                "result": {
                    "status": result.get("status"),
                    "calibration_permission": result.get("calibration_permission"),
                    "integrity_gate": result.get("integrity_gate"),
                    "final_stage2_report_path": result.get("final_stage2_report_path"),
                    "final_numbering_revision": result.get("final_numbering_revision"),
                    "real_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                },
            },
            name_hint="learning_model_review_repair",
        )
        outcome = (
            "completed"
            if result.get("calibration_permission") is True
            else "safe_stopped"
        )
        return LearningTaskResult(outcome=outcome, payload=result)
    except Exception as exc:
        return LearningTaskResult(
            outcome="failed",
            payload={
                "status": "safe_stop",
                "calibration_permission": False,
                "real_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
            },
            failure=LearningTaskFailure(
                code="learning_model_review_repair_failed",
                details=str(exc),
            ),
        )
