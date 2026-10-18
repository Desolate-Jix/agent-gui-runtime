"""固定项目快照上的可编辑语义步骤；不保存图像，也不执行输入。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _atomic_write_bytes, _write_immutable
from .reader import read_project
from .target_recipe import validate_target_reference, load_target_recipe, action_semantics_sha256, recipe_from_template, validate_editorial_action
from .graph_source import bundle_segments, read_source
from .receipt_adapter import content_hash


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
_WORKFLOW = re.compile(r"workflow-[0-9a-f]{64}\Z")
_PROGRAM = re.compile(r"task-program-[0-9a-f]{64}\Z")
_TYPES = {"text": str, "number": (int, float), "boolean": bool}
_KINDS = {"click", "input_sequence", "read_text", "scroll", "press_key"}
_LEARNING = re.compile(r"learning-[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _id(value, label, pattern=_ID):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label}_invalid")
    return value


def _json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError("task_program_file_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("task_program_file_invalid")
    return value


def _type(value, kind):
    return (type(value) is bool if kind == "boolean" else
            type(value) in (int, float) if kind == "number" else
            isinstance(value, str) and len(value) <= 20000)


def _variables(items, label):
    if not isinstance(items, list) or len(items) > 128:
        raise ValueError(f"{label}_invalid")
    seen = set()
    for item in items:
        fields = {"name", "type", "required"} if label == "inputs" else {"name", "type", "step_id"} if label == "program_outputs" else {"name", "type"}
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"{label}_invalid")
        name = _id(item["name"], label)
        if name in seen or item["type"] not in _TYPES or (label == "inputs" and type(item["required"]) is not bool):
            raise ValueError(f"{label}_invalid")
        seen.add(name)
    return {item["name"]: item["type"] for item in items}


def _source_evidence_shape(value):
    if (not isinstance(value, dict)
            or set(value) != {"learning_id", "event_id", "event_sha256", "review_sha256"}
            or not isinstance(value["learning_id"], str) or not _LEARNING.fullmatch(value["learning_id"])
            or not isinstance(value["event_id"], str) or not _ID.fullmatch(value["event_id"])
            or any(not isinstance(value[key], str) or not _HASH.fullmatch(value[key])
                   for key in ("event_sha256", "review_sha256"))):
        raise ValueError("task_program_source_evidence_invalid")
    return value


def _reference(ref, inputs, available, label):
    if not isinstance(ref, dict) or ref.get("source") not in {"constant", "input", "output"}:
        raise ValueError(f"{label}_reference_invalid")
    source = ref["source"]
    fields = {"source", "value"} if source == "constant" else {"source", "name"} if source == "input" else {"source", "name", "step_id"}
    if set(ref) != fields:
        raise ValueError(f"{label}_reference_invalid")
    if source == "constant":
        if not isinstance(ref["value"], (str, int, float, bool)) or len(str(ref["value"])) > 20000:
            raise ValueError(f"{label}_reference_invalid")
        return "text" if isinstance(ref["value"], str) else "boolean" if type(ref["value"]) is bool else "number"
    name = _id(ref["name"], label)
    if source == "input":
        if name not in inputs:
            raise ValueError(f"{label}_input_unknown")
        return inputs[name]
    step_id = _id(ref["step_id"], label)
    if (step_id, name) not in available:
        raise ValueError(f"{label}_upstream_output_unknown")
    return available[(step_id, name)]


def _condition(item, inputs, available):
    if not isinstance(item, dict) or set(item) not in ({"left", "operator"}, {"left", "operator", "value"}):
        raise ValueError("condition_invalid")
    operator = item["operator"]
    if operator not in {"exists", "eq", "not_eq", "contains", "agent_assertion"}:
        raise ValueError("condition_operator_invalid")
    left = item["left"]
    if not isinstance(left, dict) or left.get("source") not in {"input", "output", "observation"}:
        raise ValueError("condition_source_invalid")
    left_type = None
    if left["source"] == "observation":
        if set(left) != {"source", "name"}:
            raise ValueError("condition_source_invalid")
        _id(left["name"], "observation")
    else:
        if operator == "agent_assertion":
            raise ValueError("condition_agent_assertion_requires_observation")
        left_type = _reference(left, inputs, available, "condition")
    if operator in {"eq", "not_eq", "contains"} and "value" not in item:
        raise ValueError("condition_value_required")
    if operator in {"exists", "agent_assertion"} and "value" in item:
        raise ValueError("condition_value_unexpected")
    if "value" in item and not isinstance(item["value"], (str, int, float, bool)):
        raise ValueError("condition_value_invalid")
    if left_type is not None and operator in {"eq", "not_eq"} and not _type(item["value"], left_type):
        raise ValueError("condition_value_type_invalid")
    if operator == "contains" and (left_type not in {None, "text"} or not isinstance(item["value"], str)):
        raise ValueError("condition_contains_type_invalid")


def _step_rules(step, inputs, available, declarations):
    from .workflow_verification import KINDS, READ_METHODS, validate_observation_target
    verification = step.get("verification")
    read_spec = step.get("read_spec")
    if "verification" in step:
        if not isinstance(verification, dict) or verification.get("kind") not in KINDS:
            raise ValueError("task_program_verification_invalid")
        kind = verification["kind"]
        required = {"kind"} if kind == "agent_judgment" else {"kind", "target"}
        if kind in {"field_equals", "text_equals", "text_contains"}:
            required.add("expected")
        optional = {"output_name", "image_check"} if kind == "agent_judgment" else {"output_name"}
        if not required <= set(verification) or set(verification) - required - optional:
            raise ValueError("task_program_verification_fields_invalid")
        if "image_check" in verification:
            from .image_verification import validate_image_check
            validate_image_check(verification["image_check"])
            if step.get("outputs") or "read_spec" in step or step["action"]["kind"] == "read_text":
                raise ValueError("task_program_image_check_dynamic_read_forbidden")
        if "target" in verification:
            validate_observation_target(verification["target"])
        expected_type = None
        if "expected" in verification:
            expected_type = _reference(verification["expected"], inputs, available, "verification")
            if kind in {"text_equals", "text_contains"} and expected_type != "text":
                raise ValueError("task_program_verification_text_required")
        if "output_name" in verification:
            name = verification["output_name"]
            if name not in declarations or kind == "agent_judgment":
                raise ValueError("task_program_verification_output_invalid")
            actual_type = "boolean" if kind in {"target_present", "target_absent"} else expected_type
            if declarations[name] != actual_type:
                raise ValueError("task_program_verification_output_type_invalid")
    if "read_spec" in step:
        if (not isinstance(read_spec, dict) or set(read_spec) != {"method", "output_name", "target"}
                or read_spec.get("method") not in READ_METHODS
                or read_spec.get("output_name") not in declarations):
            raise ValueError("task_program_read_spec_invalid")
        validate_observation_target(read_spec["target"])
        if read_spec["method"] in {"uia_value", "visible_text"} and declarations[read_spec["output_name"]] != "text":
            raise ValueError("task_program_read_output_text_required")
        if verification is not None and verification.get("target") != read_spec["target"]:
            raise ValueError("task_program_result_targets_mismatch")


def validate_definition(definition, node_ids):
    if not isinstance(definition, dict) or set(definition) != {"title", "inputs", "outputs", "steps"}:
        raise ValueError("task_program_definition_invalid")
    if not isinstance(definition["title"], str) or not 1 <= len(definition["title"].strip()) <= 4000:
        raise ValueError("task_program_title_invalid")
    inputs = _variables(definition["inputs"], "inputs")
    _variables(definition["outputs"], "program_outputs")
    steps = definition["steps"]
    if not isinstance(steps, list) or len(steps) > 256:
        raise ValueError("task_program_steps_invalid")
    ids = [_id(step.get("step_id") if isinstance(step, dict) else None, "step") for step in steps]
    if len(set(ids)) != len(ids):
        raise ValueError("task_program_step_duplicate")
    available = {}
    for step in steps:
        fields = {"step_id", "title", "source_node_id", "target_node_id", "action", "preconditions", "success_conditions", "branches", "outputs", "review_status", "provenance"}
        if not fields <= set(step) or set(step) - fields - {"verification", "read_spec", "source_evidence"}:
            raise ValueError("task_program_step_fields_invalid")
        if not isinstance(step["title"], str) or not step["title"].strip() or len(step["title"]) > 4000:
            raise ValueError("task_program_step_title_invalid")
        if step["source_node_id"] is not None and step["source_node_id"] not in node_ids:
            raise ValueError("task_program_source_node_invalid")
        if step["target_node_id"] is not None and step["target_node_id"] not in node_ids:
            raise ValueError("task_program_target_node_invalid")
        if step["review_status"] not in {"pending", "reviewed"} or step["provenance"] not in {"observed", "editorial", "manual"}:
            raise ValueError("task_program_review_invalid")
        action = step["action"]
        if not isinstance(action, dict) or action.get("kind") not in _KINDS:
            raise ValueError("task_program_action_invalid")
        kind = action["kind"]
        from .selection_satisfaction import validate_selection_intent
        validate_selection_intent(action)
        if "source_evidence" in step:
            if kind != "read_text":
                raise ValueError("task_program_source_evidence_action_invalid")
            _source_evidence_shape(step["source_evidence"])
        fields = {"kind", "goal"} if kind in {"click", "read_text"} else {"kind", "field_goal", "text", "clear_existing", "submit_search"} if kind == "input_sequence" else {"kind", "direction", "amount"} if kind == "scroll" else {"kind", "key"}
        if kind == "click" and "click_kind" in action:
            fields.add("click_kind")
            if action["click_kind"] not in {"single", "double"}:
                raise ValueError("task_program_click_kind_invalid")
        if kind == 'click' and 'selection_intent' in action:
            fields.add('selection_intent')
            if action.get('target_memory') is None:
                raise ValueError('selection_row_name_reference_required')
        if kind in {"click", "input_sequence"} and "target_memory" in action:
            if kind == "click" and action.get("click_kind", "single") == "double":
                raise ValueError("task_program_double_click_target_memory_unsupported")
            fields.add("target_memory")
        if set(action) != fields:
            raise ValueError("task_program_action_fields_invalid")
        if "target_memory" in action:
            validate_target_reference(action["target_memory"])
        if kind in {"click", "read_text"} and (not isinstance(action["goal"], str) or not action["goal"].strip()):
            raise ValueError("task_program_goal_invalid")
        if kind == "input_sequence":
            if not isinstance(action["field_goal"], str) or not action["field_goal"].strip() or type(action["clear_existing"]) is not bool or type(action["submit_search"]) is not bool:
                raise ValueError("task_program_input_action_invalid")
            if _reference(action["text"], inputs, available, "action") != "text":
                raise ValueError("task_program_action_text_type_invalid")
        if kind == "scroll" and (action["direction"] not in {"up", "down"} or type(action["amount"]) is not int or not 1 <= action["amount"] <= 20):
            raise ValueError("task_program_scroll_invalid")
        if kind == "press_key" and action["key"] not in {"Enter", "Escape", "Tab", "Backspace"}:
            raise ValueError("task_program_key_invalid")
        try:
            declarations = _variables(step["outputs"], "outputs")
            _step_rules(step, inputs, available, declarations)
        except ValueError as error:
            error.step_id = step["step_id"]
            raise
        own_outputs = {(step["step_id"], name): kind for name, kind in declarations.items()}
        for label in ("preconditions", "success_conditions"):
            if not isinstance(step[label], list) or len(step[label]) > 32:
                raise ValueError("condition_list_invalid")
            for condition in step[label]:
                _condition(condition, inputs, available if label == "preconditions" else {**available, **own_outputs})
        branches = step["branches"]
        if not isinstance(branches, dict) or set(branches) != {"success", "failure", "uncertain"} or branches["uncertain"] is not None:
            raise ValueError("task_program_branches_invalid")
        for branch in ("success", "failure"):
            if branches[branch] is not None and branches[branch] not in ids:
                raise ValueError("task_program_branch_target_invalid")
        available.update(own_outputs)
    declared = {(step["step_id"], item["name"]): item["type"] for step in steps for item in step["outputs"]}
    for item in definition["outputs"]:
        if (item.get("step_id"), item["name"]) not in declared:
            # 顶层输出仅用于展示；来源必须用 step_id 明确指定。
            raise ValueError("task_program_output_source_invalid")
    # 分支必须无环，避免同一次运行重复步骤时混用旧输出。
    graph = {step["step_id"]: [target for target in (step["branches"]["success"], step["branches"]["failure"]) if target is not None] for step in steps}
    visiting, visited = set(), set()
    def visit(step_id):
        if step_id in visiting:
            raise ValueError("task_program_branch_cycle_invalid")
        if step_id in visited:
            return
        visiting.add(step_id)
        for target in graph[step_id]:
            visit(target)
        visiting.remove(step_id)
        visited.add(step_id)
    for step_id in graph:
        visit(step_id)
    return deepcopy(definition)


def _verified_read_sources(library, workflow_id, memory, definition):
    """以固定图来源核对读取事件；调用者的 provenance 不构成证明。"""
    steps = [step for step in definition["steps"] if "source_evidence" in step]
    if not steps:
        return set()
    revision = memory.get("source_revision")
    if type(revision) is not int or revision < 1:
        raise ValueError("task_program_source_evidence_revision_missing")
    source = library.load_graph_revision(workflow_id, revision)
    if source.get("source_refs", {}).get("kind") != "execution_memory":
        raise ValueError("task_program_source_evidence_source_invalid")
    bundle = read_source(library, source["source_refs"])
    segments = bundle_segments(bundle)
    nodes = {node["node_id"]: node for node in source["graph"]["nodes"]}
    project_nodes = {node["node_id"] for node in memory["graph"]["nodes"]}
    seen, verified = set(), set()
    for step in steps:
        ref = _source_evidence_shape(step["source_evidence"])
        identity = (ref["learning_id"], ref["event_id"])
        if identity in seen:
            raise ValueError("task_program_source_evidence_duplicate")
        seen.add(identity)
        matches = [segment for segment in segments if segment["manifest"]["learning_id"] == ref["learning_id"]]
        if len(matches) != 1 or matches[0]["manifest"]["start_spec"].get("scope") != "workflow":
            raise ValueError("task_program_source_evidence_segment_invalid")
        segment = matches[0]
        events = [event for event in segment["events"] if event["request_id"] == ref["event_id"]]
        record = segment["reviews"].get(ref["event_id"])
        if (len(events) != 1 or record is None or record.get("review_sha256") != ref["review_sha256"]):
            raise ValueError("task_program_source_evidence_event_invalid")
        event = events[0]
        review = record["review"]
        after = review.get("after")
        if (content_hash(event) != ref["event_sha256"] or event.get("kind") != "read_text"
                or event.get("status") != "returned" or event.get("after", {}).get("status") != "referenced"
                or (event.get("terminal_receipt") is not None and
                    event["terminal_receipt"].get("status") != "completed")
                or review.get("verdict") != "success" or not isinstance(after, dict)
                or after.get("frame_sha256") != event["after"].get("sha256")):
            raise ValueError("task_program_source_evidence_event_invalid")
        node_id = "state-" + content_hash([after["interface_key"], after["state_key"]])[:32]
        node = nodes.get(node_id)
        if (step["action"]["kind"] != "read_text" or step["source_node_id"] != node_id
                or step["target_node_id"] != node_id or node_id not in project_nodes or node is None
                or node.get("memory_identity") != {"interface_key": after["interface_key"],
                                                   "state_key": after["state_key"]}):
            raise ValueError("task_program_source_evidence_target_invalid")
        verified.add(step["step_id"])
    return verified


def _target_dependencies(definition, recipes):
    inputs = {row["name"]: row["type"] for row in definition["inputs"]}
    available, references = {}, {}
    for step in definition["steps"]:
        dependencies = []
        recipe = recipes.get(step["step_id"])
        for strategy in (recipe or {}).get("strategies", []):
            if strategy["kind"] == "visible_row":
                for item in strategy["constraints"]:
                    try:
                        typ = _reference(item["value"], inputs, available, "target")
                        if typ != "text":
                            raise ValueError("target_row_requires_text")
                    except ValueError as error:
                        error.step_id = step["step_id"]
                        raise
                    dependencies.append(deepcopy(item["value"]))
        references[step["step_id"]] = dependencies
        for output in step["outputs"]:
            available[(step["step_id"], output["name"])] = output["type"]
    return references


def _derive_provenance(definition, baseline, *, verified_read_sources=frozenset(),
                       target_dependencies=None, editorial_targets=frozenset()):
    checked = deepcopy(definition)
    old_steps = {step["step_id"]: step for step in baseline["steps"]}
    changed_inputs = {name for name in {item["name"] for item in baseline["inputs"]} | {item["name"] for item in checked["inputs"]}
                      if next((item for item in baseline["inputs"] if item["name"] == name), None)
                      != next((item for item in checked["inputs"] if item["name"] == name), None)}
    changed_program_outputs = {step_id for step_id in
        {item["step_id"] for item in baseline["outputs"]} | {item["step_id"] for item in checked["outputs"]}
        if [item for item in baseline["outputs"] if item["step_id"] == step_id]
        != [item for item in checked["outputs"] if item["step_id"] == step_id]}
    changed_steps = set()
    for step in checked["steps"]:
        old = old_steps.get(step["step_id"])
        # 显示名称不改变动作与输出语义，也不触发下游重新审核。
        if old is None or {key: value for key, value in step.items() if key not in {"title", "review_status", "provenance"}} != {
                key: value for key, value in old.items() if key not in {"title", "review_status", "provenance"}}:
            changed_steps.add(step["step_id"])
    references_by_step = {step["step_id"]: ([step["action"].get("text")] if isinstance(step["action"], dict) else []) + [(step.get("verification") or {}).get("expected")] + [
        item.get("left") for label in ("preconditions", "success_conditions") for item in step[label]] for step in checked["steps"]}
    for step_id, references in (target_dependencies or {}).items():
        references_by_step[step_id].extend(references)
    affected_steps = changed_steps | changed_program_outputs | {step_id for step_id, references in references_by_step.items()
        if any(isinstance(ref, dict) and ref.get("source") == "input" and ref.get("name") in changed_inputs for ref in references)}
    while True:
        expanded = affected_steps | {step_id for step_id, references in references_by_step.items()
            if any(isinstance(ref, dict) and ref.get("source") == "output" and ref.get("step_id") in affected_steps for ref in references)}
        if expanded == affected_steps:
            break
        affected_steps = expanded
    for step in checked["steps"]:
        old = old_steps.get(step["step_id"])
        affected = step["step_id"] in affected_steps
        if step["step_id"] in editorial_targets:
            step["provenance"] = "editorial"
        elif step["step_id"] in verified_read_sources:
            # 来源来自一次真实只读观察；新规则仍需人工审核。
            step["provenance"] = "editorial"
            if (old is None or old.get("source_evidence") != step.get("source_evidence") or affected):
                step["review_status"] = "pending"
        elif old is None or old.get("source_evidence") is not None:
            step["provenance"] = "manual"
        elif old["provenance"] == "observed":
            step["provenance"] = "editorial" if affected else "observed"
        else:
            step["provenance"] = old["provenance"]
        if affected:
            step["review_status"] = "pending"
    return checked


def _draft(memory, library=None):
    graph = memory["graph"]
    steps, inputs = [], {}
    for index, edge in enumerate(graph["edges"]):
        hints = edge.get("action_hints") or {}
        binding = edge.get("input_binding") or {}
        kind = edge.get("operation") or edge.get("action_type")
        if edge.get("provenance") == "observed_action_agent_judged" and kind == "input_sequence" and isinstance(hints.get("field_goal"), str) and type(hints.get("submit_search")) is bool:
            if binding.get("kind") == "variable":
                name = _id(binding["name"], "input")
                inputs[name] = {"name": name, "type": "text", "required": True}
                text = {"source": "input", "name": name}
            elif binding.get("kind") == "constant":
                text = {"source": "constant", "value": binding["value"]}
            else:
                text = {"source": "constant", "value": ""}
            action = {"kind": "input_sequence", "field_goal": hints["field_goal"], "text": text,
                      "clear_existing": hints.get("clear_existing", True), "submit_search": hints["submit_search"]}
        elif edge.get("provenance") == "observed_action_agent_judged" and kind == "execute_recognition_plan" and isinstance(hints.get("goal"), str):
            action = {"kind": "click", "goal": hints["goal"]}
            if "click_kind" in hints:
                action["click_kind"] = hints["click_kind"]
            if 'selection_intent' in hints:
                action['selection_intent'] = hints['selection_intent']
        else:
            # 人工关系没有已知操作；空目标迫使保存前明确定义。
            action = {"kind": "click", "goal": ""}
        fresh_double = action["kind"] == "click" and action.get("click_kind", "single") == "double"
        if not fresh_double and library is not None and action["kind"] in {"click", "input_sequence"} and hints.get("template_memory") is not None:
            action["target_memory"] = recipe_from_template(library, hints["template_memory"], action)
        elif not fresh_double and action["kind"] in {"click", "input_sequence"} and hints.get("target_memory") is not None:
            action["target_memory"] = validate_target_reference(hints["target_memory"])
        step_id = "step-" + str(index + 1)
        steps.append({"step_id": step_id, "title": str(edge.get("label") or edge.get("operation") or edge.get("action_type") or step_id),
            "source_node_id": edge.get("source_node_id"), "target_node_id": edge.get("target_node_id"),
            "action": action, "preconditions": [], "success_conditions": [],
            "branches": {"success": None, "failure": None, "uncertain": None}, "outputs": [],
            "review_status": "pending", "provenance": "observed" if edge.get("provenance") == "observed_action_agent_judged" else "editorial"})
    for index, step in enumerate(steps[:-1]):
        if step["provenance"] == "observed" and steps[index + 1]["provenance"] == "observed" and step["target_node_id"] == steps[index + 1]["source_node_id"]:
            step["branches"]["success"] = steps[index + 1]["step_id"]
    return {"title": graph["workflow"]["goal"], "inputs": list(inputs.values()), "outputs": [], "steps": steps}


class WorkflowProgramService:
    def __init__(self, library):
        self.library = library
        self.root = Path(library._workspace_root) / "workflow-projects"

    def _dir(self, workflow_id):
        return self.root / _id(workflow_id, "workflow_id", _WORKFLOW) / "task-program"

    def _head(self, workflow_id):
        path = self._dir(workflow_id) / "head.json"
        return _json(path) if path.exists() else {"revision": 0, "program_id": None, "requests": {}}

    def load(self, workflow_id, program_id=None):
        directory = self._dir(workflow_id)
        head = self._head(workflow_id)
        identity = program_id or head["program_id"]
        if identity is not None:
            _id(identity, "program_id", _PROGRAM)
            value = _json(directory / "versions" / (identity + ".json"))
            if value.get("program_id") != identity or value.get("workflow_id") != workflow_id or _digest({k: v for k, v in value.items() if k not in {"program_id", "content_sha256", "review_items"}}) != value.get("content_sha256"):
                raise ValueError("task_program_integrity_invalid")
            read_project(self.library, workflow_id, value["project_snapshot_id"])
            for step in value["definition"]["steps"]:
                action = step["action"]
                if "target_memory" in action:
                    recipe = load_target_recipe(self.library, action["target_memory"])
                    validate_editorial_action(recipe, action)
                    if action_semantics_sha256(action, scope=recipe["scope"], strategies=recipe["strategies"]) != recipe["action_semantics_sha256"]:
                        raise ValueError("task_program_target_memory_semantics_mismatch")
            return value
        memory = read_project(self.library, workflow_id)
        definition = _draft(memory, self.library)
        review_items = [{"step_id": s["step_id"], "reason": "needs_definition" if s["provenance"] != "observed" else "needs_review"} for s in definition["steps"]]
        content = {"workflow_id": workflow_id, "project_snapshot_id": memory["snapshot_id"], "revision": 0, "definition": definition}
        digest = _digest(content)
        return {**content, "program_id": None, "content_sha256": digest, "review_items": review_items}

    def save(self, workflow_id, expected_sha256, definition, request_id, *, target_recipes=None):
        _id(workflow_id, "workflow_id", _WORKFLOW)
        _id(request_id, "request_id")
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("expected_sha256_invalid")
        head = self._head(workflow_id)
        if target_recipes is not None and (not isinstance(target_recipes, list) or len(target_recipes) > 256):
            raise ValueError("task_program_target_recipes_invalid")
        request_body = {"expected_sha256": expected_sha256, "definition": definition}
        if target_recipes:
            request_body["target_recipes"] = target_recipes
        request_digest = _digest(request_body)
        prior = head["requests"].get(request_id)
        if prior is not None:
            if prior["request_sha256"] != request_digest:
                raise ValueError("task_program_idempotency_conflict")
            return self.load(workflow_id, prior["program_id"])
        current = self.load(workflow_id)
        if current["content_sha256"] != expected_sha256:
            raise ValueError("task_program_stale_revision")
        memory = read_project(self.library, workflow_id, current["project_snapshot_id"])
        node_ids = {node["node_id"] for node in memory["graph"]["nodes"]}
        validated = validate_definition(definition, node_ids)
        from .image_verification import load_reference_image
        for step in validated["steps"]:
            check = step.get("verification", {}).get("image_check")
            if check is not None:
                load_reference_image(self.library, check)
        from .target_recipe import _validate_recipe, _check_evidence, save_target_recipe
        proposals = {}
        for item in target_recipes or []:
            recipe = _validate_recipe(item)
            _check_evidence(self.library, recipe)
            if recipe["recipe_id"] in proposals:
                raise ValueError("task_program_target_recipe_duplicate")
            proposals[recipe["recipe_id"]] = recipe
        referenced = {step["action"]["target_memory"]["recipe_id"] for step in validated["steps"]
                      if "target_memory" in step["action"]}
        if set(proposals) - referenced:
            raise ValueError("task_program_target_recipe_unreferenced")
        old_actions = {step["step_id"]: step["action"] for step in current["definition"]["steps"]}
        target_recipes_by_step = {}
        for step in validated["steps"]:
            action = step["action"]
            reference = action.get("target_memory")
            if reference is None:
                continue
            recipe = proposals.get(reference["recipe_id"])
            if recipe is None:
                recipe = load_target_recipe(self.library, reference)
            elif any(recipe["scope"][key] != reference[key] for key in ("interface_key", "state_key")):
                raise ValueError("task_program_target_recipe_reference_mismatch")
            digest = action_semantics_sha256(action, scope=recipe["scope"], strategies=recipe["strategies"])
            if digest != recipe["action_semantics_sha256"]:
                old = old_actions.get(step["step_id"], {})
                if old.get("target_memory") == reference:
                    del action["target_memory"]
                else:
                    raise ValueError("task_program_target_memory_semantics_mismatch")
            if "target_memory" in action:
                validate_editorial_action(recipe, action)
                target_recipes_by_step[step["step_id"]] = recipe
        target_dependencies = _target_dependencies(validated, target_recipes_by_step)
        verified_read_sources = _verified_read_sources(self.library, workflow_id, memory, validated)
        derived = _derive_provenance(validated, current["definition"],
                                     verified_read_sources=verified_read_sources,
                                     target_dependencies=target_dependencies,
                                     editorial_targets={step_id for step_id, recipe in target_recipes_by_step.items()
                                                        if recipe.get("contract_version") == "target_recipe.v3"})
        checked = validate_definition(derived, node_ids)
        content = {"workflow_id": workflow_id, "project_snapshot_id": current["project_snapshot_id"],
                   "revision": current["revision"] + 1, "definition": checked}
        digest = _digest(content)
        identity = "task-program-" + digest
        value = {**content, "program_id": identity, "content_sha256": digest,
                 "review_items": [{"step_id": s["step_id"], "reason": "needs_definition" if s["provenance"] != "observed" else "needs_review"} for s in checked["steps"] if s["review_status"] == "pending"]}
        directory = self._dir(workflow_id)
        # 完整验证后先存不可变规则，最后推进程序头；失败重试不改变原版本。
        for recipe in proposals.values():
            save_target_recipe(self.library, recipe)
        _write_immutable(directory / "versions" / (identity + ".json"), canonical_json_bytes(value) + b"\n")
        requests = {**head["requests"], request_id: {"request_sha256": request_digest, "program_id": identity}}
        _atomic_write_bytes(directory / "head.json", canonical_json_bytes({"revision": content["revision"], "program_id": identity, "requests": requests}) + b"\n")
        return value


__all__ = ["WorkflowProgramService", "validate_definition"]
