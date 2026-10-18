"""将程序定义投影为只读步骤关系图，不混用现场观察图。"""

from __future__ import annotations

from .workflow_program import _id


def project_program_graph(definition: dict) -> dict:
    if not isinstance(definition, dict) or not isinstance(definition.get("steps"), list):
        raise ValueError("program_graph_definition_invalid")
    steps = definition["steps"]
    if len(steps) > 256:
        raise ValueError("program_graph_steps_limit")
    nodes = []
    identities = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("program_graph_step_invalid")
        step_id = _id(step.get("step_id"), "step_id")
        title = step.get("title")
        if step_id in identities:
            raise ValueError("program_graph_step_duplicate")
        if not isinstance(title, str) or not title.strip() or len(title) > 4000:
            raise ValueError("program_graph_title_invalid")
        identities.add(step_id)
        nodes.append({"node_id": step_id, "source_step_id": step_id, "display_name": title})
    edges = []
    for step in steps:
        branches = step.get("branches")
        if not isinstance(branches, dict) or set(branches) != {"success", "failure", "uncertain"}:
            raise ValueError("program_graph_branches_invalid")
        if branches["uncertain"] is not None:
            raise ValueError("program_graph_uncertain_must_pause")
        for branch, label in (("success", "成功"), ("failure", "失败")):
            target = branches[branch]
            if target is None:
                continue
            if not isinstance(target, str) or target not in identities:
                raise ValueError("program_graph_branch_target_invalid")
            edges.append({"edge_id": step["step_id"] + ":" + branch,
                          "source_node_id": step["step_id"], "target_node_id": target,
                          "branch": branch, "label": label, "action_type": "program_branch"})
    return {"graph": {"display_only": True, "artifact_is_authorization": False,
                      "execute_binding_enabled": False, "nodes": nodes, "edges": edges}}


__all__ = ["project_program_graph"]
