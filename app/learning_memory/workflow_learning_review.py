"""原生工作台只读回看现有学习段与整理结果。"""
from pathlib import Path

from .event_store import LearningEventStore
from .learning_synthesis import LearningSynthesisService, _SCHEMA, _source
from .receipt_adapter import content_hash
from .workflow_program import WorkflowProgramService


def read_workflow_learning(library, session_dir) -> dict:
    session = Path(session_dir).resolve()
    if not session.is_dir():
        raise ValueError("workflow_learning_session_missing")
    if (session.parent / "memory-library").resolve() != Path(library._artifact_root).resolve():
        raise ValueError("workflow_learning_library_mismatch")
    status = LearningEventStore(session).status()
    learning_id = status.get("learning_id")
    if learning_id is None:
        return {"status": "no_learning", "learning_id": None, "synthesis": None, "program": None}
    if status.get("start_spec", {}).get("scope") == "interface":
        return {"status": "interface_only", "learning_id": learning_id, "synthesis": None, "program": None}
    if status.get("start_spec", {}).get("scope") != "workflow":
        raise ValueError("workflow_learning_scope_invalid")
    if status.get("status") != "stopped":
        return {"status": "recording", "learning_id": learning_id, "synthesis": None, "program": None}
    if status.get("recording_complete") is not True:
        return {"status": "awaiting_recording", "learning_id": learning_id, "synthesis": None, "program": None}
    source, _segment = _source(library, learning_id)
    service = WorkflowProgramService(library)
    program = service.load(source["workflow_id"])
    if program["program_id"] is not None:
        synthesis = {"status": "existing_program_preserved", "program_id": program["program_id"],
                     "workflow_id": source["workflow_id"], "input_executed": False,
                     "automatic_retry_allowed": False}
        return {"status": synthesis["status"], "learning_id": learning_id,
                "synthesis": synthesis, "program": program}
    identity = "learning-synthesis-" + content_hash([_SCHEMA, content_hash(source)])
    synthesis_service = LearningSynthesisService(library, session)
    directory = synthesis_service._directory(identity)
    if not (directory / "request.json").is_file():
        if directory.exists() and any(directory.iterdir()):
            raise ValueError("workflow_learning_synthesis_request_missing")
        from .workflow_compiler import compile_workflow_draft
        draft = compile_workflow_draft(library, learning_session_id=learning_id,
                                       parameter_bindings={}, annotations={})
        if not draft["definition"]["steps"]:
            synthesis = {"status": "needs_review", "reason": "no_compilable_actions",
                         "learning_session_id": learning_id,
                         "unresolved_items": draft["unresolved_items"],
                         "input_executed": False, "automatic_retry_allowed": False}
            return {"status": synthesis["status"], "learning_id": learning_id,
                    "synthesis": synthesis, "program": program}
        return {"status": "not_requested", "learning_id": learning_id,
                "synthesis": None, "program": program}
    synthesis = synthesis_service.status(identity)
    return {"status": synthesis["status"], "learning_id": learning_id,
            "synthesis": synthesis, "program": program}


__all__ = ["read_workflow_learning"]
