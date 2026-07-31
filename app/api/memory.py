from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore
from app.api.models.response import APIResponse, ErrorModel
from app.learn.agent_evidence import load_application_agent_evidence_context
from app.learn.interface_workflow_review import (
    load_interface_workflow_agent_context,
    load_interface_workflow_library_registry,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
memory_store = ReviewedInterfaceMemoryStore(project_root=ROOT_DIR)
router = APIRouter(prefix="/memory", tags=["memory"])


class PublishReviewedInterfaceMemoryRequest(BaseModel):
    source_path: str = Field(min_length=1)
    interface_id: str = Field(min_length=2, max_length=80)
    expected_registry_revision: int = Field(ge=0)


@router.post("/reviewed_interfaces/publish", response_model=APIResponse)
def publish_reviewed_interface_memory(request: PublishReviewedInterfaceMemoryRequest) -> APIResponse:
    try:
        result = memory_store.publish(
            source_path=request.source_path,
            interface_id=request.interface_id,
            expected_registry_revision=request.expected_registry_revision,
        )
        return APIResponse(
            success=True,
            message="Reviewed interface memory published",
            data=result,
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Reviewed interface memory publish failed",
            data=None,
            error=ErrorModel(
                code="reviewed_interface_memory_publish_failed",
                details=str(exc),
            ),
        )


@router.get("/reviewed_interfaces/registry", response_model=APIResponse)
def reviewed_interface_memory_registry() -> APIResponse:
    try:
        return APIResponse(
            success=True,
            message="Reviewed interface memory registry loaded",
            data=memory_store.registry(),
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Reviewed interface memory registry load failed",
            data=None,
            error=ErrorModel(
                code="reviewed_interface_memory_registry_failed",
                details=str(exc),
            ),
        )


@router.get("/interface_workflows/registry", response_model=APIResponse)
def interface_workflow_library_registry() -> APIResponse:
    try:
        return APIResponse(
            success=True,
            message="Interface workflow library registry loaded",
            data=load_interface_workflow_library_registry(project_root=ROOT_DIR),
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Interface workflow library registry load failed",
            data=None,
            error=ErrorModel(
                code="interface_workflow_library_registry_failed",
                details=str(exc),
            ),
        )


@router.get("/interface_workflows/agent_context", response_model=APIResponse)
def interface_workflow_agent_context(
    application_identity_key: str = Query(min_length=3),
) -> APIResponse:
    try:
        return APIResponse(
            success=True,
            message="Interface workflow agent context loaded",
            data=load_interface_workflow_agent_context(
                project_root=ROOT_DIR,
                application_identity_key=application_identity_key,
            ),
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Interface workflow agent context load failed",
            data=None,
            error=ErrorModel(
                code="interface_workflow_agent_context_failed",
                details=str(exc),
            ),
        )


@router.get("/interface_assets/agent_context", response_model=APIResponse)
def application_interface_agent_context(
    application_identity_key: str = Query(min_length=3),
    interface_id: str | None = Query(default=None, min_length=1),
) -> APIResponse:
    try:
        return APIResponse(
            success=True,
            message="Application interface Agent evidence loaded",
            data=load_application_agent_evidence_context(
                application_identity_key,
                interface_id=interface_id,
                project_root=ROOT_DIR,
            ),
            error=None,
        )
    except (OSError, ValueError) as exc:
        return APIResponse(
            success=False,
            message="Application interface Agent evidence load failed",
            data=None,
            error=ErrorModel(
                code="application_interface_agent_evidence_failed",
                details=str(exc),
            ),
        )


@router.get("/reviewed_interfaces/{interface_id}", response_model=APIResponse)
def load_reviewed_interface_memory(interface_id: str) -> APIResponse:
    try:
        return APIResponse(
            success=True,
            message="Reviewed interface memory loaded",
            data=memory_store.load_active(interface_id),
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Reviewed interface memory load failed",
            data=None,
            error=ErrorModel(
                code="reviewed_interface_memory_load_failed",
                details=str(exc),
            ),
        )


@router.get("/reviewed_interfaces/{interface_id}/agent_context", response_model=APIResponse)
def reviewed_interface_agent_context(interface_id: str) -> APIResponse:
    try:
        return APIResponse(
            success=True,
            message="Agent operational memory context loaded",
            data=memory_store.agent_context(interface_id),
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Agent operational memory context load failed",
            data=None,
            error=ErrorModel(
                code="agent_operational_memory_context_failed",
                details=str(exc),
            ),
        )
