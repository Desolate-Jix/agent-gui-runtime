from __future__ import annotations

from fastapi import APIRouter

from app.core.action_registry import action_registry
from app.core.state_memory import state_memory
from app.models.response import APIResponse

router = APIRouter(prefix="/state-memory", tags=["state-memory"])


@router.get("/states", response_model=APIResponse)
def list_states() -> APIResponse:
    states = [state.to_dict() for state in state_memory.list_states()]
    return APIResponse(success=True, message="Known states listed", data={"states": states}, error=None)


@router.get("/actions", response_model=APIResponse)
def list_actions() -> APIResponse:
    actions = []
    for path in sorted(action_registry.actions_dir.glob("*.json")):
        action = action_registry.load_action(path.stem)
        if action is not None:
            actions.append(action.to_dict())
    return APIResponse(success=True, message="Known actions listed", data={"actions": actions}, error=None)


@router.get("/validators", response_model=APIResponse)
def list_validators() -> APIResponse:
    validators = []
    for path in sorted(action_registry.validators_dir.glob("*.json")):
        validator = action_registry.load_validator(path.stem)
        if validator is not None:
            validators.append(validator.to_dict())
    return APIResponse(success=True, message="Known validators listed", data={"validators": validators}, error=None)
