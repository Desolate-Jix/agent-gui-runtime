"""连续运行器的来源端口与既有学习程序适配器。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal, Protocol


RunSourceKind = Literal["caller_plan", "reviewed_program"]


class RunBackend(Protocol):
    source_kind: RunSourceKind

    def status(self, run_id: str) -> dict: ...

    def prepare(self, run_id: str, request_id: str, *, vision_capabilities=None) -> dict: ...

    def cancel(self, run_id: str, request_id: str) -> dict: ...

    def pinned_step(self, run_id: str, step_id: str) -> dict: ...

    def metrics(self, run_id: str, trial: dict) -> dict: ...

    def validate_resume(self, run_id: str, state: dict | None, *, revalidate_initial=False) -> None: ...


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


class ReviewedProgramBackend:
    source_kind: RunSourceKind = "reviewed_program"

    def __init__(self, session_dir, library_root, *, workspace_factory=None):
        if workspace_factory is None:
            from app.learning_memory.workspace import MemoryWorkspace
            workspace_factory = MemoryWorkspace
        self.session = Path(session_dir).resolve()
        self.library_root = Path(library_root).resolve()
        self._workspace = workspace_factory

    def status(self, run_id):
        with self._workspace(self.library_root) as library:
            return library.status_workflow_trial(self.session, run_id)

    def prepare(self, run_id, request_id, *, vision_capabilities=None):
        with self._workspace(self.library_root) as library:
            if vision_capabilities is None:
                return library.prepare_workflow_trial(self.session, run_id, request_id)
            return library.prepare_workflow_trial(self.session, run_id, request_id,
                                                  vision_capabilities=vision_capabilities)

    def cancel(self, run_id, request_id):
        with self._workspace(self.library_root) as library:
            return library.cancel_workflow_trial(self.session, run_id, request_id)

    def pinned_step(self, run_id, step_id):
        with self._workspace(self.library_root) as library:
            trial = library.status_workflow_trial(self.session, run_id)
            program = library.load_workflow_program(trial["workflow_id"], trial["program_id"])
        matches = [step for step in program["definition"]["steps"] if step["step_id"] == step_id]
        if len(matches) != 1:
            raise ValueError("workflow_runner_step_not_in_pinned_program")
        return deepcopy(matches[0])

    def metrics(self, run_id, trial):
        from app.learning_memory.workflow_metrics import load_run_metrics
        return load_run_metrics(self.session, run_id, trial=trial)

    def validate_resume(self, run_id, state, *, revalidate_initial=False):
        self.validate_trial_resume(self.status(run_id), state,
                                   revalidate_initial=revalidate_initial)

    def recovery_claim(self, trial, phases):
        from app.learning_memory.workflow_recovery_resolution import marker_resolution
        from app.learning_memory.workflow_program import _id
        from app.learning_memory.workflow_trial import _RUN

        marker = trial.get("recovery_import")
        try:
            resolution = marker_resolution(marker)
        except ValueError as error:
            raise ValueError("workflow_runner_recovery_import_invalid") from error

        def require(condition):
            if not condition:
                raise ValueError("workflow_runner_recovery_import_invalid")

        for key in ("claim_id", "source_program_sha256", "source_settlement_sha256", "effect_evidence_sha256", "verified_history_sha256"):
            require(isinstance(marker[key], str) and re.fullmatch(r"[0-9a-f]{64}", marker[key]) is not None)
        require(all(_text(marker[key]) for key in ("request_id", "source_step_id", "source_execution_request_id", "effect_evidence_ref")))
        require(isinstance(marker["source_session_name"], str) and re.fullmatch(r"session-[0-9a-f]{32}", marker["source_session_name"]) is not None)
        _id(marker["source_run_id"], "run_id", _RUN)
        steps = marker["consumed_step_ids"]
        minimum = 0 if resolution == "resume_unexecuted" else 1
        require(isinstance(steps, list) and minimum <= len(steps) <= 256
                and all(_text(step) for step in steps) and len(set(steps)) == len(steps))
        require(resolution != "resume_unexecuted" or marker["source_step_id"] not in steps)
        ref = Path(marker["effect_evidence_ref"])
        require(not ref.is_absolute() and (self.session / ref).resolve().is_relative_to(self.session))
        path = self.session.parent / "workflow-takeovers" / (marker["claim_id"] + ".json")
        require(path.resolve().parent == self.session.parent / "workflow-takeovers")
        try:
            claim = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("workflow_runner_recovery_claim_invalid") from error
        require(isinstance(claim, dict) and claim.get("contract_version") == "workflow_takeover_claim.v1"
                and claim.get("phase") in phases and claim.get("claim_id") == marker["claim_id"]
                and claim.get("request_id") == marker["request_id"] and claim.get("new_session_name") == self.session.name
                and claim.get("new_run_id") == trial["run_id"])
        require(claim.get("recovery_import") == marker)
        history = trial.get("history")
        require(isinstance(history, list) and len(history) >= len(steps))
        prefix = history[:len(steps)]
        require(all(isinstance(row, dict) for row in prefix) and [row.get("step_id") for row in prefix] == steps)
        require(isinstance(claim.get("imported_history_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", claim["imported_history_sha256"]) is not None
                and _digest(prefix) == claim["imported_history_sha256"])
        if claim["phase"] == "importing":
            require(claim.get("trial_state_sha256") == _digest(trial))
        return marker

    def validate_trial_resume(self, trial, state, *, revalidate_initial=False):
        # 原接管调用者可能持有库锁，复用其刚读取的账本，避免再次打开同库。
        if trial.get("recovery_import") is None:
            if state is not None and state.get("recovery_import") is not None:
                raise ValueError("workflow_runner_recovery_import_invalid")
            return
        marker = self.recovery_claim(trial, {"ready"})
        if state is None or state.get("recovery_import") != {"claim_id": marker["claim_id"], "request_id": marker["request_id"]}:
            raise ValueError("workflow_runner_recovery_import_required")
        if (revalidate_initial and marker.get("resolution") == "resume_unexecuted"
                and state.get("ticket") is None and state.get("runner_state") not in {"completed", "failed", "cancelled"}):
            from app.learning_memory.workflow_recovery_import import validate_recovery_progress
            with self._workspace(self.library_root) as library:
                verified = validate_recovery_progress(library, self.session, trial)
            consumed = verified["consumed_step_ids"]
            if (state.get("seen_steps") != consumed or state.get("steps_completed") != len(consumed)
                    or consumed == marker["consumed_step_ids"]
                    and state.get("current_step_id") != marker["source_step_id"]):
                raise ValueError("workflow_runner_recovery_initial_state_invalid")


__all__ = ["RunBackend", "RunSourceKind", "ReviewedProgramBackend"]
