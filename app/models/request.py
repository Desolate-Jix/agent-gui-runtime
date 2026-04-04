from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ROIModel(BaseModel):
    """Rectangular region of interest within the bound window."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class BindWindowRequest(BaseModel):
    """Request model for binding the runtime to a target window."""

    process_name: Optional[str] = None
    title: Optional[str] = None


class CaptureWindowRequest(BaseModel):
    """Request model for capturing the currently bound window."""

    roi: Optional[ROIModel] = None
    save_image: bool = True


class FindTemplateRequest(BaseModel):
    """Request model for template matching within an optional ROI."""

    name: str = Field(min_length=1)
    roi: Optional[ROIModel] = None


class OCRRegionRequest(BaseModel):
    """Request model for OCR within a target ROI."""

    roi: ROIModel
    save_image: bool = True
    debug: bool = False


class ClickTemplateRequest(BaseModel):
    """Request model for clicking a matched template."""

    name: str = Field(min_length=1)
    roi: Optional[ROIModel] = None
    enable_validation: bool = True


class ClickTextRequest(BaseModel):
    """Request model for locating text via OCR and clicking it."""

    text: str = Field(min_length=1)
    roi: Optional[ROIModel] = None
    enable_validation: bool = True


class WaitForSceneRequest(BaseModel):
    """Request model for waiting until a named scene is detected."""

    scene_name: str = Field(min_length=1)
    timeout: float = Field(default=3.0, gt=0)
