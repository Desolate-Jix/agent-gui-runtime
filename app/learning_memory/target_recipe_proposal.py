"""从同一次学习前观察提议固定 UIA 目标规则；结果仍需人工审核。"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
from math import isfinite
from pathlib import Path
import re

from PIL import Image

from app.desktop_review.external_mapping import canonical_json_bytes
from .target_recipe import action_semantics_sha256, _validate_recipe


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_TYPES = {"click": {"Button", "Hyperlink", "MenuItem", "CheckBox", "RadioButton", "TabItem"},
                 "input_sequence": {"Edit", "ComboBox"}}


def _unresolved(reason):
    return {"recipe": None, "unresolved_items": [{"reason": reason}], "evidence_refs": []}


def _bbox(value, size):
    return (isinstance(value, dict) and set(value) == {"x", "y", "w", "h"}
            and all(type(value[key]) is int for key in value)
            and 0 <= value["x"] < value["x"] + value["w"] <= size["width"]
            and 0 <= value["y"] < value["y"] + value["h"] <= size["height"])


def _point(point, bbox):
    return (isinstance(point, dict) and set(point) == {"x", "y"}
            and all(type(point[key]) is int for key in point)
            and bbox["x"] <= point["x"] < bbox["x"] + bbox["w"]
            and bbox["y"] <= point["y"] < bbox["y"] + bbox["h"])


def _overlap(left, right):
    return (left["x"] < right["x"] + right["w"] and right["x"] < left["x"] + left["w"]
            and left["y"] < right["y"] + right["h"] and right["y"] < left["y"] + left["h"])


def _locator(control):
    value = {"kind": "uia", "name": control["name"], "control_type": control["control_type"]}
    automation_id = control.get("automation_id")
    if isinstance(automation_id, str) and automation_id.strip():
        value["automation_id"] = automation_id
    return value


def _matches(control, locator):
    return (control.get("visible") is True and control.get("enabled") is True
            and control.get("name") == locator["name"]
            and control.get("control_type") == locator["control_type"]
            and ("automation_id" not in locator or control.get("automation_id") == locator["automation_id"]))


def _stable_anchor_name(name, inputs):
    if not isinstance(name, str) or not name.strip() or len(name) > 2000:
        return False
    # 数字、时间和本次输入值不应固化为页面身份。
    if any(char.isdigit() for char in name) or re.search(r"\d{1,2}:\d{2}", name):
        return False
    return not any(isinstance(value, str) and value and value in name for value in inputs.values())


def _frame(observation, event):
    frame = observation.get("frame")
    if not isinstance(frame, dict):
        return None
    if (observation.get("event_id") != event.get("request_id")
            or observation.get("command_sha256") != event.get("command_sha256")):
        raise ValueError("target_proposal_command_binding_mismatch")
    if observation.get("observation_stage") != "before":
        return None
    before = event.get("before") or {}
    if frame.get("capture_id") != before.get("capture_id") or frame.get("sha256") != before.get("sha256"):
        raise ValueError("target_proposal_before_frame_mismatch")
    identity = frame.get("window_identity")
    if (not isinstance(identity, dict) or set(identity) != {"handle", "process_id", "process_create_time"}
            or type(identity["handle"]) is not int or identity["handle"] <= 0
            or type(identity["process_id"]) is not int or identity["process_id"] <= 0
            or type(identity["process_create_time"]) not in (float, int)
            or not isfinite(identity["process_create_time"]) or identity["process_create_time"] <= 0):
        raise ValueError("target_proposal_window_identity_invalid")
    size = frame.get("image_size")
    if (not isinstance(size, dict) or set(size) != {"width", "height"}
            or any(type(size[key]) is not int or size[key] <= 0 for key in size)):
        raise ValueError("target_proposal_image_size_invalid")
    rect = frame.get("window_rect")
    if (not isinstance(rect, list) or len(rect) != 4 or any(type(x) is not int for x in rect)
            or rect[2] - rect[0] != size["width"] or rect[3] - rect[1] != size["height"]):
        raise ValueError("target_proposal_window_rect_invalid")
    digest, image_path = frame.get("sha256"), frame.get("image_path")
    if not isinstance(digest, str) or not _SHA.fullmatch(digest) or not isinstance(image_path, str) or not image_path:
        raise ValueError("target_proposal_image_invalid")
    try:
        raw = Path(image_path).read_bytes()
        with Image.open(image_path) as image:
            actual_size = {"width": image.width, "height": image.height}
    except (OSError, ValueError) as error:
        raise ValueError("target_proposal_image_invalid") from error
    if sha256(raw).hexdigest() != digest or actual_size != size:
        raise ValueError("target_proposal_image_digest_mismatch")
    app = frame.get("application")
    if (not isinstance(app, dict) or set(app) not in ({"executable_name"}, {"executable_name", "window_class"})
            or not isinstance(app.get("executable_name"), str) or not app["executable_name"].strip()):
        raise ValueError("target_proposal_application_invalid")
    return frame


def _snapshot(observation, frame):
    envelope = observation.get("uia")
    if not isinstance(envelope, dict) or envelope.get("status") != "ok":
        return None
    if envelope.get("capture_id") != frame["capture_id"] or envelope.get("window_identity") != frame["window_identity"]:
        raise ValueError("target_proposal_uia_binding_mismatch")
    snapshot = envelope.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("status") != "ok":
        return None
    window = snapshot.get("window")
    if (not isinstance(window, dict) or window.get("handle") != frame["window_identity"]["handle"]
            or window.get("process_id") != frame["window_identity"]["process_id"]):
        raise ValueError("target_proposal_uia_window_mismatch")
    if (snapshot.get("scan_scope", "bound_window") != "bound_window"
            or snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False
            or not isinstance(snapshot.get("controls"), list)):
        return None
    return snapshot


def _native_row_proposal(snapshot, frame, candidate):
    """仅由原实际点击的唯一同名子区提议原生行关系。"""
    from .uia_rows import _bound_snapshot, _inside, _matches as row_matches, resolve_uia_row
    capture = {key: deepcopy(frame[key]) for key in ("capture_id", "window_identity", "image_size", "sha256")}
    capture["run_id"] = "native-row-proposal"
    try:
        if (candidate.get("capture_id") != frame["capture_id"]
                or candidate.get("viewport_size") != frame["image_size"]
                or candidate.get("freshness") != "current_capture"
                or not _bbox(candidate.get("bbox"), frame["image_size"])
                or not _point(candidate.get("click_point"), candidate["bbox"])):
            return None
        controls, viewport = _bound_snapshot(snapshot, capture)
        rows = [row for row in controls if row_matches(row, {"control_type": "ListItem"})
                and _bbox(row.get("bbox"), frame["image_size"])
                and _point(candidate["click_point"], row["bbox"])]
        if len(rows) != 1 or not isinstance(rows[0].get("name"), str) or not rows[0]["name"].strip():
            return None
        row = rows[0]
        containers = [item for item in controls if item["control_id"] in row["ancestor_control_ids"]
                      and row_matches(item, {"control_type": "List"})]
        if len(containers) != 1 or not _inside(containers[0].get("bbox"), viewport):
            return None
        container = containers[0]
        container_selector = {key: value for key, value in _locator(container).items() if key != "kind" and value}
        children = [child for child in controls if row["control_id"] in child["ancestor_control_ids"]
                    and row_matches(child, {"control_type": "Edit", "name": row["name"]})]
        if (len(children) != 1 or not _inside(children[0].get("bbox"), row["bbox"])
                or not _point(candidate["click_point"], children[0]["bbox"])
                or not _overlap(candidate["bbox"], children[0]["bbox"])):
            return None
        child = children[0]
        strategy = {"kind": "visible_row", "container": container_selector,
                    "row": {"control_type": "ListItem"},
                    "properties": [{"property": "target_value", "source": "row", "control_type": "ListItem", "read": "name"}],
                    "constraints": [{"property": "target_value", "operator": "eq",
                                     "value": {"source": "constant", "value": row["name"]}}],
                    "action": {"source": "row_name", "control_type": "Edit"}}
        resolved = resolve_uia_row(snapshot, strategy, capture=capture,
                                  bindings={"run_id": capture["run_id"], "inputs": {}, "outputs": {}})
        if (resolved["candidate"]["action_id"] != child["control_id"]
                or resolved["candidate"]["row_id"] != row["control_id"]
                or resolved["candidate"]["bbox"] != child["bbox"]):
            return None
        return child, strategy
    except ValueError:
        # 原生关系未能满足完整契约时保持未解析，不退回整行中心。
        return None


def propose_target_recipe(*, event: dict, observation: dict, bindings: dict) -> dict:
    """仅返回可审核候选；本函数不写库、不把单次观察说成通用验证。"""
    if not isinstance(event, dict) or not isinstance(observation, dict) or not isinstance(bindings, dict):
        raise ValueError("target_proposal_arguments_invalid")
    if observation.get("contract_version") != "learning_target_observation.v1":
        raise ValueError("target_proposal_contract_invalid")
    if event.get("status") != "returned" or event.get("action_executed") is not True:
        return _unresolved("successful_action_required")
    action = bindings.get("action")
    if not isinstance(action, dict) or action.get("kind") not in _TARGET_TYPES:
        return _unresolved("fixed_uia_action_unsupported")
    if (action["kind"] == "click" and (event.get("kind"), event.get("operation")) !=
            ("step", "execute_recognition_plan")) or (action["kind"] == "input_sequence"
            and event.get("kind") != "input_sequence"):
        raise ValueError("target_proposal_action_source_mismatch")
    hints = event.get("action_hints")
    if not isinstance(hints, dict):
        return _unresolved("recorded_action_semantics_required")
    intent_key = "goal" if action["kind"] == "click" else "field_goal"
    if hints.get(intent_key) != action.get(intent_key):
        raise ValueError("target_proposal_action_semantics_mismatch")
    if action["kind"] == "click":
        if hints.get("click_kind", "single") != action.get("click_kind", "single"):
            raise ValueError("target_proposal_action_semantics_mismatch")
        if action.get("click_kind", "single") != "single":
            return _unresolved("fixed_uia_action_unsupported")
    elif hints.get("submit_search") != action.get("submit_search"):
        raise ValueError("target_proposal_action_semantics_mismatch")
    frame = _frame(observation, event)
    if frame is None:
        return _unresolved("before_observation_required")
    interface = bindings.get("interface")
    if not isinstance(interface, dict) or not isinstance(interface.get("source"), dict):
        return _unresolved("pinned_before_interface_required")
    source = interface["source"]
    if source.get("kind") != "execution_memory_v1":
        raise ValueError("target_proposal_interface_source_mismatch")
    action_evidence = bindings.get("action_evidence")
    if action_evidence is None:
        if source.get("view") != "before" or source.get("event_id") != event.get("request_id"):
            raise ValueError("target_proposal_interface_source_mismatch")
        if source.get("screenshot_sha256") != frame["sha256"]:
            raise ValueError("target_proposal_source_image_mismatch")
    else:
        from .action_evidence import validate_action_evidence_reference
        from .learning_observation_source import learning_observation_reference
        from .projector import validate_event_review
        from .receipt_adapter import content_hash
        action_evidence = validate_action_evidence_reference(action_evidence)
        review = validate_event_review(event, bindings.get("review"))
        before = review["before"]
        if (review["verdict"] != "success" or before is None
                or any(action_evidence[key] != event.get(key) for key in ("session_id", "learning_id"))
                or action_evidence["event_id"] != event["request_id"]
                or action_evidence["observation_sha256"] != learning_observation_reference(observation)["sha256"]
                or any(source.get(key) != before[key] for key in ("interface_key", "state_key"))
                or action_evidence["source_node_id"] != "state-" +
                    content_hash([before["interface_key"], before["state_key"]])[:32]):
            raise ValueError("target_proposal_action_evidence_mismatch")
    if not all(isinstance(interface.get(key), str) and interface[key] for key in
               ("interface_id", "version_id", "content_sha256")):
        return _unresolved("pinned_before_interface_required")
    inputs = bindings.get("inputs", {})
    if not isinstance(inputs, dict):
        raise ValueError("target_proposal_inputs_invalid")
    snapshot = _snapshot(observation, frame)
    if snapshot is None:
        return _unresolved("complete_uia_snapshot_required")
    candidate = observation.get("candidate")
    size = frame["image_size"]
    if not isinstance(candidate, dict):
        return _unresolved("executed_target_candidate_required")
    if (candidate.get("capture_id") != frame["capture_id"]
            or candidate.get("viewport_size") != size or candidate.get("freshness") != "current_capture"):
        raise ValueError("target_proposal_candidate_binding_mismatch")
    box = candidate.get("bbox")
    if not _bbox(box, size) or not _point(candidate.get("click_point"), box):
        raise ValueError("target_proposal_candidate_geometry_invalid")
    controls = snapshot["controls"]
    target_rows = [row for row in controls if isinstance(row, dict)
                   and row.get("visible") is True and row.get("enabled") is True
                   and row.get("control_type") in _TARGET_TYPES[action["kind"]]
                   and _bbox(row.get("bbox"), size) and _overlap(row["bbox"], box)
                   and _point(candidate["click_point"], row["bbox"])
                   and isinstance(row.get("name"), str) and row["name"].strip()]
    native = None
    if not target_rows and action["kind"] == "click":
        native = _native_row_proposal(snapshot, frame, candidate)
    if len(target_rows) != 1 and native is None:
        return _unresolved("unique_executed_uia_target_required")
    target = native[0] if native else target_rows[0]
    locator = _locator(target)
    if not native and sum(_matches(row, locator) for row in controls if isinstance(row, dict)) != 1:
        return _unresolved("unique_uia_target_locator_required")
    anchors = [row for row in controls if isinstance(row, dict) and row.get("control_type") in ({"Text", "HeaderItem"} if native else {"Text"})
               and row.get("visible") is True and row.get("enabled") is True
               and _bbox(row.get("bbox"), size) and not _overlap(row["bbox"], box)
               and not _overlap(row["bbox"], target["bbox"])
               and _stable_anchor_name(row.get("name"), inputs)]
    counts = Counter((row.get("name"), row.get("control_type"), row.get("automation_id")) for row in anchors)
    anchors = [row for row in anchors if counts[(row.get("name"), row.get("control_type"), row.get("automation_id"))] == 1
               and sum(_matches(control, _locator(row)) for control in controls if isinstance(control, dict)) == 1]
    if not anchors:
        return _unresolved("independent_stable_anchor_required")
    anchors.sort(key=lambda row: (row["name"], row.get("automation_id") or "", row["bbox"]["x"], row["bbox"]["y"]))
    scope = {key: source[key] for key in ("task_id", "interface_key", "state_key")}
    scope.update(application=deepcopy(frame["application"]), anchors=[_locator(anchors[0])])
    strategies = [native[1] if native else locator]
    evidence = [{"kind": "interface_content", "content_sha256": interface["content_sha256"],
                 "source_image_sha256": source["screenshot_sha256"]}]
    if action_evidence is not None:
        evidence.append(action_evidence)
    body = {"contract_version": "target_recipe.v2" if action_evidence is not None else "target_recipe.v1",
            "interface_id": interface["interface_id"],
            "interface_version_id": interface["version_id"], "scope": scope,
            "strategies": strategies, "evidence_refs": evidence,
            "action_semantics_sha256": action_semantics_sha256(action, scope=scope, strategies=strategies)}
    recipe = {**body, "recipe_id": "target-recipe-" + sha256(canonical_json_bytes(body)).hexdigest()}
    _validate_recipe(recipe)
    return {"recipe": recipe, "unresolved_items": [], "evidence_refs": deepcopy(evidence)}


__all__ = ["propose_target_recipe"]
