from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorModel(BaseModel):
    """Structured error payload returned by the API."""

    code: str
    details: Optional[Any] = None


class APIResponse(BaseModel):
    """Common response envelope for all runtime endpoints."""

    success: bool
    message: str
    data: Optional[Any] = None
    error: Optional[ErrorModel] = None


class HealthData(BaseModel):
    """Health check payload."""

    status: str = Field(default="ok")
    service: str = Field(default="agent-gui-runtime")


class WindowRectModel(BaseModel):
    """Serialized window rectangle."""

    left: int
    top: int
    right: int
    bottom: int


class SessionData(BaseModel):
    """Session/window binding information for the current runtime."""

    bound: bool
    handle: Optional[int] = None
    window_title: Optional[str] = None
    process_id: Optional[int] = None
    process_name: Optional[str] = None
    rect: Optional[WindowRectModel] = None
    is_active: bool = False


class StateData(BaseModel):
    """High-level runtime state summary."""

    bound: bool
    handle: Optional[int] = None
    window_title: Optional[str] = None
    process_id: Optional[int] = None
    process_name: Optional[str] = None
    rect: Optional[WindowRectModel] = None
    is_active: bool = False
    scene_name: Optional[str] = None


class CaptureData(BaseModel):
    """Payload returned by real screenshot capture."""

    image_path: Optional[str] = None
    image_width: int
    image_height: int
    roi: Optional[dict[str, Any]] = None
    roi_adjusted: bool = False
    window_size: Optional[dict[str, int]] = None


class VisionResultData(BaseModel):
    """Generic payload for vision-related operations."""

    result: dict[str, Any] = Field(default_factory=dict)


class ActionResultData(BaseModel):
    """Generic payload for action-related operations."""

    action: str
    result: dict[str, Any] = Field(default_factory=dict)


class WaitResultData(BaseModel):
    """Generic payload for wait/verification operations."""

    scene_name: str
    matched: bool
    elapsed_seconds: float
