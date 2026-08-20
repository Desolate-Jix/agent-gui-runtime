from __future__ import annotations

from typing import Any

from app.operation.observe.contracts import ObserveScreenTaskInput


def _should_learn_visual_assets(request: Any) -> bool:
    if getattr(request, "agent_mode", None) != "learn":
        return False
    metadata = getattr(request, "metadata", None)
    if isinstance(metadata, dict):
        visual_assets = metadata.get("visual_assets")
        if isinstance(visual_assets, dict) and visual_assets.get("enabled") is False:
            return False
    return True


def _safe_visual_asset_run_name(value: Any) -> str:
    text = str(value or "screen").strip()
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text)
    return safe.strip("_")[:80] or "screen"


def _skipped_visual_asset_learning(
    *,
    image_path: str,
    reason: str,
    app_id: Any,
    page_type: Any,
    learn_depth: Any,
    error_detail: str | None = None,
) -> dict[str, Any]:
    payload = {
        "contract_version": "visual_asset_learning_v1",
        "status": "skipped",
        "reason": reason,
        "source_image_path": str(image_path),
        "app_id": app_id,
        "page_type": page_type,
        "learn_depth": learn_depth,
        "visual_assets": {
            "contract_version": "visual_asset_store_v1",
            "asset_status_default": "skipped",
            "asset_match_is_evidence_only": True,
            "asset_can_authorize_click": False,
            "assets": [],
        },
        "summary": {
            "candidate_count": 0,
            "asset_count": 0,
            "skipped_count": 0,
            "artifact_is_authorization": False,
        },
    }
    if error_detail:
        payload["error_detail"] = error_detail
    return payload


def should_learn_visual_assets(task: ObserveScreenTaskInput) -> bool:
    return _should_learn_visual_assets(task)


def safe_visual_asset_run_name(value: str) -> str:
    return _safe_visual_asset_run_name(value)


def skipped_visual_asset_learning(
    *,
    image_path: str,
    reason: str,
    app_id: str | None,
    page_type: str | None,
    learn_depth: str,
    error_detail: str | None = None,
) -> dict[str, Any]:
    return _skipped_visual_asset_learning(
        image_path=image_path,
        reason=reason,
        app_id=app_id,
        page_type=page_type,
        learn_depth=learn_depth,
        error_detail=error_detail,
    )
