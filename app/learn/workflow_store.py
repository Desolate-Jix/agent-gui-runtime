from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any

from app.learn.workflow_state import (
    LearningWorkflowTransitionError,
    transition_learning_workflow_state,
    validate_learning_workflow_state,
)

LEARNING_WORKFLOW_STORE_CONTRACT_VERSION = "learning_workflow_run_store_v1"
LEARNING_WORKFLOW_STORE_PATH_ENV = "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LearningWorkflowRunStore:
    """在服务端保存学习流程状态，并用 revision 阻止并发覆盖。"""

    def __init__(
        self,
        *,
        max_runs: int = 128,
        state_path: str | Path | None = None,
    ) -> None:
        if max_runs < 1:
            raise ValueError("max_runs must be positive")
        self._max_runs = max_runs
        self._state_path = Path(state_path).resolve() if state_path is not None else None
        self._lock = RLock()
        self._owner_lock_handle: Any | None = None
        if self._state_path is not None:
            self._acquire_owner_lock()
        try:
            self._states = self._load_states()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """释放持久化路径的单进程所有权。"""

        handle = self._owner_lock_handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._owner_lock_handle = None

    def get(self, run_id: str) -> dict[str, Any]:
        normalized_run_id = _normalized_run_id(run_id)
        with self._lock:
            state = self._states.get(normalized_run_id)
            if state is None:
                raise LearningWorkflowTransitionError("workflow run not found")
            return deepcopy(state)

    def capacity_snapshot(self) -> dict[str, Any]:
        """只读投影当前容量；终态槽可在下一次新建 run 时回收。"""

        with self._lock:
            run_count = len(self._states)
            terminal_evictable = sum(
                state.get("terminal") is True for state in self._states.values()
            )
            active = run_count - terminal_evictable
            return {
                "contract_version": "learning_workflow_store_capacity_v1",
                "max_runs": self._max_runs,
                "run_count": run_count,
                "active_runs": active,
                "terminal_evictable_runs": terminal_evictable,
                "available_slots": self._max_runs - active,
            }

    def transition(
        self,
        *,
        run_id: str,
        expected_revision: int,
        stage: str,
        outcome: str,
        reason: str = "",
        evidence_refs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_run_id = _normalized_run_id(run_id)
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise LearningWorkflowTransitionError("expected_revision must be a non-negative integer")

        with self._lock:
            previous_state = self._states.get(normalized_run_id)
            if previous_state is None:
                if expected_revision != 0:
                    raise LearningWorkflowTransitionError("workflow run not found")
            elif previous_state["revision"] != expected_revision:
                raise LearningWorkflowTransitionError(
                    f"workflow revision conflict: expected {expected_revision}, "
                    f"current {previous_state['revision']}"
                )

            state = transition_learning_workflow_state(
                previous_state=previous_state,
                run_id=normalized_run_id,
                stage=stage,
                outcome=outcome,
                reason=reason,
                evidence_refs=evidence_refs,
            )
            candidate_states = deepcopy(self._states)
            if previous_state is None:
                self._make_capacity(candidate_states)
            candidate_states[normalized_run_id] = deepcopy(state)
            candidate_states.move_to_end(normalized_run_id)
            self._persist_states(candidate_states)
            self._states = candidate_states
            return deepcopy(state)

    def _load_states(self) -> OrderedDict[str, dict[str, Any]]:
        states: OrderedDict[str, dict[str, Any]] = OrderedDict()
        if self._state_path is None or not self._state_path.exists():
            return states
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LearningWorkflowTransitionError(
                f"workflow store persistence is unreadable: {self._state_path}: {exc}"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("contract_version")
            != LEARNING_WORKFLOW_STORE_CONTRACT_VERSION
            or not isinstance(payload.get("runs"), list)
        ):
            raise LearningWorkflowTransitionError(
                f"workflow store persistence contract is invalid: {self._state_path}"
            )
        for index, raw_state in enumerate(payload["runs"]):
            try:
                state = validate_learning_workflow_state(raw_state)
            except LearningWorkflowTransitionError as exc:
                raise LearningWorkflowTransitionError(
                    f"workflow store run at index {index} is invalid: {exc}"
                ) from exc
            run_id = str(state["run_id"])
            if run_id in states:
                raise LearningWorkflowTransitionError(
                    f"workflow store contains duplicate run_id: {run_id}"
                )
            states[run_id] = state
        if len(states) > self._max_runs:
            raise LearningWorkflowTransitionError(
                "workflow store persistence exceeds configured max_runs"
            )
        return states

    def _acquire_owner_lock(self) -> None:
        assert self._state_path is not None
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._state_path.with_name(f"{self._state_path.name}.lock")
        handle = lock_path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise LearningWorkflowTransitionError(
                f"workflow store persistence path is already owned: {self._state_path}"
            ) from exc
        self._owner_lock_handle = handle

    def _persist_states(
        self,
        states: OrderedDict[str, dict[str, Any]],
    ) -> None:
        if self._state_path is None:
            return
        payload = {
            "contract_version": LEARNING_WORKFLOW_STORE_CONTRACT_VERSION,
            "runs": list(states.values()),
        }
        try:
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise LearningWorkflowTransitionError(
                f"workflow store persistence serialization failed: {exc}"
            ) from exc

        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self._state_path.parent,
                prefix=f".{self._state_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._state_path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise LearningWorkflowTransitionError(
                f"workflow store persistence commit failed: {self._state_path}: {exc}"
            ) from exc

    def _make_capacity(
        self,
        states: OrderedDict[str, dict[str, Any]],
    ) -> None:
        if len(states) < self._max_runs:
            return
        for run_id, state in states.items():
            if state.get("terminal") is True:
                del states[run_id]
                return
        raise LearningWorkflowTransitionError("workflow run store is full with active runs")


def _normalized_run_id(run_id: str) -> str:
    value = str(run_id or "").strip()
    if not value:
        raise LearningWorkflowTransitionError("run_id is required")
    return value


def resolve_learning_workflow_store_path(
    *,
    project_root: str | Path = _PROJECT_ROOT,
) -> Path | None:
    """解析权威工作流状态路径；测试可显式选择内存模式。"""

    configured = str(os.environ.get(LEARNING_WORKFLOW_STORE_PATH_ENV) or "").strip()
    if configured == ":memory:":
        return None
    root = Path(project_root).resolve()
    if configured:
        configured_path = Path(configured)
        return (
            configured_path
            if configured_path.is_absolute()
            else root / configured_path
        ).resolve()
    return (root / "runtime_state" / "learning-workflow-runs.json").resolve()


learning_workflow_run_store = LearningWorkflowRunStore(
    state_path=resolve_learning_workflow_store_path(),
)
