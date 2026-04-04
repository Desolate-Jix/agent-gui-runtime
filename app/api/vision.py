from __future__ import annotations

from fastapi import APIRouter

from app.core.ocr_engine import ocr_engine
from app.core.template_matcher import template_matcher
from app.models.request import FindTemplateRequest, OCRRegionRequest
from app.models.response import APIResponse, ErrorModel, VisionResultData

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/find_template", response_model=APIResponse)
def find_template(request: FindTemplateRequest) -> APIResponse:
    """Find a configured template within the current bound window."""
    result = template_matcher.find_template(request.name, request.roi)
    data = VisionResultData(result=result)
    return APIResponse(success=True, message="Template search completed", data=data.model_dump(), error=None)


@router.post("/ocr_region", response_model=APIResponse)
def ocr_region(request: OCRRegionRequest) -> APIResponse:
    """Run OCR on the provided region of interest."""
    try:
        result = ocr_engine.ocr_region(request.roi, save_image=request.save_image, debug=request.debug)
        data = VisionResultData(result=result)
        return APIResponse(success=True, message="OCR completed", data=data.model_dump(), error=None)
    except ValueError as exc:
        return APIResponse(
            success=False,
            message="OCR failed",
            data=None,
            error=ErrorModel(code="ocr_failed", details=str(exc)),
        )
    except RuntimeError as exc:
        return APIResponse(
            success=False,
            message="OCR backend unavailable",
            data=None,
            error=ErrorModel(code="ocr_backend_unavailable", details=str(exc)),
        )
