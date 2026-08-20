from __future__ import annotations

from typing import Any

from app.learn.workflow_contracts import LearningTaskResult
from app.operation.observe.contracts import ObserveScreenTaskResult


def observe_result_to_legacy_response(
    result: ObserveScreenTaskResult,
) -> dict[str, Any]:
    if result.failure is not None:
        return {
            "success": False,
            "message": "Screen observation failed",
            "data": result.payload,
            "error": result.failure.model_dump(mode="json"),
        }
    return {
        "success": True,
        "message": "Screen observation completed",
        "data": {"result": result.payload},
        "error": None,
    }


def model_review_result_to_legacy_response(
    result: LearningTaskResult,
) -> dict[str, Any]:
    if result.failure is not None:
        return {
            "success": False,
            "message": "Learning model review and repair failed",
            "data": result.payload,
            "error": result.failure.model_dump(mode="json"),
        }
    return {
        "success": True,
        "message": (
            "Learning model review and repair ready for calibration"
            if result.outcome == "completed"
            else "Learning model review and repair stopped safely"
        ),
        "data": result.payload,
        "error": None,
    }


def recognition_result_to_legacy_response(
    result: LearningTaskResult,
) -> dict[str, Any]:
    if result.failure is not None:
        return {
            "success": False,
            "message": "Learning recognition draft failed",
            "data": result.payload,
            "error": result.failure.model_dump(mode="json"),
        }
    return {
        "success": True,
        "message": "Learning recognition draft saved",
        "data": result.payload,
        "error": None,
    }


def two_stage_result_to_legacy_response(
    result: LearningTaskResult,
) -> dict[str, Any]:
    if result.failure is not None:
        return {
            "success": False,
            "message": "Two-stage learning understanding failed",
            "data": result.payload,
            "error": result.failure.model_dump(mode="json"),
        }
    return {
        "success": True,
        "message": "Two-stage learning understanding generated",
        "data": result.payload,
        "error": None,
    }
