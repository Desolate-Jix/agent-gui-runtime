"""非动作 UIA 上下文不能制造点击身份歧义；真实动作重叠仍须拒绝。"""

from copy import deepcopy

from PIL import Image
import pytest

from app.api import vision
from app.operation.recognition import control_target
from app.operation.screen_inventory.builder import build_screen_inventory


def _control(identifier, name, kind, bbox, patterns):
    return {"provider": "windows_uia", "control_id": identifier, "name": name,
            "control_type": kind, "bbox": dict(bbox), "screen_bbox": dict(bbox),
            "enabled": True, "visible": True, "patterns": list(patterns),
            "runtime_id": [42, 11, len(identifier)], "ancestor_control_ids": []}


def _rig(tmp_path, *, label="Atlas Search", context_name="Atlas", kind="Button",
         context_kind="Document", context_patterns=("Value", "Text", "Scroll"),
         context_flags=None, selected_flags=None, overlapping=False):
    image = tmp_path / "synthetic-current.png"
    Image.new("RGB", (600, 500), "white").save(image)
    selected = _control("selected", label, kind, {"x": 100, "y": 350, "w": 131, "h": 36},
                        ["Value", "Text"] if kind in {"Edit", "ComboBox"} else ["Invoke"])
    selected.update(selected_flags or {})
    other = _control("distant-namesake", label, kind,
        dict(selected["bbox"]) if overlapping else {"x": 100, "y": 100, "w": 131, "h": 36}, selected["patterns"])
    context = _control("context-root", context_name, context_kind,
                       {"x": 0, "y": 0, "w": 600, "h": 500}, context_patterns)
    context.update(context_flags or {})
    uia = {"provider": "windows_uia", "status": "ok", "scan_complete": True, "truncated": False,
           "controls": [context, other, selected], "control_count": 3}
    screen = {"contract_version": "screen_reading_v1", "image_path": str(image),
              "image_size": {"width": 600, "height": 500}, "texts": [], "ui_elements": [],
              "source_layers": {"windows_uia": uia}}
    inventory = build_screen_inventory(screen, goal=label)
    screen["screen_inventory"] = inventory
    candidates = vision.rank_candidates(vision.CandidateRankRequest(goal=label,
        page_structure=vision.PageStructure(image_size=vision.ImageSize(width=600, height=500),
            screen_summary="synthetic current capture", state_guess=None, elements=[], texts=[]),
        top_k=5, screen_reading=screen)).candidates
    fast = {"status": "ready", "screen_reading": screen, "screen_inventory": inventory}
    return fast, {"goal": label, "target_text": None, "point": {"x": 121, "y": 362},
                  "candidates": candidates}


@pytest.mark.parametrize("context_kind", ["Document", "Pane", "Group", "Image", "Text"])
@pytest.mark.parametrize("label,context_name", [("Atlas Search", "Atlas"), ("查看详情", "查看详情")])
def test_non_action_context_does_not_compete_with_current_point(tmp_path, context_kind, label, context_name):
    fast, arguments = _rig(tmp_path, label=label, context_name=context_name, context_kind=context_kind)
    original = deepcopy(fast)
    candidate, error = vision._vista_direct_current_uia_identity(fast_inventory=fast, **arguments)
    assert error is None and candidate is not None
    fact = candidate.element.evidence["current_uia_point_disambiguation"]
    assert fact["selected_control_id"] == "selected"
    assert fact["excluded_control_ids"] == ["distant-namesake"]
    assert fact["matching_control_count"] == 2
    assert fact["point"] == arguments["point"]
    assert fast == original


@pytest.mark.parametrize("kind", ["Button", "Hyperlink", "Edit", "ComboBox"])
def test_direct_action_types_remain_candidates_without_explicit_target(tmp_path, kind):
    fast, arguments = _rig(tmp_path, kind=kind)
    candidate, error = vision._vista_direct_current_uia_identity(fast_inventory=fast, **arguments)
    assert error is None and candidate.element.evidence["screen_inventory_action"]["source_id"] == "selected"


@pytest.mark.parametrize("kind,role", [("Button", "button"), ("Hyperlink", "link"), ("Edit", "input")])
def test_explicit_control_target_keeps_same_label_and_role_contract(tmp_path, kind, role):
    fast, arguments = _rig(tmp_path, kind=kind)
    target = {"contract_version": "recognition_control_target_v1", "label": arguments["goal"],
              "role": role, "source_binding_sha256": "a" * 64}
    candidate, error = vision._vista_direct_current_uia_identity(fast_inventory=fast, control_target=target, **arguments)
    assert error is None and candidate.role == role
    target["label"] = "Other target"
    assert vision._vista_direct_current_uia_identity(fast_inventory=fast, control_target=target, **arguments)[1] == "control_target_current_uia_missing"


@pytest.mark.parametrize("kind", ["Document", "Pane", "Group", "Image", "Text"])
@pytest.mark.parametrize("flags", [{}, {"enabled": False}, {"visible": None}])
def test_true_invoke_context_is_not_dropped_from_ambiguity(tmp_path, kind, flags):
    fast, arguments = _rig(tmp_path, context_kind=kind, context_patterns=["Invoke"], context_flags=flags)
    candidate, error = vision._vista_direct_current_uia_identity(fast_inventory=fast, **arguments)
    assert candidate is None and error == "vista_direct_current_uia_identity_ambiguous"


@pytest.mark.parametrize("flags", [{"enabled": False}, {"enabled": None}, {"visible": False}, {"visible": None}])
def test_selected_action_still_requires_positive_current_visibility(tmp_path, flags):
    fast, arguments = _rig(tmp_path, selected_flags=flags)
    candidate, error = vision._vista_direct_current_uia_identity(fast_inventory=fast, **arguments)
    assert candidate is None and error == "vista_direct_current_uia_visibility_unconfirmed"


@pytest.mark.parametrize("changed", ["overlap", "point", "truncated"])
def test_ambiguity_outside_point_and_incomplete_scan_remain_rejected(tmp_path, changed):
    fast, arguments = _rig(tmp_path, overlapping=changed == "overlap")
    if changed == "point":
        arguments["point"] = {"x": 500, "y": 450}
    elif changed == "truncated":
        fast["screen_reading"]["source_layers"]["windows_uia"].update(truncated=True, scan_complete=False)
    candidate, error = vision._vista_direct_current_uia_identity(fast_inventory=fast, **arguments)
    assert candidate is None
    assert error == ("vista_direct_current_uia_scan_incomplete" if changed == "truncated" else "vista_direct_current_uia_identity_ambiguous")


@pytest.mark.parametrize("kind", ["Button", "Hyperlink", "Edit", "ComboBox", "Combo Box", "TextBox",
    "CheckBox", "Check Box", "RadioButton", "Radio Button", "TabItem", "MenuItem", "ListItem", "TreeItem", "SplitButton"])
def test_action_identity_predicate_preserves_types_aliases_and_uncertain_flags(kind):
    assert control_target.uia_control_is_action_identity({"control_type": kind, "patterns": [],
                                                         "visible": None, "enabled": False})


@pytest.mark.parametrize("pattern", ["Invoke", "Selection", "ExpandCollapse", "Toggle"])
def test_real_action_patterns_keep_unknown_control_identity(pattern):
    assert control_target.uia_control_is_action_identity({"control_type": "Custom", "patterns": [pattern]})


@pytest.mark.parametrize("kind", ["Document", "Pane", "Group", "Image", "Text", "Custom"])
def test_read_patterns_alone_do_not_create_action_identity(kind):
    assert not control_target.uia_control_is_action_identity({"control_type": kind, "patterns": ["Value", "Text", "Scroll"]})


def _consumer_case():
    from tests.test_navigation_adaptive_jitter import _pair

    original, _, _, _ = _pair(offset=(0, 0))
    data = original.to_dict()
    context = _control("context-only", "Open details", "Document",
        {"x": 0, "y": 0, "w": 300, "h": 200}, ["Value", "Text", "Scroll"])
    data["uia_snapshot"]["controls"].insert(0, context)
    data["uia_snapshot"]["control_count"] += 1
    candidate = data["observation_evidence"]["recognition"]["result"]["candidate_result"]["candidates"][0]
    fact = candidate["element"]["evidence"]["current_uia_point_disambiguation"]
    return data, candidate, fact, dict(fact["point"])


def test_disambiguation_consumer_recomputes_against_full_tree_without_rewriting_it():
    from app.agent.fresh_learning_action_preview import _normalize_navigation_disambiguation

    data, candidate, fact, point = _consumer_case()
    original_tree = deepcopy(data["uia_snapshot"])
    _normalize_navigation_disambiguation(candidate, data, point, {"control_id": "details-control"}, direct=True)
    assert fact["point"] == "<verified-current-safe-point>"
    assert fact["screenshot_sha256"] == "<verified-current-capture-sha256>"
    assert data["uia_snapshot"] == original_tree
    assert fact["excluded_control_ids"] == ["distant-namesake"]


@pytest.mark.parametrize("changed", ["point", "hash", "count", "excluded", "extra_action", "duplicate_id", "source"])
def test_disambiguation_consumer_rejects_unproven_point_digest_or_original_tree(changed):
    from app.agent.fresh_learning_action_preview import _normalize_navigation_disambiguation

    data, candidate, fact, point = _consumer_case()
    if changed == "point": fact["point"] = {"x": 1, "y": 1}
    elif changed == "hash": fact["screenshot_sha256"] = "0" * 64
    elif changed == "count": fact["matching_control_count"] = 3
    elif changed == "excluded": fact["excluded_control_ids"] = []
    elif changed == "source": fact["source"] = "unverified-past-point"
    else:
        extra = deepcopy(data["uia_snapshot"]["controls"][-1])
        if changed == "extra_action": extra["control_id"] = "another-action"
        data["uia_snapshot"]["controls"].append(extra)
    with pytest.raises(ValueError, match="disambiguation"):
        _normalize_navigation_disambiguation(candidate, data, point, {"control_id": "details-control"}, direct=True)
