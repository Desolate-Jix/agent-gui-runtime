from __future__ import annotations

from fastapi import APIRouter

from app.core.input_controller import input_controller
from app.core.ocr_engine import ocr_engine
from app.core.template_matcher import template_matcher
from app.core.verifier import verifier
from app.models.request import ClickTemplateRequest, ClickTextRequest
from app.models.response import APIResponse, ActionResultData, ErrorModel

router = APIRouter(prefix="/action", tags=["action"])


@router.post("/click_template", response_model=APIResponse)
def click_template(request: ClickTemplateRequest) -> APIResponse:
    """Locate a template and click its target point."""
    template_result = template_matcher.find_template(request.name, request.roi)
    click_result = input_controller.click_point(0, 0)
    verification = verifier.verify_action("click_template") if request.enable_validation else {"verified": None}

    data = ActionResultData(
        action="click_template",
        result={
            "template": template_result,
            "click": click_result,
            "verification": verification,
        },
    )
    return APIResponse(success=True, message="Template click attempted", data=data.model_dump(), error=None)


@router.post("/click_text", response_model=APIResponse)
def click_text(request: ClickTextRequest) -> APIResponse:
    """Locate text via OCR and click a target point."""
    if request.roi is None:
        return APIResponse(
            success=False,
            message="ROI is required for click_text in the current MVP stub",
            data=None,
            error=ErrorModel(code="missing_roi", details="Provide roi for click_text stub"),
        )

    ocr_result = ocr_engine.ocr_region(request.roi)
    click_result = input_controller.click_point(0, 0)
    verification = verifier.verify_action("click_text") if request.enable_validation else {"verified": None}

    data = ActionResultData(
        action="click_text",
        result={
            "target_text": request.text,
            "ocr": ocr_result,
            "click": click_result,
            "verification": verification,
        },
    )
    return APIResponse(success=True, message="Text click attempted", data=data.model_dump(), error=None)
