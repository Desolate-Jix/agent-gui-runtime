from __future__ import annotations

import re
from typing import Any

from .contracts import fail


MEMORY_SCOPE_CONTRACT = "workflow_memory_scope_v1"
MEMORY_CAPABILITY = {
    "contract_version": "agent_workflow_memory_v1",
    "operations": ["search_workflow_memory", "get_workflow_memory"],
}
_WORKFLOW_ID = re.compile(r"^workflow-[0-9a-f]{64}$")


def validate_workflow_id(value: Any) -> str:
    if not isinstance(value, str) or _WORKFLOW_ID.fullmatch(value) is None:
        fail("invalid_arguments", "workflow_id is invalid")
    return value


def validate_workflow_ids(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 128
        or any(not isinstance(item, str) or _WORKFLOW_ID.fullmatch(item) is None for item in value)
        or value != sorted(set(value))
    ):
        fail("invalid_arguments", "workflow_ids must be canonical, sorted, and unique")
    return list(value)


def validate_stored_memory_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"contract_version", "revision", "workflow_ids"}:
        raise ValueError
    if value["contract_version"] != MEMORY_SCOPE_CONTRACT:
        raise ValueError
    if type(value["revision"]) is not int or value["revision"] < 1:
        raise ValueError
    try:
        workflow_ids = validate_workflow_ids(value["workflow_ids"])
    except Exception as error:
        raise ValueError from error
    return {
        "contract_version": MEMORY_SCOPE_CONTRACT,
        "revision": value["revision"],
        "workflow_ids": workflow_ids,
    }
