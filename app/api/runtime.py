from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.model_server import check_model_server, ensure_model_server, load_model_profiles, profile_for_stage, stop_model_server
from app.core.gpu_resources import build_model_resource_preflight
from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.gate.contracts import build_gate_contract_catalog
from app.api.models.request import ModelServerRequest, RuntimePrepareRequest
from app.api.models.response import APIResponse, ErrorModel
from app.learn.model_trial import build_learning_model_trial
from app.operation.skills import build_operation_skill_catalog
from app.agent.prompts import (
    PromptRollbackRequest,
    PromptVersionSave,
    diff_agent_prompt_versions,
    get_agent_prompt,
    get_agent_prompt_version,
    list_agent_prompt_versions,
    list_agent_prompts,
    rollback_agent_prompt_version,
    save_agent_prompt_version,
)
from app.runtime_architecture import build_default_architecture_spec
from app.runtime_architecture.profiles import get_app_profile, list_app_profiles

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/architecture", response_model=APIResponse)
def runtime_architecture() -> APIResponse:
    spec = build_default_architecture_spec()
    return APIResponse(
        success=True,
        message="Runtime architecture loaded",
        data=spec.model_dump(),
        error=None,
    )


@router.get("/operation_skills", response_model=APIResponse)
def operation_skills(app_id: str | None = Query(default=None)) -> APIResponse:
    try:
        catalog = build_operation_skill_catalog(app_id)
        return APIResponse(
            success=True,
            message="Operation skills listed",
            data=catalog,
            error=None,
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="App profile not found",
            data={"app_id": app_id},
            error=ErrorModel(code="app_profile_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Operation skills failed",
            data={"app_id": app_id},
            error=ErrorModel(code="operation_skills_failed", details=str(exc)),
        )


@router.get("/gate_contracts", response_model=APIResponse)
def gate_contracts(app_id: str | None = Query(default=None)) -> APIResponse:
    try:
        catalog = build_gate_contract_catalog(app_id)
        return APIResponse(
            success=True,
            message="Gate contracts listed",
            data=catalog,
            error=None,
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="App profile not found",
            data={"app_id": app_id},
            error=ErrorModel(code="app_profile_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Gate contracts failed",
            data={"app_id": app_id},
            error=ErrorModel(code="gate_contracts_failed", details=str(exc)),
        )


@router.get("/agent_prompts", response_model=APIResponse)
def agent_prompts() -> APIResponse:
    prompts = list_agent_prompts()
    return APIResponse(
        success=True,
        message="Agent prompts listed",
        data={"contract_version": "runtime_agent_prompts_v1", "prompts": prompts},
        error=None,
    )


@router.get("/agent_prompts/{prompt_id}", response_model=APIResponse)
def agent_prompt(prompt_id: str) -> APIResponse:
    try:
        prompt, path = get_agent_prompt(prompt_id)
        return APIResponse(
            success=True,
            message="Agent prompt loaded",
            data={
                "contract_version": "runtime_agent_prompt_v1",
                "path": str(path),
                "prompt": prompt.model_dump(),
            },
            error=None,
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt not found",
            data={"prompt_id": prompt_id},
            error=ErrorModel(code="agent_prompt_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Agent prompt load failed",
            data={"prompt_id": prompt_id},
            error=ErrorModel(code="agent_prompt_load_failed", details=str(exc)),
        )


@router.get("/agent_prompts/{prompt_id}/versions", response_model=APIResponse)
def agent_prompt_versions(prompt_id: str) -> APIResponse:
    try:
        versions = list_agent_prompt_versions(prompt_id)
        return APIResponse(
            success=True,
            message="Agent prompt versions listed",
            data={
                "contract_version": "runtime_agent_prompt_versions_v1",
                "prompt_id": prompt_id,
                "versions": versions,
            },
            error=None,
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt not found",
            data={"prompt_id": prompt_id},
            error=ErrorModel(code="agent_prompt_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Agent prompt versions failed",
            data={"prompt_id": prompt_id},
            error=ErrorModel(code="agent_prompt_versions_failed", details=str(exc)),
        )


@router.get("/agent_prompts/{prompt_id}/versions/{version}", response_model=APIResponse)
def agent_prompt_version(prompt_id: str, version: str) -> APIResponse:
    try:
        prompt, path = get_agent_prompt_version(prompt_id, version)
        return APIResponse(
            success=True,
            message="Agent prompt version loaded",
            data={
                "contract_version": "runtime_agent_prompt_version_v1",
                "path": str(path),
                "prompt": prompt.model_dump(),
            },
            error=None,
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt version not found",
            data={"prompt_id": prompt_id, "version": version},
            error=ErrorModel(code="agent_prompt_version_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Agent prompt version load failed",
            data={"prompt_id": prompt_id, "version": version},
            error=ErrorModel(code="agent_prompt_version_load_failed", details=str(exc)),
        )


@router.get("/agent_prompts/{prompt_id}/diff", response_model=APIResponse)
def agent_prompt_diff(
    prompt_id: str,
    from_version: str = Query(min_length=1),
    to_version: str = Query(min_length=1),
) -> APIResponse:
    try:
        diff = diff_agent_prompt_versions(prompt_id, from_version, to_version)
        return APIResponse(success=True, message="Agent prompt diff generated", data=diff, error=None)
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt diff version not found",
            data={"prompt_id": prompt_id, "from_version": from_version, "to_version": to_version},
            error=ErrorModel(code="agent_prompt_version_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Agent prompt diff failed",
            data={"prompt_id": prompt_id, "from_version": from_version, "to_version": to_version},
            error=ErrorModel(code="agent_prompt_diff_failed", details=str(exc)),
        )


@router.post("/agent_prompts/{prompt_id}/rollback", response_model=APIResponse)
def rollback_agent_prompt(prompt_id: str, request: PromptRollbackRequest) -> APIResponse:
    try:
        prompt, path, trace_path = rollback_agent_prompt_version(prompt_id, request)
        return APIResponse(
            success=True,
            message="Agent prompt rollback version saved",
            data={
                "contract_version": "runtime_agent_prompt_rollback_v1",
                "path": str(path),
                "trace_path": trace_path,
                "prompt": prompt.model_dump(),
            },
            error=None,
        )
    except FileExistsError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt rollback target already exists",
            data={"prompt_id": prompt_id, "new_version": request.new_version},
            error=ErrorModel(code="agent_prompt_version_exists", details=str(exc)),
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt rollback source not found",
            data={"prompt_id": prompt_id, "target_version": request.target_version},
            error=ErrorModel(code="agent_prompt_version_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Agent prompt rollback failed",
            data={"prompt_id": prompt_id},
            error=ErrorModel(code="agent_prompt_rollback_failed", details=str(exc)),
        )


@router.post("/agent_prompts/{prompt_id}/versions", response_model=APIResponse)
def save_agent_prompt(prompt_id: str, request: PromptVersionSave) -> APIResponse:
    try:
        prompt, path, trace_path = save_agent_prompt_version(prompt_id, request)
        return APIResponse(
            success=True,
            message="Agent prompt version saved",
            data={
                "contract_version": "runtime_agent_prompt_save_v1",
                "path": str(path),
                "trace_path": trace_path,
                "prompt": prompt.model_dump(),
            },
            error=None,
        )
    except FileExistsError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt version already exists",
            data={"prompt_id": prompt_id, "version": request.version},
            error=ErrorModel(code="agent_prompt_version_exists", details=str(exc)),
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Agent prompt not found",
            data={"prompt_id": prompt_id},
            error=ErrorModel(code="agent_prompt_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Agent prompt save failed",
            data={"prompt_id": prompt_id},
            error=ErrorModel(code="agent_prompt_save_failed", details=str(exc)),
        )


@router.get("/app_profiles", response_model=APIResponse)
def app_profiles() -> APIResponse:
    profiles = list_app_profiles()
    return APIResponse(
        success=True,
        message="App profiles listed",
        data={"contract_version": "runtime_app_profiles_v1", "profiles": profiles},
        error=None,
    )


@router.get("/app_profiles/{app_id}", response_model=APIResponse)
def app_profile(app_id: str) -> APIResponse:
    try:
        profile, path = get_app_profile(app_id)
        return APIResponse(
            success=True,
            message="App profile loaded",
            data={
                "contract_version": "runtime_app_profile_v1",
                "path": str(path),
                "profile": profile.model_dump(),
            },
            error=None,
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="App profile not found",
            data={"app_id": app_id},
            error=ErrorModel(code="app_profile_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="App profile load failed",
            data={"app_id": app_id},
            error=ErrorModel(code="app_profile_load_failed", details=str(exc)),
        )


@router.get("/learning/model_trial", response_model=APIResponse)
def learning_model_trial(
    image_path: str = Query(min_length=1),
    app_name: str = Query(default="unknown_app"),
    state_hint: str = Query(default=""),
    goal: str = Query(default="learn a reusable UI workflow template from this screen"),
    validation_mode: str = Query(default="strict_blind"),
    max_attempts: int = Query(default=3, ge=1, le=5),
    max_output_tokens: int = Query(default=768, ge=256, le=8192),
    temperature: float = Query(default=0.0, ge=0.0, le=2.0),
    timeout_seconds: int = Query(default=180, ge=1, le=600),
    learning_image_max_edge: int = Query(default=256, ge=128, le=1280),
    allow_fast_profile_fallback: bool = Query(default=False),
) -> APIResponse:
    try:
        result = build_learning_model_trial(
            image_path=image_path,
            app_name=app_name,
            state_hint=state_hint,
            goal=goal,
            validation_mode=validation_mode,
            max_attempts=max_attempts,
            learning_parameter_overrides={
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "timeout_seconds": timeout_seconds,
                "learning_image_max_edge": learning_image_max_edge,
                "allow_fast_profile_fallback": allow_fast_profile_fallback,
            },
        )
        return APIResponse(
            success=True,
            message="Learning model trial completed",
            data=result,
            error=None,
        )
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Learning model trial image not found",
            data={"image_path": image_path},
            error=ErrorModel(code="learning_trial_image_not_found", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning model trial failed",
            data={"image_path": image_path, "app_name": app_name},
            error=ErrorModel(code="learning_model_trial_failed", details=str(exc)),
        )


@router.get("/models", response_model=APIResponse)
def model_status(profile_id: str | None = None) -> APIResponse:
    """Return configured local vision model profiles and current /v1/models status."""
    timer = RuntimeTimer()
    results = []
    with timer.step("load_model_profiles"):
        profiles = load_model_profiles()
    requested_profile_id = str(profile_id or "").strip()
    if requested_profile_id:
        profiles = [profile for profile in profiles if str(profile.get("profile_id") or "") == requested_profile_id]
    for profile in profiles:
        with timer.step("check_model_server", profile_id=profile.get("profile_id")):
            results.append({"profile": profile, "status": check_model_server(profile)})
    return APIResponse(
        success=True,
        message="Model server status collected",
        data={
            "contract_version": "runtime_model_status_v1",
            "requested_profile_id": requested_profile_id or None,
            "models": results,
            "timings": timer.to_dict(),
        },
        error=None,
    )


@router.get("/models/resource_preflight", response_model=APIResponse)
def model_resource_preflight(
    stage: str = Query(default="locate"),
    profile_id: str | None = Query(default=None),
) -> APIResponse:
    """在启动真实模型前报告 GPU 与系统内存占用，并给出批次建议。"""

    try:
        profile = profile_for_stage(stage, profile_id)
        result = build_model_resource_preflight(profile)
        return APIResponse(
            success=True,
            message="Model resource preflight completed",
            data=result,
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Model resource preflight failed",
            data={"stage": stage, "profile_id": profile_id},
            error=ErrorModel(code="model_resource_preflight_failed", details=str(exc)),
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
        after_status = str(((result.get("after") or {}).get("status") or "")).casefold()
        waited_start_failed = bool(request.wait_until_ready and result.get("after") and after_status != "running")
        result["trace_path"] = write_trace(
            category="runtime",
            operation="start_model",
            payload={"success": not waited_start_failed, "request": request.model_dump(), "result": result},
            name_hint=request.stage,
        )
        if waited_start_failed:
            return APIResponse(
                success=False,
                message="Model server did not become ready",
                data=result,
                error=ErrorModel(code="model_server_not_ready", details=str(result.get("after") or {})),
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
