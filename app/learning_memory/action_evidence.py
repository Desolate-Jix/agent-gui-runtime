"""从不可变学习图来源核验单个动作，不移动代表界面的版本引用。"""
from copy import deepcopy
import re


_PATTERNS = {
    "project_id": r"[a-z0-9][a-z0-9_-]{0,79}",
    "session_id": r"[a-z0-9][a-z0-9_-]{0,79}",
    "learning_id": r"learning-[0-9a-f]{32}",
    "event_id": r"[a-z0-9][a-z0-9_-]{0,79}",
    "source_node_id": r"state-[0-9a-f]{32}",
    "bundle_sha256": r"[0-9a-f]{64}",
    "observation_sha256": r"[0-9a-f]{64}",
}


def validate_action_evidence_reference(value):
    if (not isinstance(value, dict) or set(value) != {"kind", *_PATTERNS}
            or value.get("kind") != "learning_action"
            or any(not isinstance(value.get(key), str) or re.fullmatch(pattern, value[key]) is None
                   for key, pattern in _PATTERNS.items())):
        raise ValueError("target_recipe_action_evidence_invalid")
    return deepcopy(value)


def load_action_evidence(library, reference):
    from app.desktop_review.workspace import DesktopReviewError
    from .graph_source import read_source, bundle_segments
    from .learning_observation_source import load_learning_observation, validate_learning_observation
    from .projector import project_segment

    ref = validate_action_evidence_reference(reference)
    source = {"kind": "execution_memory", "task_id": "memory-local", "project_id": ref["project_id"],
              "bundle_sha256": ref["bundle_sha256"], "interface_composition": []}
    try:
        bundle = read_source(library, source)
    except (OSError, ValueError, DesktopReviewError) as error:
        raise ValueError("target_recipe_action_source_invalid") from error
    segments = [row for row in bundle_segments(bundle)
                if (row["manifest"]["session_id"], row["manifest"]["learning_id"]) ==
                   (ref["session_id"], ref["learning_id"])]
    if len(segments) != 1:
        raise ValueError("target_recipe_action_segment_missing")
    segment = segments[0]
    events = [row for row in segment["events"] if row["request_id"] == ref["event_id"]]
    if len(events) != 1:
        raise ValueError("target_recipe_action_event_missing")
    event = events[0]
    terminal = event.get("terminal_receipt")
    if (event.get("status") != "returned" or event.get("action_executed") is not True
            or terminal is not None and (not isinstance(terminal, dict) or terminal.get("status") != "completed")):
        raise ValueError("target_recipe_action_not_completed")
    projection = project_segment(segment["manifest"], segment["events"], segment["reviews"])
    edges = [edge for edge in projection["edges"] if edge["evidence"]["event_id"] == ref["event_id"]]
    if len(edges) != 1 or edges[0]["source_node_id"] != ref["source_node_id"]:
        raise ValueError("target_recipe_action_state_mismatch")
    if ref["source_node_id"] in bundle.get("excluded_states", []):
        raise ValueError("target_recipe_action_state_excluded")
    pin = bundle.get("pins", {}).get(ref["source_node_id"])
    if not isinstance(pin, dict) or set(pin) != {"interface_id", "version_id", "content_sha256"}:
        raise ValueError("target_recipe_action_pin_invalid")
    observation_ref = {"kind": "learning_target_observation", "sha256": ref["observation_sha256"]}
    if (segment.get("target_observations", {}).get(ref["event_id"]) != observation_ref
            or event.get("target_observation") != observation_ref):
        raise ValueError("target_recipe_action_observation_mismatch")
    observation = validate_learning_observation(event, load_learning_observation(library, observation_ref))
    return {"event": deepcopy(event), "review": deepcopy(segment["reviews"][ref["event_id"]]["review"]),
            "pin": deepcopy(pin), "observation": observation}


def validate_captured_rule(recipe, source):
    from .target_recipe import action_semantics_sha256
    from .target_recipe_proposal import (_TARGET_TYPES, _bbox, _locator, _matches, _overlap,
                                         _point, _stable_anchor_name, _native_row_proposal)

    event, observation = source["event"], source["observation"]
    hints = event.get("action_hints") or {}
    if event["kind"] == "step" and event.get("operation") == "execute_recognition_plan":
        action = {"kind": "click", "goal": hints.get("goal"), "click_kind": hints.get("click_kind", "single")}
        if action["click_kind"] != "single":
            raise ValueError("target_recipe_captured_action_unsupported")
    elif event["kind"] == "input_sequence":
        action = {"kind": "input_sequence", "field_goal": hints.get("field_goal"),
                  "submit_search": hints.get("submit_search")}
    else:
        raise ValueError("target_recipe_captured_action_unsupported")
    if action_semantics_sha256(action, scope=recipe["scope"], strategies=recipe["strategies"]) != recipe["action_semantics_sha256"]:
        raise ValueError("target_recipe_captured_action_changed")
    candidate = observation["candidate"]
    size = observation["frame"]["image_size"]
    controls = observation["uia"]["snapshot"]["controls"]
    targets = [row for row in controls if isinstance(row, dict)
               and row.get("visible") is True and row.get("enabled") is True
               and row.get("control_type") in _TARGET_TYPES[action["kind"]]
               and _bbox(row.get("bbox"), size) and _overlap(row["bbox"], candidate["bbox"])
               and _point(candidate["click_point"], row["bbox"])
               and isinstance(row.get("name"), str) and row["name"].strip()]
    native = None
    if not targets and action["kind"] == "click":
        native = _native_row_proposal(observation["uia"]["snapshot"], observation["frame"], candidate)
    if native is not None:
        if recipe["strategies"] != [native[1]]:
            raise ValueError("target_recipe_captured_target_changed")
        target = native[0]
    else:
        if (len(targets) != 1 or recipe["strategies"] != [_locator(targets[0])]
                or sum(_matches(row, recipe["strategies"][0]) for row in controls if isinstance(row, dict)) != 1):
            raise ValueError("target_recipe_captured_target_changed")
        target = targets[0]
    anchors = recipe["scope"].get("anchors", [])
    if len(anchors) != 1 or anchors[0]["kind"] != "uia":
        raise ValueError("target_recipe_captured_anchor_changed")
    matched = [row for row in controls if isinstance(row, dict) and _matches(row, anchors[0])]
    # 自动提议只能证明实际目标和独立锚点；人工换目标须另建编辑来源。
    if (len(matched) != 1 or matched[0].get("control_type") not in ({"Text", "HeaderItem"} if native else {"Text"})
            or anchors[0] != _locator(matched[0]) or not _bbox(matched[0].get("bbox"), size)
            or _overlap(matched[0]["bbox"], candidate["bbox"])
            or _overlap(matched[0]["bbox"], target["bbox"])
            or not _stable_anchor_name(matched[0].get("name"), {})):
        raise ValueError("target_recipe_captured_anchor_changed")


__all__ = ["validate_action_evidence_reference", "load_action_evidence", "validate_captured_rule"]
