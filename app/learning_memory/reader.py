"""固定项目快照供 Agent 按需读取；生成建议，不调度或重放输入。"""
from copy import deepcopy

from app.desktop_review.workflow_project import WorkflowProjectService
from .graph_source import read_source, bundle_segments


def read_project(library, workflow_id, snapshot_id=None, node_id=None):
    value = WorkflowProjectService(library).memory("memory-local", workflow_id, snapshot_id)
    source = library.load_graph_revision(workflow_id, value["source_revision"])
    source_kind = source["source_refs"].get("kind")
    if source_kind not in {"execution_memory", "interface_composition"}:
        raise ValueError("this reader requires execution memory or an interface composition")
    bundle = read_source(library, source["source_refs"]) if source_kind == "execution_memory" else None
    events = {(event["learning_id"], event["request_id"]): event
              for segment in bundle_segments(bundle) for event in segment["events"]} if bundle else {}
    raw_edges = {edge["edge_id"]: edge for edge in source["graph"]["edges"]}
    graph = value["graph"]
    graph.pop("action_memory", None)
    for node in graph["nodes"]:
        for region in node.get("regions", []):
            region.pop("bbox", None)
    for edge in graph["edges"]:
        original = raw_edges.get(edge["edge_id"])
        if bundle is None or edge.get("editorial") or original is None:
            edge["provenance"] = "editorial_not_observed"
            continue
        evidence = original["evidence"]
        event = events[(evidence.get("learning_id", bundle["manifest"]["learning_id"]), evidence["event_id"])]
        edge.update(provenance="observed_action_agent_judged", input_binding=deepcopy(original["input_binding"]),
                    action_hints=deepcopy(event.get("action_hints", {})),
                    event_id=event["request_id"], operation=event.get("operation") or event["kind"],
                    input_binding_required=original["input_binding_required"])
    if node_id is not None:
        if node_id not in {node["node_id"] for node in graph["nodes"]}:
            raise ValueError("node is not part of this fixed snapshot")
        graph["edges"] = [edge for edge in graph["edges"] if edge["source_node_id"] == node_id]
        visible = {node_id} | {edge["target_node_id"] for edge in graph["edges"]}
        graph["nodes"] = [node for node in graph["nodes"] if node["node_id"] in visible]
        graph["workflow"]["node_ids"] = [node["node_id"] for node in graph["nodes"]]
        graph["workflow"]["edge_ids"] = [edge["edge_id"] for edge in graph["edges"]]
    value.update(current_grounding_required=True, partial_view=node_id is not None,
                 automatic_retry_allowed=False, input_executed=False)
    return value


def prepare_reuse(library, workflow_id, snapshot_id, edge_id, variables):
    memory = read_project(library, workflow_id, snapshot_id)
    matches = [edge for edge in memory["graph"]["edges"] if edge["edge_id"] == edge_id]
    if len(matches) != 1:
        raise ValueError("edge is absent from this fixed project snapshot")
    edge = matches[0]
    if edge.get("provenance") != "observed_action_agent_judged":
        raise ValueError("editorial relationship has no recorded operation; Agent must plan a fresh action")
    binding = edge.get("input_binding")
    if edge.get("input_binding_required"):
        raise ValueError("declare the recorded input as a variable or constant before reuse")
    required = {binding["name"]} if binding and binding["kind"] == "variable" else set()
    if not isinstance(variables, dict) or set(variables) != required:
        raise ValueError("variables must exactly match: " + ", ".join(sorted(required)))
    if any(not isinstance(value, str) or not 1 <= len(value) <= 20000 for value in variables.values()):
        raise ValueError("variable values must contain 1-20000 characters")
    text = variables[binding["name"]] if required else binding["value"] if binding else None
    hints = edge.get("action_hints") or {}
    command = None
    if edge["operation"] == "input_sequence" and text is not None:
        if not isinstance(hints.get("field_goal"), str) or type(hints.get("submit_search")) is not bool:
            raise ValueError("recorded input sequence lacks field intent or explicit submit semantics")
        command = {"kind": "input_sequence", "request": {"field_goal": hints["field_goal"], "text": text,
            "clear_existing": hints.get("clear_existing", True), "submit_search": hints["submit_search"]}}
        if hints.get("template_memory") is not None:
            from .target_recipe import recipe_from_template
            command["request"]["target_memory"] = recipe_from_template(library, hints["template_memory"],
                {"kind": "input_sequence", "field_goal": hints["field_goal"], "submit_search": hints["submit_search"]})
        elif hints.get("target_memory") is not None:
            from .target_recipe import validate_target_reference
            command["request"]["target_memory"] = validate_target_reference(hints["target_memory"])
    elif edge["operation"] == "execute_recognition_plan" and isinstance(hints.get("goal"), str):
        click_kind = hints.get("click_kind", "single")
        if click_kind not in {"single", "double", "right"}:
            raise ValueError("recorded click kind is unsupported; Agent must plan a fresh action")
        command = {"kind": "step", "operation": "execute_recognition_plan",
                   "request": {"goal": hints["goal"], "click_kind": click_kind}}
        if hints.get("template_memory") is not None:
            from .target_recipe import recipe_from_template
            command["request"]["target_memory"] = recipe_from_template(library, hints["template_memory"],
                {"kind": "click", "goal": hints["goal"], "click_kind": click_kind})
        elif hints.get("target_memory") is not None:
            from .target_recipe import validate_target_reference
            command["request"]["target_memory"] = validate_target_reference(hints["target_memory"])
    # 其他操作仍由 Agent 根据当前界面建立请求，不能补入历史点位或默认焦点。
    return {"contract_version": "instant_memory_reuse_advice_v1", "workflow_id": workflow_id,
        "snapshot_id": memory["snapshot_id"], "edge_id": edge_id,
        "status": "agent_decision_required" if command else "fresh_action_request_required",
        "suggested_command": command, "operation": edge["operation"], "action_hints": hints,
        "resolved_text": text if command is None else None, "current_grounding_required": True,
        "input_executed": False, "automatic_retry_allowed": False,
        "next": "Observe current target, check source state, then use existing instant_run with a NEW request_id; inspect its result before deciding the next edge."}
