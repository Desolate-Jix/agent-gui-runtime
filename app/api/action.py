from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter

from app.actions.known_action_runner import run_known_action
from app.core.action_registry import action_registry
from app.core.input_controller import input_controller
from app.core.ocr_service import ocr_service
from app.core.screenshot import screenshot_service
from app.core.verifier import verifier
from app.core.window_manager import window_manager
from app.models.request import ClickTextRequest
from app.models.response import APIResponse, ActionResultData, ErrorModel
from app.schemas.action_target import ActionTarget
from app.schemas.state import AppState
from app.schemas.validator_profile import ValidatorProfile
from modules.ocr.matching import bbox_center, find_text_matches
from modules.region.geometry import (
    generate_zone_points as generate_zone_points_module,
    locate_mouse_tester_panel as locate_mouse_tester_panel_module,
    normalized_point as normalized_point_module,
    window_rect as window_rect_module,
    window_size_bucket as window_size_bucket_module,
)
from modules.validation.counter import evaluate_counter_result as evaluate_counter_result_module

router = APIRouter(prefix="/action", tags=["action"])

CACHE_DIR = Path("logs/region-click-cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CASES_DIR = Path("logs/region-click-cases")
CASES_DIR.mkdir(parents=True, exist_ok=True)

RegionClickPanelLocator = Callable[[Any], dict[str, Any]]
RegionClickZoneResolver = Callable[[dict[str, Any]], dict[str, Any]]
RegionClickPointStrategy = Callable[[dict[str, Any], Optional[dict[str, float]]], list[dict[str, Any]]]
RegionClickValidator = Callable[[list[str], list[str]], dict[str, Any]]


def _window_rect(bound: Any) -> dict[str, int]:
    return window_rect_module(bound)


def _window_size_bucket(rect: dict[str, int]) -> str:
    return window_size_bucket_module(rect)


def _locate_mouse_tester_panel(bound: Any) -> dict[str, Any]:
    return locate_mouse_tester_panel_module(bound)


def _generate_zone_points(zone: dict[str, Any], preferred_norm_point: Optional[dict[str, float]] = None) -> list[dict[str, Any]]:
    return generate_zone_points_module(zone, preferred_norm_point)


def _counter_value(texts: list[str]) -> Optional[int]:
    from modules.validation.counter import counter_value

    return counter_value(texts)


def _evaluate_counter_result(before_numeric_texts: list[str], after_numeric_texts: list[str]) -> dict[str, Any]:
    return evaluate_counter_result_module(before_numeric_texts, after_numeric_texts)


def _normalized_point(zone: dict[str, Any], point: dict[str, Any]) -> dict[str, float]:
    return normalized_point_module(zone, point)


def _load_region_click_memory(case_name: str, bucket: str) -> Optional[dict[str, Any]]:
    path = CACHE_DIR / f"{case_name}-{bucket}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_region_click_memory(case_name: str, bucket: str, payload: dict[str, Any]) -> str:
    path = CACHE_DIR / f"{case_name}-{bucket}.json"
    payload = {**payload, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _capture_bound_window_image(bound: Any, name_prefix: str) -> Optional[str]:
    capture = screenshot_service.capture_window(save_image=True)
    image_path = capture.get("image_path")
    if not image_path:
        return None
    return str(Path(image_path).resolve())


def _ensure_mouse_tester_state_assets(bound: Any) -> tuple[Optional[AppState], list[ActionTarget], dict[str, ValidatorProfile]]:
    state_id = f"mousetester_main_{_window_size_bucket(_window_rect(bound))}"
    state = action_registry.load_state_hint(state_id)
    if state is None:
        state = AppState(
            state_id=state_id,
            app_name="MouseTesterWeb",
            state_name="main_page",
            window_size_bucket=_window_size_bucket(_window_rect(bound)),
            fingerprint=None,
            panel_profiles=[],
            known_action_ids=["click_mouse_tester_left_region", "click_mouse_tester_left_region_alt"],
            tags=["legacy-reduced", "manual-zone"],
            version=1,
        )
        action_registry.save_state_hint(state)

    action_specs = [
        {
            "action_id": "click_mouse_tester_left_region",
            "action_name": "Click MouseTester Left Region",
            "zone": {"nx": 0.10, "ny": 0.15, "nw": 0.35, "nh": 0.40},
            "validator_id": "validator_mouse_tester_left_counter",
        },
        {
            "action_id": "click_mouse_tester_left_region_alt",
            "action_name": "Click MouseTester Left Region Alt",
            "zone": {"nx": 0.14, "ny": 0.18, "nw": 0.28, "nh": 0.32},
            "validator_id": "validator_mouse_tester_left_counter",
        },
    ]

    actions: list[ActionTarget] = []
    for spec in action_specs:
        action = action_registry.load_action(spec["action_id"])
        if action is None:
            action = ActionTarget(
                action_id=spec["action_id"],
                state_id=state.state_id,
                action_name=spec["action_name"],
                target_kind="region",
                panel_locator_profile={
                    "mode": "window_relative_rect",
                    "coord_space": "window",
                    "nx": 0.16,
                    "ny": 0.48,
                    "nw": 0.48,
                    "nh": 0.40,
                },
                zone_resolver_profile={"mode": "panel_relative_rect", "coord_space": "panel", **spec["zone"]},
                point_strategy_profile={"mode": "grid", "rows": 3, "cols": 3, "inset": 0.18, "prefer_memory": True},
                validator_profile_id=spec["validator_id"],
                successful_points=[],
                forbidden_points=[],
                local_patch_template_path=None,
                notes="Reduced legacy region action kept as reusable click fallback.",
                version=1,
            )
            action_registry.save_action(action)
        actions.append(action)

    validator = action_registry.load_validator("validator_mouse_tester_left_counter")
    if validator is None:
        validator = ValidatorProfile(
            validator_profile_id="validator_mouse_tester_left_counter",
            name="MouseTester Left Counter Validator",
            ocr_roi=None,
            roi_diff_threshold=0.01,
            strict_rule={"type": "counter_change_or_visual_diff"},
            weak_rule={"type": "visual_diff"},
            version=1,
        )
        action_registry.save_validator(validator)

    validators = {action.action_id: validator for action in actions}
    return state, actions, validators


@router.post("/click_text", response_model=APIResponse)
def click_text(request: ClickTextRequest) -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data=None,
            error=ErrorModel(code="no_bound_window", details="Bind a target window before calling /action/click_text"),
        )

    try:
        capture = screenshot_service.capture_window(roi=request.roi, save_image=True)
        ocr_result = ocr_service.scan_image(capture["image_path"])
        matches = find_text_matches(ocr_result, request.text, partial_match=request.partial_match)
        if not matches:
            return APIResponse(
                success=False,
                message="Requested text was not found in OCR result",
                data={
                    "query": request.text,
                    "partial_match": request.partial_match,
                    "matches": [match.to_dict() for match in find_text_matches(ocr_result, request.text, partial_match=True)],
                    "ocr_result": ocr_result.to_dict(),
                },
                error=ErrorModel(code="text_not_found", details=request.text),
            )

        roi_payload = capture.get("roi") or {}
        attempts: list[dict[str, Any]] = []
        selected_result: Optional[dict[str, Any]] = None
        candidate_matches = matches[: request.max_retries]

        for index, candidate in enumerate(candidate_matches, start=1):
            center = bbox_center(candidate.bbox)
            window_x = int(center["x"] + int(roi_payload.get("x", 0)))
            window_y = int(center["y"] + int(roi_payload.get("y", 0)))

            before_state = verifier.capture_pre_action_state(roi=request.roi) if request.enable_validation else None
            click_result = input_controller.click_point(window_x, window_y, move_before_click=True, settle_ms=100, hold_ms=70)
            verification = (
                verifier.verify_action(
                    f"click_text:{request.text}",
                    roi=request.roi,
                    before_state=before_state,
                    click_result=click_result,
                )
                if request.enable_validation
                else {"verified": None, "verification_skipped": True}
            )
            success = True if not request.enable_validation else bool(verification.get("verified"))
            attempt = {
                "attempt": index,
                "match": candidate.to_dict(),
                "window_point": {"x": window_x, "y": window_y},
                "click_result": click_result,
                "verification": verification,
                "success": success,
            }
            attempts.append(attempt)
            if success:
                selected_result = attempt
                break

        if selected_result is None:
            return APIResponse(
                success=False,
                message="Text candidates were clicked but verification did not succeed",
                data={
                    "query": request.text,
                    "partial_match": request.partial_match,
                    "capture": {
                        "image_path": capture.get("image_path"),
                        "roi": capture.get("roi"),
                        "roi_adjusted": capture.get("roi_adjusted"),
                        "window_size": capture.get("window_size"),
                    },
                    "ocr_match_count": len(ocr_result.matches),
                    "attempts": attempts,
                },
                error=ErrorModel(code="click_text_not_verified", details=request.text),
            )

        result = {
            "query": request.text,
            "partial_match": request.partial_match,
            "selected_match": selected_result["match"],
            "window_point": selected_result["window_point"],
            "capture": {
                "image_path": capture.get("image_path"),
                "roi": capture.get("roi"),
                "roi_adjusted": capture.get("roi_adjusted"),
                "window_size": capture.get("window_size"),
            },
            "ocr_match_count": len(ocr_result.matches),
            "attempts": attempts,
            "click_result": selected_result["click_result"],
            "verification": selected_result["verification"],
        }
        data = ActionResultData(action="click_text", result=result)
        return APIResponse(success=True, message="Text clicked successfully", data=data.model_dump(), error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Text click failed",
            data=None,
            error=ErrorModel(code="click_text_failed", details=str(exc)),
        )


def _run_region_click(
    *,
    case_name: str,
    bound: Any,
    panel_locator: RegionClickPanelLocator,
    zone_resolver: RegionClickZoneResolver,
    point_strategy: RegionClickPointStrategy,
    validator: RegionClickValidator,
    validator_profile: Optional[ValidatorProfile] = None,
    max_retries: int = 1,
) -> dict[str, Any]:
    panel = panel_locator(bound)
    zone = zone_resolver(panel)
    bucket = _window_size_bucket(_window_rect(bound))
    memory = _load_region_click_memory(case_name, bucket) or {}
    preferred_norm_point = memory.get("preferred_norm_point")
    points = point_strategy(zone, preferred_norm_point)

    before_state = verifier.capture_pre_action_state()
    retries: list[dict[str, Any]] = []

    for attempt_index, point in enumerate(points[: max(1, len(points))]):
        click_result = input_controller.click_point(point["x"], point["y"], move_before_click=True, settle_ms=100, hold_ms=70)
        verification = verifier.verify_action(case_name, before_state=before_state, click_result=click_result)
        diff_changed = verification.get("diff", {}).get("changed")
        counter_eval = validator([], [])
        if diff_changed and not counter_eval.get("weak_success"):
            counter_eval["weak_success"] = True
        if diff_changed and not counter_eval.get("strict_success"):
            counter_eval["strict_success"] = True
        success = bool(counter_eval.get("strict_success") or counter_eval.get("weak_success"))

        retry_entry = {
            "attempt": attempt_index + 1,
            "point": point,
            "click": click_result,
            "verification": verification,
            "counter_eval": counter_eval,
            "success": success,
        }
        retries.append(retry_entry)

        if success:
            memory_path = _save_region_click_memory(
                case_name,
                bucket,
                {
                    "preferred_norm_point": _normalized_point(zone, point),
                    "last_success_point": point,
                    "validator_profile_id": validator_profile.validator_profile_id if validator_profile else None,
                },
            )
            case_path = str((CASES_DIR / f"{case_name}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json").resolve())
            Path(case_path).write_text(json.dumps(retry_entry, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "success": True,
                "panel": panel,
                "zone": zone,
                "points": points,
                "selected_point": point,
                "strict_success": bool(counter_eval.get("strict_success")),
                "weak_success": bool(counter_eval.get("weak_success")),
                "verification": verification,
                "roi_diff_score": verification.get("diff", {}).get("count"),
                "retries": retries,
                "memory_path": memory_path,
                "case_path": case_path,
            }

        if attempt_index + 1 >= max_retries and max_retries > 0:
            break

    return {
        "success": False,
        "panel": panel,
        "zone": zone,
        "points": points,
        "retries": retries,
    }


@router.post("/click_mouse_tester_left_region", response_model=APIResponse)
def click_mouse_tester_left_region() -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(success=False, message="No bound window is currently available", data=None, error=ErrorModel(code="no_bound_window", details="Bind a MouseTester window before calling /action/click_mouse_tester_left_region"))

    state_before, actions, validators = _ensure_mouse_tester_state_assets(bound)

    primary_action = next((a for a in actions if a.action_id == "click_mouse_tester_left_region"), None)
    alt_action = next((a for a in actions if a.action_id == "click_mouse_tester_left_region_alt"), None)

    def execute_with_action(action_target: ActionTarget) -> dict[str, Any]:
        zone_profile = action_target.zone_resolver_profile

        def dynamic_zone(panel: dict[str, Any]) -> dict[str, Any]:
            return {
                "x": int(panel["x"] + panel["width"] * float(zone_profile.get("nx", 0.0))),
                "y": int(panel["y"] + panel["height"] * float(zone_profile.get("ny", 0.0))),
                "width": max(1, int(panel["width"] * float(zone_profile.get("nw", 1.0)))),
                "height": max(1, int(panel["height"] * float(zone_profile.get("nh", 1.0)))),
                "source": action_target.action_id,
            }

        return run_known_action(
            app_name="MouseTesterWeb",
            state_before=state_before,
            action_target=action_target,
            validator_profile=validators.get(action_target.action_id),
            capture_state_image=lambda prefix: _capture_bound_window_image(bound, prefix),
            get_window_bucket=lambda: _window_size_bucket(_window_rect(bound)),
            execute_action=lambda: _run_region_click(
                case_name=action_target.action_id,
                bound=bound,
                panel_locator=_locate_mouse_tester_panel,
                zone_resolver=dynamic_zone,
                point_strategy=_generate_zone_points,
                validator=_evaluate_counter_result,
                validator_profile=validators.get(action_target.action_id),
            ),
        )

    try:
        result = execute_with_action(primary_action) if primary_action else {"success": False}
        if not result.get("success") and alt_action is not None:
            result["fallback_attempted_action_id"] = alt_action.action_id
            fallback_result = execute_with_action(alt_action)
            result["fallback_result"] = {
                "success": fallback_result.get("success"),
                "action_target_id": fallback_result.get("action_target_id"),
                "strict_success": fallback_result.get("strict_success"),
                "weak_success": fallback_result.get("weak_success"),
            }
            if fallback_result.get("success"):
                result = fallback_result
                result["used_fallback_action"] = True
    except Exception as exc:
        return APIResponse(success=False, message="Region click execution failed", data=None, error=ErrorModel(code="region_click_failed", details=str(exc)))

    if not result["success"]:
        return APIResponse(success=False, message="MouseTester left region click did not change the counter", data=result, error=ErrorModel(code="counter_not_changed", details="No known action target changed the target counter; generic region_click path remains available as fallback"))

    data = ActionResultData(action="click_mouse_tester_left_region", result=result)
    return APIResponse(success=True, message="MouseTester left region clicked successfully", data=data.model_dump(), error=None)
