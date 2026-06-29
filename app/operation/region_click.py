from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.input_controller import input_controller
from app.core.verifier import verifier
from app.operation.validator_profile import ValidatorProfile
from modules.region.geometry import normalized_point as normalized_point_module
from modules.region.geometry import window_rect as window_rect_module
from modules.region.geometry import window_size_bucket as window_size_bucket_module


REGION_CLICK_CACHE_DIR = Path("logs/region-click-cache")
REGION_CLICK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
REGION_CLICK_CASES_DIR = Path("logs/region-click-cases")
REGION_CLICK_CASES_DIR.mkdir(parents=True, exist_ok=True)

RegionClickPanelLocator = Callable[[Any], dict[str, Any]]
RegionClickZoneResolver = Callable[[dict[str, Any]], dict[str, Any]]
RegionClickPointStrategy = Callable[[dict[str, Any], Optional[dict[str, float]]], list[dict[str, Any]]]
RegionClickValidator = Callable[[list[str], list[str]], dict[str, Any]]


def load_region_click_memory(case_name: str, bucket: str) -> Optional[dict[str, Any]]:
    path = REGION_CLICK_CACHE_DIR / f"{case_name}-{bucket}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_region_click_memory(case_name: str, bucket: str, payload: dict[str, Any]) -> str:
    path = REGION_CLICK_CACHE_DIR / f"{case_name}-{bucket}.json"
    payload = {**payload, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def run_region_click(
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
    bucket = window_size_bucket_module(window_rect_module(bound))
    memory = load_region_click_memory(case_name, bucket) or {}
    preferred_norm_point = memory.get("preferred_norm_point")
    points = point_strategy(zone, preferred_norm_point)

    before_state = verifier.capture_pre_action_state(action_name=case_name)
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
            memory_path = save_region_click_memory(
                case_name,
                bucket,
                {
                    "preferred_norm_point": normalized_point_module(zone, point),
                    "last_success_point": point,
                    "validator_profile_id": validator_profile.validator_profile_id if validator_profile else None,
                },
            )
            case_path = str((REGION_CLICK_CASES_DIR / f"{case_name}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json").resolve())
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
