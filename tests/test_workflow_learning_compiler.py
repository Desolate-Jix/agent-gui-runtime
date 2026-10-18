"""学习草稿只从原始终态和固定审核生成，不替代人工修订。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_compiler import compile_workflow_draft


LEARNING = "learning-" + "a" * 32
WORKFLOW = "workflow-" + "b" * 64
SNAPSHOT = "workflow-project-snapshot-" + "c" * 64


class Library:
    def __init__(self, root):
        self._workspace_root = Path(root)

    def list_workflow_graphs(self):
        return [{"logical_workflow_id": WORKFLOW}]

    def load_graph_revision(self, workflow_id):
        assert workflow_id == WORKFLOW
        return {"source_refs": {"kind": "execution_memory"},
                "graph": {"edges": [{"edge_id": "edge1", "evidence": {"learning_id": LEARNING, "event_id": "run1"}}]}}


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    event = {"learning_id": LEARNING, "request_id": "run1", "status": "returned",
             "kind": "input_sequence", "operation": "input_sequence", "action_executed": True,
             "sequence_status": "completed", "interrupted_at": None,
             "input_text": {"sha256": sha256("第一次".encode("utf-8")).hexdigest()},
             "before": {"sha256": "1" * 64}, "after": {"sha256": "2" * 64},
             "action_hints": {"field_goal": "搜索框", "submit_search": True, "clear_existing": True},
             "terminal_receipt": {"status": "completed"}}
    review = {"review_sha256": "3" * 64,
              "review": {"verdict": "success", "before": {"frame_sha256": "1" * 64},
                         "after": {"frame_sha256": "2" * 64},
                         "input_binding": {"kind": "constant", "value": "第一次"}}}
    bundle = {"manifest": {"learning_id": LEARNING, "session_id": "fresh-session",
                           "start_spec": {"scope": "workflow"}},
              "segments": [{"manifest": {"learning_id": LEARNING, "session_id": "fresh-session",
                                         "start_spec": {"scope": "workflow"}},
                            "events": [event], "reviews": {"run1": review}}],
              "contract_version": "execution_memory_graph_source_v2"}
    memory = {"snapshot_id": SNAPSHOT, "graph": {"workflow": {"goal": "搜索记录"},
        "nodes": [{"node_id": "home"}, {"node_id": "results"}],
        "edges": [{"edge_id": "edge1", "event_id": "run1", "source_node_id": "home",
            "target_node_id": "results", "provenance": "observed_action_agent_judged",
            "operation": "input_sequence", "action_hints": deepcopy(event["action_hints"]),
            "input_binding": deepcopy(review["review"]["input_binding"]), "label": "搜索"}]}}
    monkeypatch.setattr("app.learning_memory.workflow_compiler.read_source", lambda *_: deepcopy(bundle))
    monkeypatch.setattr("app.learning_memory.workflow_compiler.read_project", lambda *_: deepcopy(memory))
    return Library(tmp_path), bundle, memory


def test_terminal_receipt_compiles_stable_parameterized_candidate(recorded):
    library, _, _ = recorded
    kwargs = {"learning_session_id": LEARNING,
              "parameter_bindings": {"run1": {"name": "query", "example_value": "第一次"}},
              "annotations": {}}
    first = compile_workflow_draft(library, **kwargs)
    assert first == compile_workflow_draft(library, **kwargs)
    assert first["definition"]["inputs"] == [{"name": "query", "type": "text", "required": True}]
    step = first["definition"]["steps"][0]
    assert step["provenance"] == "observed"
    assert step["action"]["text"] == {"source": "input", "name": "query"}
    assert step["branches"]["success"] is None
    assert first["evidence_refs"][0]["event_id"] == "run1"
    assert "第一次" not in str(first)
    assert {row["reason"] for row in first["unresolved_items"]} >= {"target_rule_required", "verification_rule_required"}


def test_pending_or_failed_event_never_becomes_observed_step(recorded, monkeypatch):
    library, bundle, _ = recorded
    bundle["segments"][0]["events"][0]["status"] = "running"
    from app.learning_memory import workflow_compiler
    monkeypatch.setattr(workflow_compiler, "read_source", lambda *_: deepcopy(bundle))
    result = compile_workflow_draft(library, learning_session_id=LEARNING,
                                    parameter_bindings={}, annotations={})
    assert result["definition"]["steps"] == []
    assert any(item["reason"] == "execution_not_terminal" for item in result["unresolved_items"])


def test_parameter_requires_actual_recorded_value(recorded):
    library, _, _ = recorded
    with pytest.raises(ValueError, match="parameter_example_mismatch"):
        compile_workflow_draft(library, learning_session_id=LEARNING,
            parameter_bindings={"run1": {"name": "query", "example_value": "臆造"}}, annotations={})


def test_unsupported_step_semantics_do_not_turn_into_single_click(recorded, monkeypatch):
    library, bundle, memory = recorded
    bundle["segments"][0]["events"][0].update(kind="step", operation="execute_recognition_plan",
        action_hints={"goal": "打开", "click_kind": "right"})
    memory["graph"]["edges"][0].update(operation="execute_recognition_plan",
        action_hints={"goal": "打开", "click_kind": "right"})
    from app.learning_memory import workflow_compiler
    monkeypatch.setattr(workflow_compiler, "read_source", lambda *_: deepcopy(bundle))
    monkeypatch.setattr(workflow_compiler, "read_project", lambda *_: deepcopy(memory))
    result = compile_workflow_draft(library, learning_session_id=LEARNING,
                                    parameter_bindings={}, annotations={})
    assert result["definition"]["steps"] == []
    assert {item["reason"] for item in result["unresolved_items"]} == {"action_definition_required"}


def test_pending_middle_action_breaks_success_chain_even_when_states_join(recorded, monkeypatch):
    library, bundle, memory = recorded
    first = bundle["segments"][0]["events"][0]
    first["started_at"] = "2026-09-29T01:00:00+00:00"
    middle = deepcopy(first)
    middle.update(request_id="run2", status="running", started_at="2026-09-29T01:01:00+00:00")
    last = deepcopy(first)
    last.update(request_id="run3", started_at="2026-09-29T01:02:00+00:00")
    bundle["segments"][0]["events"] = [first, middle, last]
    bundle["segments"][0]["reviews"]["run2"] = None
    bundle["segments"][0]["reviews"]["run3"] = deepcopy(bundle["segments"][0]["reviews"]["run1"])
    first_edge = memory["graph"]["edges"][0]
    first_edge["target_node_id"] = "middle"
    last_edge = deepcopy(first_edge)
    last_edge.update(edge_id="edge3", event_id="run3", source_node_id="middle", target_node_id="results")
    memory["graph"]["edges"] = [first_edge, last_edge]
    memory["graph"]["nodes"].append({"node_id": "middle"})
    monkeypatch.setattr(library, "load_graph_revision", lambda *_: {"source_refs": {"kind": "execution_memory"},
        "graph": {"edges": [{"edge_id": "edge1", "evidence": {"learning_id": LEARNING, "event_id": "run1"}},
                             {"edge_id": "edge3", "evidence": {"learning_id": LEARNING, "event_id": "run3"}}]}})
    from app.learning_memory import workflow_compiler
    monkeypatch.setattr(workflow_compiler, "read_source", lambda *_: deepcopy(bundle))
    monkeypatch.setattr(workflow_compiler, "read_project", lambda *_: deepcopy(memory))
    result = compile_workflow_draft(library, learning_session_id=LEARNING,
                                    parameter_bindings={}, annotations={})
    assert len(result["definition"]["steps"]) == 2
    assert result["definition"]["steps"][0]["branches"]["success"] is None
    assert {item["reason"] for item in result["unresolved_items"]} >= {
        "execution_not_terminal", "observed_sequence_interrupted"}


def test_chronological_events_can_link_despite_reverse_graph_order(recorded, monkeypatch):
    library, bundle, memory = recorded
    first = bundle["segments"][0]["events"][0]
    first["started_at"] = "2026-09-29T01:00:00+00:00"
    last = deepcopy(first)
    last.update(request_id="run3", started_at="2026-09-29T01:02:00+00:00")
    bundle["segments"][0]["events"] = [last, first]
    bundle["segments"][0]["reviews"]["run3"] = deepcopy(bundle["segments"][0]["reviews"]["run1"])
    first_edge = memory["graph"]["edges"][0]
    first_edge["target_node_id"] = "middle"
    last_edge = deepcopy(first_edge)
    last_edge.update(edge_id="edge3", event_id="run3", source_node_id="middle", target_node_id="results")
    memory["graph"]["edges"] = [last_edge, first_edge]
    memory["graph"]["nodes"].append({"node_id": "middle"})
    monkeypatch.setattr(library, "load_graph_revision", lambda *_: {"source_refs": {"kind": "execution_memory"},
        "graph": {"edges": [{"edge_id": "edge3", "evidence": {"learning_id": LEARNING, "event_id": "run3"}},
                             {"edge_id": "edge1", "evidence": {"learning_id": LEARNING, "event_id": "run1"}}]}})
    from app.learning_memory import workflow_compiler
    monkeypatch.setattr(workflow_compiler, "read_source", lambda *_: deepcopy(bundle))
    monkeypatch.setattr(workflow_compiler, "read_project", lambda *_: deepcopy(memory))
    result = compile_workflow_draft(library, learning_session_id=LEARNING,
                                    parameter_bindings={}, annotations={})
    assert [row["event_id"] for row in result["evidence_refs"]] == ["run1", "run3"]
    assert result["definition"]["steps"][0]["branches"]["success"] == "step-2"


def test_standalone_segment_cannot_become_workflow(recorded, monkeypatch):
    library, bundle, _ = recorded
    bundle["segments"][0]["manifest"]["start_spec"]["scope"] = "interface"
    bundle["manifest"]["start_spec"]["scope"] = "interface"
    from app.learning_memory import workflow_compiler
    monkeypatch.setattr(workflow_compiler, "read_source", lambda *_: deepcopy(bundle))
    with pytest.raises(ValueError, match="workflow_segment_required"):
        compile_workflow_draft(library, learning_session_id=LEARNING,
                               parameter_bindings={}, annotations={})


def test_real_immutable_graph_source_compiles_without_writing_program(tmp_path):
    session = tmp_path / "fresh-session"
    (session / "responses").mkdir(parents=True)
    store = LearningEventStore(session)
    started = store.control("learning_start", {"scope": "workflow", "title": "搜索记录",
        "project_id": "fresh-project"}, "start")
    frames = []
    for view, color in (("before", "white"), ("after", "blue")):
        path = session / f"{view}.png"
        Image.new("RGB", (160, 100), color).save(path)
        frames.append({"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
                       "window_size": {"width": 160, "height": 100}})
    command = {"kind": "input_sequence", "request": {"field_goal": "搜索框", "text": "第一次",
               "clear_existing": True, "submit_search": True}}
    ticket = store.prepare("input-one", command, None)
    write_json_snapshot(session / "responses" / "input-one.json", {
        "command": command, "status": "returned", "learning_binding": ticket,
        "result": {"capture": frames[0], "observation": {"capture": frames[1]},
                   "status": "completed", "action_executed": True, "steps": []}})
    store.record("input-one", ticket)
    event = store.control("learning_event", {"event_id": "input-one"}, "read")["event"]
    store.control("learning_review", {"review": {
        "event_id": "input-one", "event_sha256": content_hash(event), "verdict": "success",
        "reviewer": "synthetic-contract", "reason": "合成终态审核",
        "input_binding": {"kind": "constant", "value": "第一次"},
        "before": {"interface_key": "search", "state_key": "home", "meaning": "搜索首页",
                   "frame_sha256": frames[0]["sha256"]},
        "after": {"interface_key": "search", "state_key": "results", "meaning": "结果页",
                  "frame_sha256": frames[1]["sha256"]}}}, "review")
    store.control("learning_stop", {}, "stop")
    with MemoryWorkspace(tmp_path / "memory-library") as library:
        first = compile_workflow_draft(library, learning_session_id=started["learning_id"],
            parameter_bindings={"input-one": {"name": "query", "example_value": "第一次"}},
            annotations={})
        second = compile_workflow_draft(library, learning_session_id=started["learning_id"],
            parameter_bindings={"input-one": {"name": "query", "example_value": "第一次"}},
            annotations={})
        assert first == second
        assert first["definition"]["steps"][0]["action"]["text"] == {"source": "input", "name": "query"}
        assert first["evidence_refs"][0]["event_id"] == "input-one"
        assert not (library._workspace_root / "workflow-projects" / first["workflow_id"] /
                    "task-program" / "head.json").exists()
        baseline = library.load_workflow_program(first["workflow_id"])
        edited = deepcopy(first["definition"])
        edited["steps"][0]["title"] = "人工修订标题"
        saved = library.save_workflow_program(first["workflow_id"], baseline["content_sha256"],
                                              edited, "human-edit")
        protected = compile_workflow_draft(library, learning_session_id=started["learning_id"],
            parameter_bindings={"input-one": {"name": "query", "example_value": "第一次"}},
            annotations={})
        assert protected["existing_program_id"] == saved["program_id"]
        assert protected["definition"]["steps"][0]["title"] == "人工修订标题"
        assert protected["unresolved_items"] == [
            {"event_id": None, "reason": "existing_program_revision_preserved"}]
