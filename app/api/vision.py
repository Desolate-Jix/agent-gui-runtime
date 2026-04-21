from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from PIL import Image

from app.core.ocr_service import ocr_service
from app.core.screenshot import screenshot_service
from app.models.request import VisionAnalyzeRequestModel
from app.models.response import APIResponse, ErrorModel, VisionResultData
from app.models.request import OCRRegionRequest
from app.vision.artifacts import save_region_artifacts
from app.vision.factory import VisionProviderFactory
from app.vision.normalizer import normalizer
from app.vision.schemas import ImageSize, VisionAnalyzeRequest

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/ocr_region", response_model=APIResponse)
def ocr_region(request: OCRRegionRequest) -> APIResponse:
    try:
        capture = screenshot_service.capture_window(roi=request.roi, save_image=True)
        result = ocr_service.scan_image(capture["image_path"])
        result.metadata.update(
            {
                "roi": capture.get("roi"),
                "roi_adjusted": capture.get("roi_adjusted"),
                "window_size": capture.get("window_size"),
                "capture_saved_for_ocr": True,
            }
        )
        data = VisionResultData(result=result.to_dict())
        return APIResponse(success=True, message="OCR completed", data=data.model_dump(), error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="OCR failed",
            data=None,
            error=ErrorModel(code="ocr_failed", details=str(exc)),
        )


@router.post("/analyze", response_model=APIResponse)
def analyze_vision(request: VisionAnalyzeRequestModel) -> APIResponse:
    image_path = Path(request.image_path)
    if not image_path.exists():
        return APIResponse(
            success=False,
            message="Image path not found",
            data=None,
            error=ErrorModel(code="image_not_found", details=str(image_path)),
        )

    try:
        config = VisionProviderFactory.load_config()
        provider = VisionProviderFactory.create(mode=request.provider_mode, config=config)
        response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=str(image_path),
                task=request.task,
                app_name=request.app_name,
                goal=request.goal,
                state_hint=request.state_hint,
                provider_mode=request.provider_mode,
                metadata=request.metadata,
            )
        )
        normalized = normalizer.normalize(response.to_dict(), response.provider)
        if normalized.image_size is None:
            with Image.open(image_path) as image:
                normalized.image_size = ImageSize(width=image.width, height=image.height)
        normalized.artifacts = save_region_artifacts(image_path, normalized)
        data = VisionResultData(result=normalized.to_dict())
        return APIResponse(success=True, message="Vision analysis completed", data=data.model_dump(), error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Vision analysis failed",
            data=None,
            error=ErrorModel(code="vision_analyze_failed", details=str(exc)),
        )
