"""人工修订固定目标，并在学习截图上只读预览。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from app.desktop_review.external_mapping import canonical_json_bytes

from .action_evidence import load_action_evidence
from .target_recipe import (_check_evidence, _validate_recipe, action_semantics_sha256,
                            load_target_recipe, validate_target_reference, validate_editorial_action)
from .target_recipe_proposal import _TARGET_TYPES
from .target_resolution import (_matches_control, _resolve_loaded_recipe, _uia_snapshot)
from .uia_rows import _bound_snapshot, _inside, _matches, _row_action_matches, validate_visible_row_strategy
from .target_box_projection import project_target_boxes, select_box_control, box_list, row_members


def _source_recipe(library, reference, proposed_recipe):
    ref = validate_target_reference(reference)
    recipe = (load_target_recipe(library, ref) if proposed_recipe is None
              else _validate_recipe(proposed_recipe))
    if (recipe["recipe_id"] != ref["recipe_id"]
            or (recipe["scope"]["interface_key"], recipe["scope"]["state_key"]) !=
               (ref["interface_key"], ref["state_key"])):
        raise ValueError("target_recipe_reference_mismatch")
    _check_evidence(library, recipe)
    if recipe["contract_version"] == "target_recipe.v1":
        raise ValueError("target_edit_action_observation_unsupported")
    return recipe


def _observation(library, recipe):
    return load_action_evidence(library, recipe["evidence_refs"][1])["observation"]


def read_target_edit_context(library, reference, *, proposed_recipe=None):
    recipe = _source_recipe(library, reference, proposed_recipe)
    observation = _observation(library, recipe)
    frame = observation["frame"]
    snapshot, error = _uia_snapshot({"uia": observation["uia"]}, frame)
    if error:
        raise ValueError("target_edit_" + error)
    boxes, issues = project_target_boxes(recipe, observation)
    return {"recipe": deepcopy(recipe), "frame": deepcopy(frame),
            "controls": deepcopy(snapshot["controls"]), "uia": deepcopy(observation["uia"]),
            "target_boxes": boxes, "box_issues": issues}


def _validate_uia_target(strategy, snapshot, frame, anchors):
    matches = [control for control in snapshot["controls"] if _matches_control(control, strategy)]
    if len(matches) != 1:
        raise ValueError("target_edit_control_ambiguous" if matches else "target_edit_control_missing")
    control = matches[0]
    viewport = {"x": 0, "y": 0, "w": frame["image_size"]["width"], "h": frame["image_size"]["height"]}
    if not _inside(control.get("bbox"), viewport):
        raise ValueError("target_edit_control_geometry_invalid")
    if any(_matches_control(control, anchor) or
           any(_matches_control(row, anchor) and row.get("bbox") == control["bbox"]
               for row in snapshot["controls"])
           for anchor in anchors if anchor["kind"] == "uia"):
        raise ValueError("target_edit_anchor_is_target")
    if strategy["control_type"] not in (_TARGET_TYPES["click"] | _TARGET_TYPES["input_sequence"] |
                                       {"ListItem", "DataItem"}):
        raise ValueError("target_edit_control_not_executable")


def _validate_row_target(strategy, snapshot, frame, anchors):
    validate_visible_row_strategy(strategy)
    capture = {key: deepcopy(frame[key]) for key in ("capture_id", "window_identity", "image_size", "sha256")}
    controls, viewport = _bound_snapshot(snapshot, capture)
    containers = [row for row in controls if _matches(row, strategy["container"])]
    if len(containers) != 1:
        raise ValueError("target_edit_container_ambiguous" if containers else "target_edit_container_missing")
    container = containers[0]
    if not _inside(container.get("bbox"), viewport):
        raise ValueError("target_edit_container_geometry_invalid")
    rows = [row for row in controls if container["control_id"] in row["ancestor_control_ids"]
            and _matches(row, strategy["row"])]
    if not rows:
        raise ValueError("target_edit_row_missing")
    row_ids = {row["control_id"] for row in rows}
    for row in rows:
        if row_ids.intersection(row["ancestor_control_ids"]):
            raise ValueError("uia_multiple_row_ancestors")
        if not _inside(row.get("bbox"), container["bbox"]):
            raise ValueError("target_edit_row_geometry_invalid")
        descendants = [item for item in controls if row["control_id"] in item["ancestor_control_ids"]
                       and container["control_id"] in item["ancestor_control_ids"]]
        if any(len(row_ids.intersection(item["ancestor_control_ids"])) != 1 for item in descendants):
            raise ValueError("uia_multiple_row_ancestors")
        for spec in strategy["properties"]:
            matches = [item for item in ([row] if spec.get("source") == "row" else descendants) if _matches(item, spec)
                       and _inside(item.get("bbox"), row["bbox"]) and isinstance(item.get("name"), str)
                       and item["name"].strip()]
            if len(matches) != 1:
                raise ValueError("target_edit_property_ambiguous" if matches else "target_edit_property_missing")
        actions = [item for item in ([row] if strategy["action"].get("source") == "row" else descendants) if _row_action_matches(item, strategy["action"], row)
                   and _inside(item.get("bbox"), row["bbox"])]
        if len(actions) != 1:
            raise ValueError("target_edit_row_action_ambiguous" if actions else "target_edit_row_action_missing")
        if any(_matches_control(actions[0], anchor) or
               any(_matches_control(item, anchor) and item.get("bbox") == actions[0]["bbox"]
                   for item in controls)
               for anchor in anchors if anchor["kind"] == "uia"):
            raise ValueError("target_edit_anchor_is_target")


def validate_editorial_target(recipe, observation):
    """独立验证人工规则在原始完整树中真实存在，不证明原动作点击了新目标。"""
    strategies = recipe["strategies"]
    if not 1 <= len(strategies) <= 8 or any(row["kind"] not in {"uia", "visible_row"} for row in strategies):
        raise ValueError("target_edit_single_strategy_required")
    frame = observation["frame"]
    snapshot, error = _uia_snapshot({"uia": observation["uia"]}, frame)
    if error:
        raise ValueError("target_edit_" + error)
    anchors = recipe["scope"].get("anchors", [])
    for strategy in strategies:
        if strategy["kind"] == "uia":
            _validate_uia_target(strategy, snapshot, frame, anchors)
        else:
            _validate_row_target(strategy, snapshot, frame, anchors)


def propose_target_edit(library, reference, action, strategies, *, proposed_recipe=None,
                        preview_inputs=None, preview_outputs=None):
    recipe = _source_recipe(library, reference, proposed_recipe)
    original = recipe["editorial"]["context_recipe"] if recipe["contract_version"] == "target_recipe.v3" else recipe
    body = {key: deepcopy(original[key]) for key in ("interface_id", "interface_version_id", "scope", "evidence_refs")}
    body.update(contract_version="target_recipe.v3", strategies=deepcopy(strategies),
                editorial={"kind": "human_edit", "validation": "unverified", "context_recipe": deepcopy(original)})
    body["action_semantics_sha256"] = action_semantics_sha256(action, scope=body["scope"],
                                                              strategies=body["strategies"])
    validate_editorial_action(body, action)
    revised = {**body, "recipe_id": "target-recipe-" + sha256(canonical_json_bytes(body)).hexdigest()}
    _validate_recipe(revised)
    _check_evidence(library, revised)
    frame = _observation(library, revised)["frame"]
    ref = {"recipe_id": revised["recipe_id"], "interface_key": revised["scope"]["interface_key"],
           "state_key": revised["scope"]["state_key"]}
    inputs = {} if preview_inputs is None else deepcopy(preview_inputs)
    outputs = {} if preview_outputs is None else deepcopy(preview_outputs)
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        raise ValueError("target_edit_preview_bindings_invalid")
    if any(not isinstance(key, str) or not key or not isinstance(value, dict)
           or set(value) != {"run_id", "value"} or value["run_id"] != "target-edit-preview"
           or type(value["value"]) not in (str, int, float, bool)
           for key, value in outputs.items()):
        raise ValueError("target_edit_preview_bindings_invalid")
    bindings = {"action": action, "run_id": "target-edit-preview", "inputs": inputs, "outputs": outputs}
    observation = _observation(library, revised)
    preview = _resolve_loaded_recipe(library, ref, revised, frame=frame,
                                     observations={"uia": observation["uia"]}, bindings=bindings)
    if preview["candidate"] is not None:
        preview["candidate"]["freshness"] = "learning_capture"
    return {"recipe": revised, "reference": ref, "preview": preview,
            "preview_scope": "learning_capture", "validation": "unverified"}


def propose_target_box_edit(library, reference, action, strategies, strategy_index, bbox, *,
                            proposed_recipe=None, preview_inputs=None, preview_outputs=None):
    """框只选择原帧内的控件；实际保存与执行仍使用控件规则。"""
    context = read_target_edit_context(library, reference, proposed_recipe=proposed_recipe)
    if (not isinstance(strategies, list) or type(strategy_index) is not int
            or not 0 <= strategy_index < len(strategies)):
        raise ValueError('target_box_strategy_index_invalid')
    revised = deepcopy(strategies)
    strategy = revised[strategy_index]
    row_strategy = None
    if strategy.get('kind') == 'visible_row' and strategy.get('action', {}).get('source') == 'row_name':
        validate_visible_row_strategy(strategy)
        row_strategy = strategy
    control = select_box_control(context['controls'], context['frame'], action, bbox, row_strategy=row_strategy)
    if strategy.get('kind') == 'uia':
        selector = {'kind': 'uia', 'name': control.get('name'), 'control_type': control['control_type']}
        if control.get('automation_id'):
            selector['automation_id'] = control['automation_id']
        revised[strategy_index] = selector
    elif strategy.get('kind') == 'visible_row':
        validate_visible_row_strategy(strategy)
        members = [(row, c) for row, c in row_members(context['controls'], strategy, context['frame'])
                   if c == control]
        if len(members) != 1:
            raise ValueError('target_box_row_control_not_unique')
        selector = {'control_type': control['control_type']}
        if strategy['action'].get('source') in {'row', 'row_name'}:
            selector['source'] = strategy['action']['source']
        if 'name' in strategy['action']:
            selector['name'] = control.get('name')
        if 'automation_id' in strategy['action']:
            selector['automation_id'] = control.get('automation_id')
        strategy['action'] = selector
    else:
        raise ValueError('target_box_strategy_unsupported')
    result = propose_target_edit(library, reference, action, revised, proposed_recipe=proposed_recipe,
                                preview_inputs=preview_inputs, preview_outputs=preview_outputs)
    if result['preview']['status'] != 'matched':
        raise ValueError('target_box_preview_not_matched')
    result['selected_control_bbox'] = box_list(control['bbox'])
    return result


__all__ = ["read_target_edit_context", "propose_target_edit", "propose_target_box_edit"]
