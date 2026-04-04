from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from app.core.window_manager import BoundWindow, window_manager
from app.models.request import BindWindowRequest
from app.models.response import APIResponse, ErrorModel, SessionData, WindowRectModel

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
