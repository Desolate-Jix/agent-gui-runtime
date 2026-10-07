"""从已归档的终态学习证据编译只读程序候选。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import re

from .graph_source import bundle_segments, read_source
from .reader import read_project
from .receipt_adapter import content_hash
from .target_recipe import action_semantics_sha256, load_target_recipe, validate_target_reference
from .workflow_program import WorkflowProgramService, _draft, validate_definition


_LEARNING = re.compile(r"learning-[0-9a-f]{32}\Z")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class LearningAnnotationError(ValueError):
    """只标记可由整理回复纠正的字段，来源与存储故障保持原错误。"""

    def __init__(self, code, event_id, field="annotations"):
        super().__init__(code)
        self.learning_event_id = event_id
        self.field = field + "." + event_id


def _source_segment(library, learning_id):
    catalog = library.list_workflow_graphs()
    if not isinstance(catalog, list) or len(catalog) > 1024:
        raise ValueError("learning_catalog_unbounded")
    matches = []
    for row in catalog:
        workflow_id = row["logical_workflow_id"]
        source = library.load_graph_revision(workflow_id)
        refs = source.get("source_refs") or {}
        if refs.get("kind") != "execution_memory":
            continue
        bundle = read_source(library, refs)
        for segment in bundle_segments(bundle):
            if segment["manifest"]["learning_id"] == learning_id:
                matches.append((workflow_id, source, segment))
    if len(matches) != 1:
        raise ValueError("learning_segment_missing_or_ambiguous")
    return matches[0]


def _terminal(event):
    if event.get("status") != "returned":
        return False
    receipt = event.get("terminal_receipt")
    if receipt is not None and (not isinstance(receipt, dict) or receipt.get("status") != "completed"):
        return False
    if event.get("kind") == "read_text":
        return event.get("after", {}).get("status") == "referenced"
    if event.get("action_executed") is not True:
        return False
    if event.get("kind") == "input_sequence" and (
            event.get("sequence_status") != "completed" or event.get("interrupted_at") is not None):
        return False
    return True


def _parameter(value, event):
    if (not isinstance(value, dict) or set(value) != {"name", "example_value"}
            or not isinstance(value["name"], str) or not _NAME.fullmatch(value["name"])
            or not isinstance(value["example_value"], str) or not 1 <= len(value["example_value"]) <= 20000):
        raise ValueError("parameter_binding_invalid")
    recorded = event.get("input_text")
    if (not isinstance(recorded, dict) or
            sha256(value["example_value"].encode("utf-8")).hexdigest() != recorded.get("sha256")):
        raise ValueError("parameter_example_mismatch")
    return {"kind": "variable", "name": value["name"]}


def _annotation(value):
    if not isinstance(value, dict) or set(value) - {"title", "target_memory", "verification", "read_spec", "outputs"}:
        raise ValueError("learning_annotation_invalid")
    if "title" in value and (not isinstance(value["title"], str) or not 1 <= len(value["title"].strip()) <= 4000):
        raise ValueError("learning_annotation_invalid")
    if "target_memory" in value:
        validate_target_reference(value["target_memory"])
    if "verification" in value and not isinstance(value["verification"], dict):
        raise ValueError("learning_annotation_invalid")
    if "read_spec" in value and not isinstance(value["read_spec"], dict):
        raise ValueError("learning_annotation_invalid")
    if "outputs" in value and (not isinstance(value["outputs"], list) or len(value["outputs"]) > 128):
        raise ValueError("learning_annotation_invalid")
    return value


def _action_order(events):
    actions = [event for event in events.values() if event.get("kind") in {"step", "input_sequence", "read_text"}]
    if len(actions) < 2:
        return [], True
    timed = []
    for event in actions:
        stamp = event.get("started_at")
        try:
            parsed = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None:
            return [], False
        timed.append((parsed, event["request_id"]))
    if len({stamp for stamp, _ in timed}) != len(timed):
        return [], False
    return [event_id for _, event_id in sorted(timed)], True


def compile_workflow_draft(library, *, learning_session_id: str,
                           parameter_bindings: dict, annotations: dict) -> dict:
    """只读生成候选；调用方审核后用原有 save API 建立新版本。"""
    if not isinstance(learning_session_id, str) or not _LEARNING.fullmatch(learning_session_id):
        raise ValueError("learning_session_id_invalid")
    if not isinstance(parameter_bindings, dict) or not isinstance(annotations, dict):
        raise ValueError("learning_compiler_bindings_invalid")
    workflow_id, source, segment = _source_segment(library, learning_session_id)
    manifest = segment["manifest"]
    if manifest["start_spec"].get("scope") != "workflow":
        raise ValueError("workflow_segment_required")
    events = {event["request_id"]: event for event in segment["events"]}
    if len(events) != len(segment["events"]):
        raise ValueError("learning_event_duplicate")
    if set(parameter_bindings) - set(events) or set(annotations) - set(events):
        raise ValueError("learning_compiler_unknown_event")
    for event_id, value in parameter_bindings.items():
        _parameter(value, events[event_id])
    for value in annotations.values():
        _annotation(value)
    memory = read_project(library, workflow_id)
    existing = WorkflowProgramService(library)._head(workflow_id)
    if existing["program_id"] is not None:
        saved = WorkflowProgramService(library).load(workflow_id, existing["program_id"])
        return {"workflow_id": workflow_id, "project_snapshot_id": saved["project_snapshot_id"],
                "definition": deepcopy(saved["definition"]),
                "unresolved_items": [{"event_id": None, "reason": "existing_program_revision_preserved"}],
                "evidence_refs": [], "proposed_target_recipes": [],
                "existing_program_id": saved["program_id"]}
    reviews = segment["reviews"]
    action_order, order_verified = _action_order(events)
    raw_edges = {edge["edge_id"]: edge for edge in source["graph"]["edges"]}
    eligible, unresolved, evidence_refs = [], [], []
    for event_id, event in events.items():
        record = reviews.get(event_id)
        if not _terminal(event):
            unresolved.append({"event_id": event_id, "reason": "execution_not_terminal"})
        elif record is None or record["review"]["verdict"] != "success":
            unresolved.append({"event_id": event_id, "reason": "success_review_required"})
        elif (record["review"].get("after") is None
              or record["review"]["after"].get("frame_sha256") != event.get("after", {}).get("sha256")
              or (event.get("kind") != "read_text" and
                  (record["review"].get("before") is None or
                   record["review"]["before"].get("frame_sha256") != event.get("before", {}).get("sha256")))):
            unresolved.append({"event_id": event_id, "reason": "transition_identity_incomplete"})
        elif event.get("kind") not in {"step", "input_sequence", "read_text"}:
            unresolved.append({"event_id": event_id, "reason": "not_a_workflow_action"})
        else:
            eligible.append(event_id)
    selected = []
    selected_events = set()
    for edge in memory["graph"]["edges"]:
        original = raw_edges.get(edge["edge_id"])
        evidence = original.get("evidence", {}) if original else {}
        event_id = evidence.get("event_id")
        if (event_id not in eligible or edge.get("provenance") != "observed_action_agent_judged"
                or evidence.get("learning_id", learning_session_id) != learning_session_id):
            continue
        event = events[event_id]
        if event["kind"] == "read_text":
            raise ValueError("learning_read_transition_edge_unexpected")
        if evidence.get("event_sha256") not in (None, content_hash(event)):
            raise ValueError("learning_edge_event_evidence_mismatch")
        action_hints = edge.get("action_hints") or {}
        if (event["kind"] == "input_sequence" and
                (not isinstance(action_hints.get("field_goal"), str) or
                 type(action_hints.get("submit_search")) is not bool)):
            unresolved.append({"event_id": event_id, "reason": "action_definition_required"})
            continue
        if event["kind"] == "step" and (
                event.get("operation") != "execute_recognition_plan"
                or not isinstance(action_hints.get("goal"), str)
                or action_hints.get("click_kind", "single") not in {"single", "double"}):
            unresolved.append({"event_id": event_id, "reason": "action_definition_required"})
            continue
        if event_id in selected_events:
            raise ValueError("learning_event_multiple_action_edges")
        selected_events.add(event_id)
        row = deepcopy(edge)
        if event_id in parameter_bindings:
            row["input_binding"] = _parameter(parameter_bindings[event_id], event)
        selected.append(row)
        evidence_refs.append({"event_id": event_id, "event_sha256": content_hash(event),
                              "review_sha256": reviews[event_id]["review_sha256"],
                              "terminal_status": (event.get("terminal_receipt") or {}).get("status", "completed")})
    filtered = deepcopy(memory)
    filtered["graph"]["edges"] = selected
    definition = _draft(filtered)
    rows = [{"step": step, "edge": edge, "evidence": evidence}
            for step, edge, evidence in zip(definition["steps"], selected, evidence_refs)]
    source_nodes = {node["node_id"]: node for node in source["graph"].get("nodes", [])}
    memory_nodes = {node["node_id"] for node in memory["graph"]["nodes"]}
    for event_id in eligible:
        event = events[event_id]
        if event.get("kind") != "read_text":
            continue
        after = reviews[event_id]["review"]["after"]
        node_id = "state-" + content_hash([after["interface_key"], after["state_key"]])[:32]
        source_node = source_nodes.get(node_id)
        if (source_node is None or node_id not in memory_nodes
                or source_node.get("memory_identity") != {"interface_key": after["interface_key"],
                                                         "state_key": after["state_key"]}):
            unresolved.append({"event_id": event_id, "reason": "read_state_not_in_source"})
            continue
        step = {"step_id": "", "title": "读取当前界面", "source_node_id": node_id,
                "target_node_id": node_id, "action": {"kind": "read_text", "goal": "读取当前界面可见文字"},
                "source_evidence": {"learning_id": learning_session_id, "event_id": event_id,
                                    "event_sha256": content_hash(event),
                                    "review_sha256": reviews[event_id]["review_sha256"]},
                "preconditions": [], "success_conditions": [],
                "branches": {"success": None, "failure": None, "uncertain": None},
                "outputs": [], "review_status": "pending", "provenance": "observed"}
        rows.append({"step": step, "edge": None, "evidence": {
            "event_id": event_id, "event_sha256": content_hash(event),
            "review_sha256": reviews[event_id]["review_sha256"],
            "terminal_status": (event.get("terminal_receipt") or {}).get("status", "completed")}})
    if order_verified and action_order:
        rank = {event_id: index for index, event_id in enumerate(action_order)}
        rows.sort(key=lambda item: rank[item["evidence"]["event_id"]])
    else:
        rows.sort(key=lambda item: item["evidence"]["event_id"])
        if len(rows) > 1:
            unresolved.append({"event_id": None, "reason": "action_order_unverified"})
    for index, row in enumerate(rows):
        row["step"]["step_id"] = "step-" + str(index + 1)
        row["step"]["branches"]["success"] = None
    definition["steps"] = [row["step"] for row in rows]
    evidence_refs = [row["evidence"] for row in rows]
    if order_verified and action_order:
        rank = {event_id: index for index, event_id in enumerate(action_order)}
        for index, (left, right) in enumerate(zip(evidence_refs, evidence_refs[1:])):
            if rank[right["event_id"]] != rank[left["event_id"]] + 1:
                unresolved.append({"event_id": left["event_id"],
                                   "reason": "observed_sequence_interrupted",
                                   "next_event_id": right["event_id"]})
            elif rows[index]["step"]["target_node_id"] == rows[index + 1]["step"]["source_node_id"]:
                definition["steps"][index]["branches"]["success"] = definition["steps"][index + 1]["step_id"]
    proposed = []
    for row in rows:
        step, evidence = row["step"], row["evidence"]
        event_id = evidence["event_id"]
        note = annotations.get(event_id, {})
        image_check = (note.get("verification") or {}).get("image_check")
        if image_check is not None:
            if not isinstance(image_check, dict):
                raise LearningAnnotationError("image_check_config_invalid", event_id)
            after = reviews[event_id]["review"].get("after") or {}
            if image_check.get("reference_sha256") != after.get("frame_sha256"):
                raise LearningAnnotationError("image_check_reference_not_event_after", event_id,
                                              "annotations")
        if "title" in note:
            step["title"] = note["title"]
        for key in ("outputs", "verification", "read_spec"):
            if key in note:
                step[key] = deepcopy(note[key])
                step["provenance"] = "editorial"
        if "verification" in note:
            unresolved.append({"event_id": event_id, "reason": "editorial_verification_unverified"})
        if "read_spec" in note:
            unresolved.append({"event_id": event_id, "reason": "agent_read_required" if note["read_spec"].get("method") == "agent_read"
                               else "editorial_read_spec_unverified"})
        from .image_verification_proposal import apply_default_image_verification
        if apply_default_image_verification(library, step, events[event_id]):
            step["provenance"] = "editorial"
            unresolved.append({"event_id": event_id, "reason": "proposed_image_verification_needs_review"})
        ref = note.get("target_memory") or step["action"].get("target_memory")
        if ref is not None:
            if step["action"]["kind"] == "read_text":
                raise LearningAnnotationError("learning_read_target_memory_unsupported", event_id)
            recipe = load_target_recipe(library, ref)
            if action_semantics_sha256(step["action"], scope=recipe["scope"],
                                       strategies=recipe["strategies"]) != recipe["action_semantics_sha256"]:
                raise LearningAnnotationError("learning_target_semantics_mismatch", event_id)
            step["action"]["target_memory"] = validate_target_reference(ref)
            proposed.append({"event_id": event_id, "reference": deepcopy(ref),
                             "source": "existing_pinned_reference"})
            if "target_memory" in note:
                step["provenance"] = "editorial"
        elif step["action"]["kind"] != "read_text":
            observation_ref = segment.get("target_observations", {}).get(event_id)
            node = source_nodes.get(step["source_node_id"], {})
            pin = node.get("interface_reference") or {}
            if observation_ref is not None and pin:
                from .learning_observation_source import load_learning_observation
                from .target_recipe_proposal import propose_target_recipe
                interface = library.load_interface_content(pin["interface_id"], pin["version_id"])
                observation = load_learning_observation(library, observation_ref)
                action_evidence = {"kind": "learning_action", "project_id": source["source_refs"]["project_id"],
                    "bundle_sha256": source["source_refs"]["bundle_sha256"],
                    "session_id": manifest["session_id"], "learning_id": manifest["learning_id"],
                    "event_id": event_id, "source_node_id": step["source_node_id"],
                    "observation_sha256": observation_ref["sha256"]}
                proposal = propose_target_recipe(event=events[event_id], observation=observation,
                    bindings={"action": step["action"], "interface": interface,
                              "action_evidence": action_evidence, "review": reviews[event_id]["review"],
                              "inputs": {value["name"]: value["example_value"] for value in parameter_bindings.values()}})
                if proposal["recipe"] is not None:
                    recipe = proposal["recipe"]
                    reference = {"recipe_id": recipe["recipe_id"],
                                 "interface_key": recipe["scope"]["interface_key"],
                                 "state_key": recipe["scope"]["state_key"]}
                    proposed.append({"event_id": event_id, "step_id": step["step_id"],
                                     "source": "captured_uia_proposal", "reference": reference,
                                     "observation_ref": deepcopy(observation_ref), "recipe": recipe})
                    # 动作来源独立固定，代表界面 pin 保持原样；编译仍不写库。
                    step["action"]["target_memory"] = reference
                    step["review_status"] = "pending"
                    unresolved.append({"event_id": event_id, "reason": "proposed_target_rule_requires_review"})
                unresolved.extend({"event_id": event_id, **item} for item in proposal["unresolved_items"])
            else:
                unresolved.append({"event_id": event_id, "reason": "target_rule_required"})
        if "verification" not in step and "read_spec" not in step:
            unresolved.append({"event_id": event_id, "reason": "read_spec_required" if step["action"]["kind"] == "read_text"
                               else "verification_rule_required"})
    node_ids = {node["node_id"] for node in memory["graph"]["nodes"]}
    try:
        validate_definition(definition, node_ids)
    except ValueError as error:
        row = next((row for row in rows if row["step"]["step_id"] == getattr(error, "step_id", None)), None)
        if row is not None:
            event_id = row["evidence"]["event_id"]
            if set(annotations.get(event_id, {})) & {"outputs", "verification", "read_spec"}:
                raise LearningAnnotationError(str(error), event_id) from error
        raise
    return {"workflow_id": workflow_id, "project_snapshot_id": memory["snapshot_id"],
            "definition": definition, "unresolved_items": unresolved,
            "evidence_refs": evidence_refs, "proposed_target_recipes": proposed,
            "existing_program_id": None}


__all__ = ["compile_workflow_draft"]
