from __future__ import annotations

from fastapi import APIRouter

from app.core.model_server import check_model_server, ensure_model_server, load_model_profiles, profile_for_stage, stop_model_server
from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.models.request import ModelServerRequest, RuntimePrepareRequest
from app.models.response import APIResponse, ErrorModel

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/models", response_model=APIResponse)
def model_status() -> APIResponse:
    """Return configured local vision model profiles and current /v1/models status."""
    timer = RuntimeTimer()
    results = []
    with timer.step("load_model_profiles"):
        profiles = load_model_profiles()
    for profile in profiles:
        with timer.step("check_model_server", profile_id=profile.get("profile_id")):
            results.append({"profile": profile, "status": check_model_server(profile)})
    return APIResponse(
        success=True,
        message="Model server status collected",
        data={"contract_version": "runtime_model_status_v1", "models": results, "timings": timer.to_dict()},
        error=None,
    )


@router.post("/models/start", response_model=APIResponse)
def start_model(request: ModelServerRequest) -> APIResponse:
    """Start the local vision model for a stage when it is not already reachable."""
    timer = RuntimeTimer()
    try:
        with timer.step("ensure_model_server", stage=request.stage, profile_id=request.profile_id):
            result = ensure_model_server(
                stage=request.stage,
                profile_id=request.profile_id,
                wait_until_ready=request.wait_until_ready,
                wait_seconds=request.wait_seconds,
            )
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="runtime",
            operation="start_model",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.stage,
        )
        return APIResponse(success=True, message="Model server ensure completed", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="runtime",
            operation="start_model",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.stage,
        )
        return APIResponse(
            success=False,
            message="Model server start failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="model_server_start_failed", details=str(exc)),
        )


@router.post("/models/stop", response_model=APIResponse)
def stop_model(request: ModelServerRequest) -> APIResponse:
    """Stop the local vision model profile for a stage when possible."""
    timer = RuntimeTimer()
    try:
        with timer.step("resolve_model_profile", stage=request.stage, profile_id=request.profile_id):
            profile = profile_for_stage(request.stage, request.profile_id)
        with timer.step("stop_model_server", stage=request.stage, profile_id=profile.get("profile_id")):
            result = stop_model_server(profile)
        result["stage"] = request.stage
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="runtime",
            operation="stop_model",
            payload={"success": result.get("returncode") == 0, "request": request.model_dump(), "result": result},
            name_hint=request.stage,
        )
        if result.get("returncode") != 0:
            return APIResponse(
                success=False,
                message="Model server stop failed",
                data=result,
                error=ErrorModel(code="model_server_stop_failed", details=result.get("stderr")),
            )
        return APIResponse(success=True, message="Model server stop completed", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="runtime",
            operation="stop_model",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.stage,
        )
        return APIResponse(
            success=False,
            message="Model server stop failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="model_server_stop_failed", details=str(exc)),
        )


@router.post("/prepare", response_model=APIResponse)
def prepare_runtime(request: RuntimePrepareRequest) -> APIResponse:
    """Prepare dependencies that an API-first agent should check before acting."""
    timer = RuntimeTimer()
    stage_results = []
    if request.start_models:
        for stage in request.stages:
            with timer.step("ensure_model_server", stage=stage):
                stage_results.append(
                    ensure_model_server(
                        stage=stage,
                        wait_until_ready=request.wait_until_ready,
                        wait_seconds=request.wait_seconds,
                    )
                )
    else:
        for stage in request.stages:
            with timer.step("resolve_model_profile", stage=stage):
                profile = profile_for_stage(stage)
            with timer.step("check_model_server", stage=stage, profile_id=profile.get("profile_id")):
                stage_results.append({"stage": stage, "profile": profile, "status": check_model_server(profile)})
    result = {
        "contract_version": "runtime_prepare_v1",
        "runtime": {"status": "ok", "service": "agent-gui-runtime"},
        "start_models": request.start_models,
        "stages": stage_results,
    }
    result["timings"] = timer.to_dict()
    result["trace_path"] = write_trace(
        category="runtime",
        operation="prepare_runtime",
        payload={"success": True, "request": request.model_dump(), "result": result},
        name_hint="prepare",
    )
    return APIResponse(success=True, message="Runtime preparation completed", data=result, error=None)
