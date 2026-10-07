"""人工目标修订只使用已经归档并固定的完整学习截图。"""
from copy import deepcopy

import pytest

from app.learning_memory.target_recipe import load_target_recipe, save_target_recipe
from app.learning_memory.target_resolution import resolve_target_recipe
from app.learning_memory.workflow_target_editor_service import read_target_edit_context, propose_target_edit
from app.learning_memory.workspace import MemoryWorkspace
from test_learning_action_evidence import repeated_state
from test_learning_observation_source import observation_scene


class _FullControls(list):
    def append(self, item):
        if "control_id" not in item:
            item = {**item, "control_id": "other-action", "ancestor_control_ids": []}
        super().append(item)


def _draft(repeated_state):
    store, root, started, _, _ = repeated_state
    draft = store.control("learning_workflow", {"action": "compile", "learning_session_id": started["learning_id"]}, "compile")
    original = next(row for row in draft["proposed_target_recipes"] if row["event_id"] == "click-1")
    return root, original


def _edit(library, original, **kwargs):
    return propose_target_edit(library, original["reference"],
        {"kind": "click", "goal": "Other action"},
        [{"kind": "uia", "name": "Other action", "control_type": "Button"}],
        proposed_recipe=original["recipe"], **kwargs)


def test_edit_preserves_pinned_v2_and_reopens_new_target(repeated_state):
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        context = read_target_edit_context(library, original["reference"], proposed_recipe=original["recipe"])
        assert context["recipe"] == original["recipe"]
        assert any(control["name"] == "Other action" for control in context["controls"])
        assert context["uia"]["snapshot"]["controls"] == context["controls"]
        result = _edit(library, original)
        recipe = result["recipe"]
        assert recipe["contract_version"] == "target_recipe.v3"
        assert recipe["editorial"] == {"kind": "human_edit", "validation": "unverified",
                                       "context_recipe": original["recipe"]}
        assert recipe["scope"] == original["recipe"]["scope"]
        assert recipe["evidence_refs"] == original["recipe"]["evidence_refs"]
        assert result["validation"] == "unverified"
        assert result["preview_scope"] == "learning_capture"
        assert result["preview"]["status"] == "matched"
        assert result["preview"]["candidate"]["bbox"] == {"x": 100, "y": 25, "w": 40, "h": 20}
        assert result["preview"]["candidate"]["freshness"] != "current_capture"
        assert not (root / "desktop-review" / "target-recipes" / (recipe["recipe_id"] + ".json")).exists()
        save_target_recipe(library, original["recipe"])
        save_target_recipe(library, recipe)
        assert load_target_recipe(library, original["reference"]) == original["recipe"]
        assert load_target_recipe(library, result["reference"]) == recipe


def test_second_edit_embeds_only_original_v2(repeated_state):
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        first = _edit(library, original)
        second = propose_target_edit(library, first["reference"],
            {"kind": "click", "goal": "Refresh again"},
            [{"kind": "uia", "name": "Refresh", "control_type": "Button"}],
            proposed_recipe=first["recipe"])
        assert second["recipe"]["editorial"]["context_recipe"] == original["recipe"]
        assert second["recipe"]["editorial"]["context_recipe"]["contract_version"] == "target_recipe.v2"


@pytest.mark.parametrize("change", ["source", "scope", "anchor", "control"])
def test_rehashed_forgery_is_rejected(repeated_state, change):
    from app.desktop_review.external_mapping import canonical_json_bytes
    from hashlib import sha256
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        recipe = deepcopy(_edit(library, original)["recipe"])
        if change == "source":
            recipe["editorial"]["context_recipe"]["evidence_refs"][1]["bundle_sha256"] = "0" * 64
        elif change == "scope":
            recipe["scope"]["state_key"] = "other"
        elif change == "anchor":
            recipe["scope"]["anchors"] = []
        else:
            recipe["strategies"][0]["name"] = "Unknown control"
        recipe["recipe_id"] = "target-recipe-" + sha256(canonical_json_bytes({k: v for k, v in recipe.items() if k != "recipe_id"})).hexdigest()
        with pytest.raises(ValueError):
            save_target_recipe(library, recipe)


def test_missing_row_input_stays_unknown_and_preview_does_not_write(repeated_state):
    root, original = _draft(repeated_state)
    rule = {"kind": "visible_row", "container": {"name": "Results", "control_type": "List"},
            "row": {"control_type": "ListItem"},
            "properties": [{"property": "title", "control_type": "Text", "read": "name"}],
            "constraints": [{"property": "title", "operator": "eq",
                             "value": {"source": "input", "name": "wanted"}}],
            "action": {"name": "Open", "control_type": "Button"}}
    with MemoryWorkspace(root) as library:
        before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file() and path.suffix != ".lock"}
        with pytest.raises(ValueError):
            propose_target_edit(library, original["reference"], {"kind": "click", "goal": "Open"},
                                [rule], proposed_recipe=original["recipe"])
        after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file() and path.suffix != ".lock"}
        assert after == before


def test_preview_outputs_require_same_preview_run(repeated_state):
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="target_edit_preview_bindings_invalid"):
            _edit(library, original, preview_outputs={"step.value": {"run_id": "earlier", "value": "x"}})


def test_input_sequence_rejects_button_target(repeated_state):
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="target_edit_action_control_type_mismatch"):
            propose_target_edit(library, original["reference"],
                {"kind": "input_sequence", "field_goal": "Other action", "submit_search": False},
                [{"kind": "uia", "name": "Other action", "control_type": "Button"}],
                proposed_recipe=original["recipe"])


def test_click_accepts_tab_item_in_full_observation(tmp_path):
    scene = observation_scene.__wrapped__(tmp_path)
    scene[2]["uia"]["snapshot"]["controls"].append({"name": "Settings", "control_type": "TabItem",
        "runtime_id": [10], "visible": True, "enabled": True,
        "bbox": {"x": 85, "y": 50, "w": 50, "h": 20}})
    root, original = _draft(repeated_state.__wrapped__(scene))
    with MemoryWorkspace(root) as library:
        result = propose_target_edit(library, original["reference"],
            {"kind": "click", "goal": "Settings"},
            [{"kind": "uia", "name": "Settings", "control_type": "TabItem"}],
            proposed_recipe=original["recipe"])
        assert result["preview"]["status"] == "matched"


def row_state(tmp_path, *, compound=False, unnamed_dynamic=False):
    """生成可复用的真实完整行树与已归档动作来源。"""
    scene = observation_scene.__wrapped__(tmp_path)
    observation = scene[2]
    snapshot = observation["uia"]["snapshot"]
    snapshot.update(provider="windows_uia", provider_tree_valid=True)
    for index, control in enumerate(snapshot["controls"]):
        control.update(control_id=f"existing-{index}", ancestor_control_ids=[])
    snapshot["controls"].extend([
        {"control_id": "list", "ancestor_control_ids": [], "name": "Results", "control_type": "List",
         "bbox": {"x": 80, "y": 20, "w": 75, "h": 75}, "visible": True, "enabled": True},
        {"control_id": "row", "ancestor_control_ids": ["list"], "name": "", "control_type": "ListItem",
         "bbox": {"x": 82, "y": 25, "w": 70, "h": 45}, "visible": True, "enabled": True},
        {"control_id": "title", "ancestor_control_ids": ["list", "row"], "name": "Alpha", "control_type": "Text",
         "bbox": {"x": 85, "y": 28, "w": 30, "h": 10}, "visible": True, "enabled": True},
        {"control_id": "open", "ancestor_control_ids": ["list", "row"], "name": "Open", "control_type": "Button",
         "bbox": {"x": 120, "y": 50, "w": 30, "h": 20}, "visible": True, "enabled": True},
    ])
    if compound:
        next(row for row in snapshot["controls"] if row.get("control_id") == "title")["automation_id"] = "titleId"
        snapshot["controls"].extend([
            {"control_id": "number-a", "ancestor_control_ids": ["list", "row"],
             "name": "A-1", "control_type": "Text", "automation_id": "numberId",
             "bbox": {"x": 87, "y": 40, "w": 28, "h": 8}, "visible": True, "enabled": True},
            {"control_id": "row-b", "ancestor_control_ids": ["list"], "name": "", "control_type": "ListItem",
             "bbox": {"x": 82, "y": 72, "w": 70, "h": 20}, "visible": True, "enabled": True},
            {"control_id": "title-b", "ancestor_control_ids": ["list", "row-b"],
             "name": "Alpha", "control_type": "Text", "automation_id": "titleId",
             "bbox": {"x": 85, "y": 73, "w": 30, "h": 8}, "visible": True, "enabled": True},
            {"control_id": "number-b", "ancestor_control_ids": ["list", "row-b"],
             "name": "B-2", "control_type": "Text", "automation_id": "numberId",
             "bbox": {"x": 87, "y": 82, "w": 28, "h": 8}, "visible": True, "enabled": True},
            {"control_id": "open-b", "ancestor_control_ids": ["list", "row-b"],
             "name": "Open", "control_type": "Button", "bbox": {"x": 120, "y": 75, "w": 30, "h": 14},
             "visible": True, "enabled": True},
        ])
    if unnamed_dynamic:
        assert not compound
        container = next(row for row in snapshot["controls"] if row.get("control_id") == "list")
        container.update(name=None, automation_id="results")
        for cid, aid in [("title", "row-a.recordLabel"), ("open", "row-a.openDetail")]:
            next(row for row in snapshot["controls"] if row.get("control_id") == cid)["automation_id"] = aid
        snapshot["controls"].extend([
            {"control_id": "row-b", "ancestor_control_ids": ["list"], "name": "", "control_type": "ListItem",
             "bbox": {"x": 82, "y": 72, "w": 70, "h": 20}, "visible": True, "enabled": True},
            {"control_id": "title-b", "ancestor_control_ids": ["list", "row-b"], "name": "Beta", "control_type": "Text",
             "automation_id": "row-b.recordLabel", "bbox": {"x": 85, "y": 73, "w": 30, "h": 15}, "visible": True, "enabled": True},
            {"control_id": "open-b", "ancestor_control_ids": ["list", "row-b"], "name": "Open", "control_type": "Button",
             "automation_id": "row-b.openDetail", "bbox": {"x": 120, "y": 75, "w": 30, "h": 14}, "visible": True, "enabled": True},
        ])
    snapshot["controls"] = _FullControls(snapshot["controls"])
    return repeated_state.__wrapped__(scene)


def test_visible_row_preview_and_later_position_use_same_semantic_rule(tmp_path):
    state = row_state(tmp_path)
    root, original = _draft(state)
    rule = {"kind": "visible_row", "container": {"name": "Results", "control_type": "List"},
            "row": {"control_type": "ListItem"},
            "properties": [{"property": "title", "control_type": "Text", "read": "name"}],
            "constraints": [{"property": "title", "operator": "eq",
                             "value": {"source": "input", "name": "wanted"}}],
            "action": {"name": "Open", "control_type": "Button"}}
    action = {"kind": "click", "goal": "Open"}
    with MemoryWorkspace(root) as library:
        missing = propose_target_edit(library, original["reference"], action, [rule],
                                      proposed_recipe=original["recipe"])
        assert (missing["preview"]["status"], missing["preview"]["reason"]) == ("invalid", "missing_input")
        edited = propose_target_edit(library, original["reference"], action, [rule],
                                     proposed_recipe=original["recipe"], preview_inputs={"wanted": "Alpha"})
        assert edited["preview"]["candidate"]["bbox"] == {"x": 120, "y": 50, "w": 30, "h": 20}
        save_target_recipe(library, edited["recipe"])
        current = deepcopy(state[4][1])
        current["frame"]["capture_id"] = "later"
        current["uia"]["capture_id"] = "later"
        current["uia"]["snapshot"]["capture_id"] = "later"
        controls = current["uia"]["snapshot"]["controls"]
        for control in controls:
            if control.get("control_id") in {"row", "title", "open"}:
                control["bbox"]["y"] += 20
        result = resolve_target_recipe(library, edited["reference"], frame=current["frame"],
            observations={"uia": current["uia"]},
            bindings={"action": action, "run_id": "later", "inputs": {"wanted": "Alpha"}, "outputs": {}})
        assert result["status"] == "matched"
        assert result["candidate"]["bbox"] == {"x": 120, "y": 70, "w": 30, "h": 20}


def test_two_row_conditions_distinguish_same_title_by_number(tmp_path):
    state = row_state(tmp_path, compound=True)
    root, original = _draft(state)
    rule = {"kind": "visible_row", "container": {"name": "Results", "control_type": "List"},
        "row": {"control_type": "ListItem"},
        "properties": [
            {"property": "title", "control_type": "Text", "automation_id": "titleId", "read": "name"},
            {"property": "number", "control_type": "Text", "automation_id": "numberId", "read": "name"}],
        "constraints": [
            {"property": "title", "operator": "eq", "value": {"source": "input", "name": "wanted_title"}},
            {"property": "number", "operator": "eq", "value": {"source": "input", "name": "wanted_number"}}],
        "action": {"name": "Open", "control_type": "Button"}}
    with MemoryWorkspace(root) as library:
        result = propose_target_edit(library, original["reference"], {"kind": "click", "goal": "Open"},
            [rule], proposed_recipe=original["recipe"],
            preview_inputs={"wanted_title": "Alpha", "wanted_number": "B-2"})
        assert result["preview"]["status"] == "matched"
        assert result["preview"]["candidate"]["bbox"] == {"x": 120, "y": 75, "w": 30, "h": 14}
        assert result["recipe"]["strategies"][0]["constraints"] == rule["constraints"]


def test_strategy_order_is_new_immutable_version(repeated_state):
    root, original = _draft(repeated_state)
    first_rule = {"kind": "uia", "name": "Other action", "control_type": "Button"}
    second_rule = {"kind": "uia", "name": "Refresh", "control_type": "Button"}
    action = {"kind": "click", "goal": "Choose action"}
    with MemoryWorkspace(root) as library:
        first = propose_target_edit(library, original["reference"], action,
            [first_rule, second_rule], proposed_recipe=original["recipe"])
        save_target_recipe(library, first["recipe"])
        reordered = propose_target_edit(library, first["reference"], action,
            [second_rule, first_rule], proposed_recipe=first["recipe"])
        save_target_recipe(library, reordered["recipe"])
        assert first["recipe"]["recipe_id"] != reordered["recipe"]["recipe_id"]
        assert load_target_recipe(library, first["reference"])["strategies"] == [first_rule, second_rule]
        assert load_target_recipe(library, reordered["reference"])["strategies"] == [second_rule, first_rule]
        assert first["preview"]["candidate"]["bbox"] != reordered["preview"]["candidate"]["bbox"]


def test_second_strategy_must_match_action_kind(repeated_state):
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="target_edit_action_control_type_mismatch"):
            propose_target_edit(library, original["reference"],
                {"kind": "input_sequence", "field_goal": "Search", "submit_search": False},
                [{"kind": "uia", "name": "Search", "control_type": "Edit"},
                 {"kind": "uia", "name": "Other action", "control_type": "Button"}],
                proposed_recipe=original["recipe"])
