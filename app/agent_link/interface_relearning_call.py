"""独立界面重学通信：身份取自连接，只允许读取和提交候选。"""
from __future__ import annotations

from copy import deepcopy
from pydantic import ValidationError

from .contracts import AgentLinkError, InterfaceRelearningChanges, fail
from .interface_capability import INTERFACE_RELEARNING_CAPABILITY


def interface_relearning_call(service, token, operation, arguments):
    from .service import _args, _text
    from app.desktop_review.workspace import DesktopReviewError

    with service._interface_gateway_guard:
        gateway = service._interface_gateway
    if gateway is None or not all(callable(getattr(gateway, name, None))
                                  for name in INTERFACE_RELEARNING_CAPABILITY["operations"]):
        fail("operation_forbidden", "interface relearning is not enabled")
    keys = {
        "list_interface_relearning_feedback": set(),
        "get_interface_relearning_feedback": {"issue_id"},
        "submit_interface_relearning_candidate": {
            "issue_id", "expected_baseline_sha256", "changes", "idempotency_key"},
    }[operation]
    args = _args(arguments, keys, keys)
    for key in keys - {"changes"}:
        _text(args[key], key)
    args = deepcopy(args)
    if operation == "submit_interface_relearning_candidate":
        try:
            args["changes"] = InterfaceRelearningChanges.model_validate(args["changes"]).model_dump(exclude_unset=True)
        except ValidationError as error:
            raise AgentLinkError("invalid_arguments", "interface changes must contain valid content fields") from error
    identity = service._store.read(lambda state: {key: value for key, value in service._connection(state, token).items()
                                                  if key in {"connection_id", "task_id"}})
    try:
        result = getattr(gateway, operation)(identity["task_id"], **args)
        safe = service._safe_interface_result(result)
        if (safe.get("contract_version") != INTERFACE_RELEARNING_CAPABILITY["contract_version"]
                or any(safe.get(key) is not False for key in (
                    "artifact_is_authorization", "execute_binding_enabled", "action_executed"))):
            fail("interface_source_unavailable", "interface feedback response is invalid")
    except AgentLinkError:
        raise
    except DesktopReviewError as error:
        detail = str(error)
        code = ("idempotency_conflict" if "idempotency_conflict" in detail else
                "stale_revision" if "stale" in detail else
                "persistence_failed" if "persistence_failed" in detail else
                "invalid_arguments" if any(word in detail for word in ("arguments_invalid", "regions_invalid", "changes_invalid", "idempotency_key_invalid")) else
                "interface_source_unavailable")
        raise AgentLinkError(code, "interface feedback request failed: " + code) from error
    except OSError as error:
        raise AgentLinkError("interface_source_unavailable", "interface feedback evidence could not be read") from error
    service._store.read(lambda state: service._recheck_identity(state, token, identity))
    return safe
