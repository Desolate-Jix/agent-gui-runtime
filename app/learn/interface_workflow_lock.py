from __future__ import annotations

from threading import Lock


_INTERFACE_WORKFLOW_SAVE_LOCKS_GUARD = Lock()
_INTERFACE_WORKFLOW_SAVE_LOCKS: dict[str, Lock] = {}


def interface_workflow_lock(workflow_id: str) -> Lock:
    lock_key = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in str(workflow_id or "").strip()
    ).strip("._") or "__invalid_workflow__"
    with _INTERFACE_WORKFLOW_SAVE_LOCKS_GUARD:
        return _INTERFACE_WORKFLOW_SAVE_LOCKS.setdefault(lock_key, Lock())
