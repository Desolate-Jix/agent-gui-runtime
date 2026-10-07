"""学习编译控制只读，读取步骤只来自冻结的当前界面证据。"""

from copy import deepcopy
from hashlib import sha256

import pytest
from PIL import Image

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.workflow_control import workflow_control
from app.learning_memory.workspace import MemoryWorkspace
from tests.test_workflow_learning_compiler import LEARNING, recorded


def test_compile_control_is_closed_and_rules_are_editorial(recorded):
    library, _, _ = recorded
    candidate = workflow_control(library, None, {"action": "compile", "learning_session_id": LEARNING,
        "annotations": {"run1": {"verification": {"kind": "agent_judgment"}}}}, "compile-one")
    step = candidate["definition"]["steps"][0]
    assert step["verification"] == {"kind": "agent_judgment"}
    assert step["provenance"] == "editorial"
    assert step["review_status"] == "pending"
    assert "editorial_verification_unverified" in {item["reason"] for item in candidate["unresolved_items"]}
    with pytest.raises(ValueError, match="learning_workflow fields"):
        workflow_control(library, None, {"action": "compile", "learning_session_id": LEARNING,
            "unexpected": True}, "bad-fields")
    with pytest.raises(ValueError, match="task_program_verification"):
        workflow_control(library, None, {"action": "compile", "learning_session_id": LEARNING,
            "annotations": {"run1": {"verification": {"kind": "field_equals", "target": {"name": "x"}}}}},
            "bad-rule")
    with pytest.raises(ValueError, match="verification_upstream_output_unknown"):
        workflow_control(library, None, {"action": "compile", "learning_session_id": LEARNING,
            "annotations": {"run1": {"verification": {"kind": "text_equals",
                "target": {"control_type": "Text", "name": "结果"},
                "expected": {"source": "output", "step_id": "missing", "name": "detail"}}}}}, "bad-upstream")
    with pytest.raises(ValueError, match="learning_annotation_invalid"):
        workflow_control(library, None, {"action": "compile", "learning_session_id": LEARNING,
            "annotations": {"run1": {"approval": True}}}, "bad-annotation")


def test_real_read_event_compiles_saves_and_reopens_without_transition(tmp_path):
    session = tmp_path / "fresh-read-session"
    (session / "responses").mkdir(parents=True)
    store = LearningEventStore(session)
    started = store.control("learning_start", {"scope": "workflow", "title": "读取当前页",
        "project_id": "fresh-read-project"}, "start")
    image = session / "after.png"
    Image.new("RGB", (160, 100), "white").save(image)
    frame = {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
             "window_size": {"width": 160, "height": 100}}
    command = {"kind": "read_text", "max_chars": 10000}
    ticket = store.prepare("read-one", command, None)
    write_json_snapshot(session / "responses" / "read-one.json", {
        "command": command, "status": "returned", "learning_binding": ticket,
        "result": {"status": "text_observed", "action_executed": False}, "observation": frame})
    store.record("read-one", ticket)
    event = store.control("learning_event", {"event_id": "read-one"}, "read")["event"]
    store.control("learning_review", {"review": {
        "event_id": "read-one", "event_sha256": content_hash(event), "verdict": "success",
        "reviewer": "synthetic-contract", "reason": "当前页读取完成", "before": None,
        "after": {"interface_key": "results", "state_key": "current", "meaning": "当前结果页",
                  "frame_sha256": frame["sha256"]}}}, "review")
    store.control("learning_stop", {}, "stop")
    with MemoryWorkspace(tmp_path / "memory-library") as library:
        request = {"action": "compile", "learning_session_id": started["learning_id"],
            "annotations": {"read-one": {
                "read_spec": {"method": "agent_read", "output_name": "detail",
                              "target": {"control_type": "Text", "name": "当前结果"}},
                "outputs": [{"name": "detail", "type": "text"}]}}}
        candidate = workflow_control(library, session, request, "compile-read")
        assert candidate == workflow_control(library, session, request, "compile-read-again")
        assert len(candidate["definition"]["steps"]) == 1
        step = candidate["definition"]["steps"][0]
        assert step["action"] == {"kind": "read_text", "goal": "读取当前界面可见文字"}
        assert step["source_node_id"] == step["target_node_id"]
        assert step["read_spec"]["method"] == "agent_read"
        assert step["provenance"] == "editorial"
        assert step["source_evidence"] == {"learning_id": started["learning_id"], "event_id": "read-one",
            "event_sha256": content_hash(event), "review_sha256": candidate["evidence_refs"][0]["review_sha256"]}
        assert candidate["evidence_refs"][0]["event_id"] == "read-one"
        assert "agent_read_required" in {row["reason"] for row in candidate["unresolved_items"]}
        baseline = library.load_workflow_program(candidate["workflow_id"])
        forged = deepcopy(candidate["definition"])
        forged["steps"][0]["source_evidence"]["event_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="task_program_source_evidence"):
            library.save_workflow_program(candidate["workflow_id"], baseline["content_sha256"], forged, "forged-read")
        duplicate = deepcopy(candidate["definition"])
        duplicate_step = deepcopy(duplicate["steps"][0])
        duplicate_step["step_id"] = "step-2"
        duplicate["steps"].append(duplicate_step)
        with pytest.raises(ValueError, match="task_program_source_evidence_duplicate"):
            library.save_workflow_program(candidate["workflow_id"], baseline["content_sha256"], duplicate, "duplicate-read")
        drifted = deepcopy(candidate["definition"])
        drifted["steps"][0]["target_node_id"] = None
        with pytest.raises(ValueError, match="task_program_source_evidence"):
            library.save_workflow_program(candidate["workflow_id"], baseline["content_sha256"], drifted, "drifted-read")
        changed_kind = deepcopy(candidate["definition"])
        changed_kind["steps"][0]["action"] = {"kind": "click", "goal": "打开结果"}
        with pytest.raises(ValueError, match="task_program_source_evidence_action_invalid"):
            library.save_workflow_program(candidate["workflow_id"], baseline["content_sha256"],
                                          changed_kind, "changed-kind")
        premature_review = deepcopy(candidate["definition"])
        premature_review["steps"][0]["review_status"] = "reviewed"
        saved = workflow_control(library, session, {"action": "save", "workflow_id": candidate["workflow_id"],
            "expected_sha256": baseline["content_sha256"], "definition": premature_review}, "save-read")
        reopened = workflow_control(library, session, {"action": "read", "workflow_id": candidate["workflow_id"],
            "program_id": saved["program_id"]}, "read-saved")
        assert reopened["definition"]["steps"][0]["action"]["kind"] == "read_text"
        assert reopened["definition"]["steps"][0]["provenance"] == "editorial"
        assert reopened["definition"]["steps"][0]["review_status"] == "pending"
        approved = deepcopy(reopened["definition"])
        approved["steps"][0]["review_status"] = "reviewed"
        reviewed = library.save_workflow_program(candidate["workflow_id"], reopened["content_sha256"],
                                                 approved, "review-read")
        reviewed_again = library.load_workflow_program(candidate["workflow_id"], reviewed["program_id"])
        assert reviewed_again["definition"]["steps"][0]["provenance"] == "editorial"
        assert reviewed_again["definition"]["steps"][0]["review_status"] == "reviewed"
        rule_changed = deepcopy(reviewed_again["definition"])
        rule_changed["steps"][0]["read_spec"]["target"]["name"] = "新的当前结果"
        rule_edited = library.save_workflow_program(candidate["workflow_id"], reviewed_again["content_sha256"],
                                                    rule_changed, "edit-rule")
        assert rule_edited["definition"]["steps"][0]["review_status"] == "pending"
        rule_reviewed = deepcopy(rule_edited["definition"])
        rule_reviewed["steps"][0]["review_status"] = "reviewed"
        rule_approved = library.save_workflow_program(candidate["workflow_id"], rule_edited["content_sha256"],
                                                      rule_reviewed, "review-rule")
        assert rule_approved["definition"]["steps"][0]["review_status"] == "reviewed"
        dependency_changed = deepcopy(rule_approved["definition"])
        dependency_changed["outputs"] = [{"name": "detail", "type": "text", "step_id": "step-1"}]
        dependency_edited = library.save_workflow_program(candidate["workflow_id"], rule_approved["content_sha256"],
                                                          dependency_changed, "edit-output-dependency")
        assert dependency_edited["definition"]["steps"][0]["review_status"] == "pending"
        dependency_reviewed = deepcopy(dependency_edited["definition"])
        dependency_reviewed["steps"][0]["review_status"] = "reviewed"
        dependency_approved = library.save_workflow_program(candidate["workflow_id"], dependency_edited["content_sha256"],
                                                            dependency_reviewed, "review-output-dependency")
        assert dependency_approved["definition"]["steps"][0]["review_status"] == "reviewed"
        revised = deepcopy(dependency_approved["definition"])
        revised["steps"][0]["action"]["goal"] = "读取当前界面的结果标题"
        revised["steps"][0]["provenance"] = "observed"
        edited = library.save_workflow_program(candidate["workflow_id"], dependency_approved["content_sha256"], revised, "edit-goal")
        assert edited["definition"]["steps"][0]["provenance"] == "editorial"
        assert edited["definition"]["steps"][0]["review_status"] == "pending"
        manual = deepcopy(edited["definition"])
        manual_step = deepcopy(manual["steps"][0])
        manual_step.pop("source_evidence")
        manual_step.update(step_id="step-2", provenance="observed")
        manual["steps"].append(manual_step)
        saved_manual = library.save_workflow_program(candidate["workflow_id"], edited["content_sha256"],
                                                     manual, "manual-read")
        assert saved_manual["definition"]["steps"][1]["provenance"] == "manual"
        assert saved_manual["definition"]["steps"][1]["review_status"] == "pending"
        removed_source = deepcopy(saved_manual["definition"])
        removed_source["steps"][0].pop("source_evidence")
        removed = library.save_workflow_program(candidate["workflow_id"], saved_manual["content_sha256"],
                                                removed_source, "remove-source")
        assert removed["definition"]["steps"][0]["provenance"] == "manual"
        protected = workflow_control(library, session, request, "compile-after-save")
        assert protected["existing_program_id"] == removed["program_id"]


def test_failed_read_breaks_observed_success_chain(recorded):
    library, bundle, memory = recorded
    first = bundle["segments"][0]["events"][0]
    first.update(request_id="run1", started_at="2026-09-29T00:00:00+00:00")
    middle = deepcopy(first)
    middle.update(request_id="read2", kind="read_text", operation="read_text", action_executed=False,
                  started_at="2026-09-29T00:00:01+00:00", status="failed")
    last = deepcopy(first)
    last.update(request_id="run3", started_at="2026-09-29T00:00:02+00:00")
    bundle["segments"][0]["events"] = [first, middle, last]
    bundle["segments"][0]["reviews"] = {"run1": bundle["segments"][0]["reviews"]["run1"],
        "read2": None, "run3": deepcopy(bundle["segments"][0]["reviews"]["run1"])}
    middle_node = {"node_id": "middle"}
    memory["graph"]["nodes"].append(middle_node)
    memory["graph"]["edges"][0]["target_node_id"] = "middle"
    last_edge = deepcopy(memory["graph"]["edges"][0])
    last_edge.update(edge_id="edge3", event_id="run3", source_node_id="middle", target_node_id="results")
    memory["graph"]["edges"].append(last_edge)
    library.load_graph_revision = lambda workflow_id: {"source_refs": {"kind": "execution_memory"},
        "graph": {"edges": [{"edge_id": "edge1", "evidence": {"learning_id": LEARNING, "event_id": "run1"}},
                            {"edge_id": "edge3", "evidence": {"learning_id": LEARNING, "event_id": "run3"}}]}}
    candidate = workflow_control(library, None, {"action": "compile", "learning_session_id": LEARNING}, "compile")
    assert len(candidate["definition"]["steps"]) == 2
    assert candidate["definition"]["steps"][0]["branches"]["success"] is None
    assert "observed_sequence_interrupted" in {row["reason"] for row in candidate["unresolved_items"]}
