from __future__ import annotations

from fastapi import FastAPI


def create_runtime_app() -> FastAPI:
    from app.api.action import router as action_router
    from app.api.agent_runtime import router as agent_runtime_router
    from app.api.apps import router as apps_router
    from app.api.execute import router as execute_router
    from app.api.memory import router as memory_router
    from app.api.runtime import router as runtime_router
    from app.api.session import router as session_router
    from app.api.state import router as state_router
    from app.api.vision import router as vision_router
    from app.api.models.response import APIResponse, HealthData

    application = FastAPI(title="agent-gui-runtime", version="0.3.0")
    application.include_router(apps_router)
    application.include_router(runtime_router)
    application.include_router(session_router)
    application.include_router(state_router)
    application.include_router(action_router)
    application.include_router(agent_runtime_router)
    application.include_router(execute_router)
    application.include_router(memory_router)
    application.include_router(vision_router)

    @application.get("/health", response_model=APIResponse)
    def health() -> APIResponse:
        return APIResponse(
            success=True,
            message="Service is healthy",
            data=HealthData().model_dump(),
            error=None,
        )

    return application
