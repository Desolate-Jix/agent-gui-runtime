"""结构化目标复用已验证的完整规范图，仍拒绝冲突、迟到重名与坏绑定。"""
from copy import deepcopy

import pytest

from app.execution.task_plan_target import resolve_current_uia_target
from app.operation.screen_reading import uia_provider as provider
from tests.test_task_plan_target import control, current_frame
from tests.test_uia_alias_normalization import Node, install
from tests.test_browser_content_readiness import harness, source, snapshot as readiness_snapshot


def graph_frame(current_frame, monkeypatch, *, edge="sibling", fault=None, duplicate=False,
                budget=100, field=False):
    install(monkeypatch)
    capture, snapshot = current_frame

    def node(rid, identifier, name, kind, box, parent=None):
        value = Node(rid, parent)
        value.identifier, value.name, value.box = identifier, name, box
        value.element_info.control_type = kind
        value.element_info.process_id = value.CurrentProcessId = 22
        value.top_handle = 11
        return value

    root = node(1, "root", "Browser", "Window", (0, 0, 900, 600))
    first = node(2, "find", "Quick search" if field else "Find", "Edit" if field else "Button",
                 (40, 80, 120, 40), root)
    other = node(3, "other", "Other", "Pane", (300, 80, 120, 40), root)
    root.children = [first, other]
    if edge == "sibling":
        root.children = [first, first, other]
    elif edge == "self":
        first.children = [first]
    elif edge == "root":
        first.children = [root]
    elif edge == "cross_parent":
        other.children = [first]
    if duplicate:
        root.children.append(node(4, "duplicate", first.name, first.element_info.control_type,
                                  (500, 80, 120, 40), root))
    if fault == "com_identity":
        root.children = [first, node(2, "conflict", "Find", "Button", first.box, root), other]
    elif fault == "new_parent":
        other.parent_node = first
    elif fault in {"parent", "process", "window", "root_parent"}:
        first.children = [root if fault == "root_parent" else first]

        def children(value):
            if value is first:
                if fault == "parent":
                    first.parent_node = other
                elif fault == "process":
                    first.element_info.process_id = first.CurrentProcessId = 99
                elif fault == "window":
                    first.top_handle = 99
                else:
                    root.parent_node = other
            return value.children

        monkeypatch.setattr(provider, "_finite_uia_children", children)
    walk = provider._bounded_uia_walk(root, budget=budget)
    snapshot.update(provider._walk_metadata(walk))
    snapshot["controls"] = [control(value.identifier, value.name, value.element_info.control_type,
        value.box, ancestors=() if value is root else ("root",),
        runtime_id=list(value.element_info.runtime_id)) for value in walk["wrappers"]]
    target = {"name": first.name, "control_type": first.element_info.control_type}
    return capture, snapshot, target


@pytest.mark.parametrize("edge", ["sibling", "self", "root", "cross_parent"])
def test_structured_target_uses_proven_alias_graph_without_rewriting_tree_fact(current_frame, monkeypatch, edge):
    capture, snapshot, target = graph_frame(current_frame, monkeypatch, edge=edge)
    original = deepcopy(snapshot)
    assert snapshot["scan_complete"] is True and snapshot["provider_tree_valid"] is False
    assert snapshot["alias_count"] == 1 and snapshot["traversal_errors"] == []
    result = resolve_current_uia_target(target, capture=capture, snapshot=snapshot)
    assert result["status"] == "matched" and result["control_id"] == "find"
    assert result["runtime_id"] == [2] and result["bbox"] == {"x": 40, "y": 80, "w": 120, "h": 40}
    assert snapshot == original


def test_named_edit_is_resolved_from_same_canonical_graph(current_frame, monkeypatch):
    capture, snapshot, target = graph_frame(current_frame, monkeypatch, edge="self", field=True)
    assert resolve_current_uia_target(target, capture=capture, snapshot=snapshot)["control_id"] == "find"


@pytest.mark.parametrize("fault", ["com_identity", "parent", "process", "window", "root_parent", "new_parent"])
def test_real_graph_identity_conflict_remains_incomplete(current_frame, monkeypatch, fault):
    capture, snapshot, target = graph_frame(current_frame, monkeypatch, fault=fault)
    assert snapshot["scan_complete"] is False and snapshot["traversal_errors"]
    with pytest.raises(ValueError, match="task_plan_target_uia_incomplete"):
        resolve_current_uia_target(target, capture=capture, snapshot=snapshot)


def test_alias_edges_exhausting_budget_cannot_become_exact_target(current_frame, monkeypatch):
    capture, snapshot, target = graph_frame(current_frame, monkeypatch, budget=3)
    assert snapshot["truncated"] is True
    with pytest.raises(ValueError, match="task_plan_target_uia_incomplete"):
        resolve_current_uia_target(target, capture=capture, snapshot=snapshot)


@pytest.mark.parametrize("changes", [
    {"scan_complete": False}, {"scan_complete": None}, {"truncated": True}, {"truncated": None},
    {"scan_scope": "browser_chrome"}, {"graph_scan_complete": False}, {"graph_scan_complete": None},
    {"provider_tree_valid": None}, {"provider_tree_valid": 1},
    {"alias_count": 0}, {"alias_count": True}, {"alias_count": "1"},
    {"cycle_count": -1}, {"cycle_count": 2}, {"cycle_count": True}, {"cycle_count": None},
    {"traversal_errors": None}, {"traversal_errors": ()},
    {"traversal_errors": [{"reason": "tree_runtime_id_conflict"}]},
    {"provider_tree_valid": True, "traversal_errors": [{"reason": "children_enumeration_failed"}]},
])
def test_unknown_or_bad_graph_metadata_is_rejected(current_frame, monkeypatch, changes):
    capture, snapshot, target = graph_frame(current_frame, monkeypatch)
    snapshot.update(changes)
    with pytest.raises(ValueError, match="task_plan_target_uia_incomplete"):
        resolve_current_uia_target(target, capture=capture, snapshot=snapshot)


def test_late_distinct_homonym_is_not_removed_as_an_alias(current_frame, monkeypatch):
    capture, snapshot, target = graph_frame(current_frame, monkeypatch, duplicate=True)
    result = resolve_current_uia_target(target, capture=capture, snapshot=snapshot)
    assert result["status"] == "ambiguous" and result["match_count"] == 2


@pytest.mark.parametrize("mutation,reason", [
    ("window", "window_mismatch"), ("hash", "capture_changed"),
    ("duplicate_runtime", "uia_identity_invalid"), ("ancestor", "uia_identity_invalid"),
    ("bbox", "geometry_invalid"), ("screen_bbox", "coordinate_mismatch"),
    ("readonly", "field_not_writable"),
])
def test_canonical_graph_does_not_bypass_remaining_target_checks(current_frame, monkeypatch, mutation, reason):
    capture, snapshot, target = graph_frame(current_frame, monkeypatch, field=True)
    selected = snapshot["controls"][1]
    if mutation == "window":
        snapshot["window"]["handle"] = 99
    elif mutation == "hash":
        capture["sha256"] = "0" * 64
    elif mutation == "duplicate_runtime":
        snapshot["controls"][2]["runtime_id"] = selected["runtime_id"][:]
    elif mutation == "ancestor":
        selected["ancestor_control_ids"] = ["missing"]
    elif mutation == "bbox":
        selected["bbox"]["w"] = 950
    elif mutation == "screen_bbox":
        selected["screen_bbox"]["x"] = 210
    else:
        selected["readonly"] = True
    with pytest.raises(ValueError, match="task_plan_target_" + reason):
        resolve_current_uia_target(target, capture=capture, snapshot=snapshot)


def test_existing_complete_tree_without_graph_metadata_remains_compatible(current_frame):
    capture, snapshot = current_frame
    result = resolve_current_uia_target({"name": "Find", "control_type": "Button"},
                                       capture=capture, snapshot=snapshot)
    assert result["status"] == "matched"


def test_readiness_sample_keeps_safe_graph_fact_for_final_generation(current_frame, monkeypatch, harness):
    from app.operation.screen_reading import browser_content_readiness as readiness
    _, canonical, _ = graph_frame(current_frame, monkeypatch, edge="self")
    value = readiness_snapshot(**{key: canonical[key] for key in ("scan_complete", "truncated",
        "provider_tree_valid", "graph_scan_complete", "alias_count", "cycle_count", "traversal_errors",
        "scan_visited_count")})
    source(monkeypatch, [value, value])
    with harness.scope():
        prepared = readiness.prepare_browser_content(harness.manager, "Click the Address input field")
        prepared.capture_snapshot({"image_path": "fresh.png", "window_size": {"width": 1000, "height": 690}})
    final = prepared.report["samples"][-1]
    assert final["stage"] == "after_fresh_capture"
    assert final["provider_tree_valid"] is False and final["graph_scan_complete"] is True
    assert final["truncated"] is False and final["alias_count"] == 1 and final["cycle_count"] == 1
    assert "controls" not in final and "traversal_errors" not in final
