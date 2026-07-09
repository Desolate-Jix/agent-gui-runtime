from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from app.core.window_manager import BoundWindow, window_manager
from app.api.models.request import BindWindowRequest, ResizeBoundWindowRequest
from app.api.models.response import APIResponse, ErrorModel, SessionData, WindowRectModel
from app.operation.runtime_context import build_operation_runtime_context, operation_trace_link

router = APIRouter(prefix="/session", tags=["session"])


@router.get("/windows", response_model=APIResponse)
def list_windows() -> APIResponse:
    """List visible top-level windows explicitly for debugging and selection."""
    candidates = window_manager.list_visible_windows()
    return APIResponse(success=True, message="Visible windows listed", data={"candidates": candidates}, error=None)



def _to_session_data(bound: BoundWindow) -> SessionData:
    """Convert a bound window object into API response data."""
    return SessionData(
        bound=True,
        handle=bound.handle,
        window_title=bound.title,
        process_id=bound.process_id,
        process_name=bound.process_name,
        rect=WindowRectModel(
            left=bound.rect.left,
            top=bound.rect.top,
            right=bound.rect.right,
            bottom=bound.rect.bottom,
        ),
        is_active=bound.is_active,
    )


@router.post("/bind_window", response_model=APIResponse)
def bind_window(request: BindWindowRequest) -> APIResponse:
    """Bind the runtime to a target window session."""
    candidates = window_manager.list_visible_windows()

    if not request.process_name and not request.title:
        return APIResponse(
            success=False,
            message="No binding criteria provided",
            data={"candidates": candidates},
            error=ErrorModel(
                code="missing_binding_criteria",
                details="Provide process_name and/or title, or inspect candidates in data.candidates",
            ),
        )

    try:
        bound = window_manager.bind_window(request.process_name, request.title)
        data = _to_session_data(bound).model_dump()
        data["candidates"] = candidates
        operation_context = build_operation_runtime_context(
            request=request,
            skill_id="bind_window",
            semantic_action="bind_window",
            side_effect_class="navigation",
            requires_gate=False,
            window_binding_id=f"window:{int(bound.handle)}",
            viewport_size={
                "width": int(bound.rect.right - bound.rect.left),
                "height": int(bound.rect.bottom - bound.rect.top),
            },
        )
        data["operation_context"] = operation_context
        data["operation_trace_link"] = operation_trace_link(operation_context, result_status="success")
        return APIResponse(success=True, message="Window bound", data=data, error=None)
    except ValueError as exc:
        logger.warning("Window bind did not match any visible candidate: {}", exc)
        return APIResponse(
            success=False,
            message="Window not found",
            data={"candidates": candidates},
            error=ErrorModel(code="window_not_found", details=str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive skeleton handling
        logger.exception("Failed to bind window")
        return APIResponse(
            success=False,
            message="Failed to bind window",
            data={"candidates": candidates},
            error=ErrorModel(code="bind_window_failed", details=str(exc)),
        )


@router.post("/resize_bound_window", response_model=APIResponse)
def resize_bound_window(request: ResizeBoundWindowRequest) -> APIResponse:
    """Resize the currently bound target window for stability and drift testing."""
    try:
        before = window_manager.get_bound_window()
        resized = window_manager.resize_bound_window(
            width=request.width,
            height=request.height,
            left=request.left,
            top=request.top,
            focus=request.focus,
        )
        return APIResponse(
            success=True,
            message="Bound window resized",
            data={
                "contract_version": "bound_window_resize_v1",
                "requested": request.model_dump(),
                "before": _to_session_data(before).model_dump() if before is not None else None,
                "after": _to_session_data(resized).model_dump(),
            },
            error=None,
        )
    except Exception as exc:
        logger.warning("Failed to resize bound window: {}", exc)
        return APIResponse(
            success=False,
            message="Failed to resize bound window",
            data={"requested": request.model_dump()},
            error=ErrorModel(code="window_resize_failed", details=str(exc)),
        )
