"""在当前截图和完整控件快照上解析已固定的目标规则。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from math import isfinite
from pathlib import Path

from PIL import Image

from .target_recipe import action_semantics_sha256, load_target_recipe, validate_editorial_action
from .templates import match_template_frame
from .uia_rows import resolve_uia_row


def _result(status, reason, reference, frame, goal, *, candidate=None, verified=False, evidence=None):
    return {"status": status, "reason": reason, "goal": goal, "reference": deepcopy(reference),
            "frame": deepcopy(frame), "candidate": deepcopy(candidate),
            "context_verified": verified, "evidence": deepcopy(evidence or {})}


def _frame_valid(frame):
    if not isinstance(frame, dict) or not isinstance(frame.get("capture_id"), str) or not frame["capture_id"]:
        return False
    identity = frame.get("window_identity")
    if (not isinstance(identity, dict) or type(identity.get("handle")) is not int or identity["handle"] <= 0
            or type(identity.get("process_id")) is not int or identity["process_id"] <= 0
            or type(identity.get("process_create_time")) not in (int, float)
            or not isfinite(identity["process_create_time"]) or identity["process_create_time"] <= 0):
        return False
    size = frame.get("image_size")
    if (not isinstance(size, dict) or type(size.get("width")) is not int or size["width"] <= 0
            or type(size.get("height")) is not int or size["height"] <= 0):
        return False
    path = frame.get("image_path")
    digest = frame.get("sha256")
    if not isinstance(path, str) or not path or not isinstance(digest, str) or len(digest) != 64:
        return False
    try:
        if sha256(Path(path).read_bytes()).hexdigest() != digest:
            return False
        with Image.open(path) as image:
            return size == {"width": image.width, "height": image.height}
    except (OSError, ValueError):
        return False


def _uia_snapshot(observations, frame):
    row = observations.get("uia") if isinstance(observations, dict) else None
    if not isinstance(row, dict) or row.get("status") != "ok":
        return None, "uia_unavailable"
    if row.get("capture_id") != frame["capture_id"] or row.get("window_identity") != frame["window_identity"]:
        return None, "uia_binding_changed"
    snapshot = row.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("status") != "ok":
        return None, "uia_unavailable"
    window = snapshot.get("window")
    identity = frame["window_identity"]
    if (not isinstance(window, dict) or window.get("handle") != identity["handle"]
            or window.get("process_id") != identity["process_id"]):
        return None, "uia_binding_changed"
    if (snapshot.get("scan_scope", "bound_window") != "bound_window"
            or snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False):
        return None, "uia_incomplete"
    if not isinstance(snapshot.get("controls"), list):
        return None, "uia_invalid"
    return snapshot, None


def _matches_control(control, locator):
    return (isinstance(control, dict) and control.get("visible") is True and control.get("enabled") is True
            and control.get("name") == locator["name"]
            and control.get("control_type") == locator["control_type"]
            and ("automation_id" not in locator or control.get("automation_id") == locator["automation_id"]))


def _unique_control(snapshot, locator):
    matches = [item for item in snapshot["controls"] if _matches_control(item, locator)]
    return (matches[0], "matched") if len(matches) == 1 else (None, "ambiguous" if matches else "miss")


def _candidate(frame, bbox, source, label, role, score):
    size = frame["image_size"]
    if (not isinstance(bbox, dict) or any(type(bbox.get(k)) is not int for k in ("x", "y", "w", "h"))
            or not (0 <= bbox["x"] < bbox["x"] + bbox["w"] <= size["width"])
            or not (0 <= bbox["y"] < bbox["y"] + bbox["h"] <= size["height"])):
        return None
    point = {"x": bbox["x"] + bbox["w"] // 2, "y": bbox["y"] + bbox["h"] // 2}
    return {"capture_id": frame["capture_id"], "viewport_size": deepcopy(size), "source": source,
            "bbox": deepcopy(bbox), "click_point": point, "score": score, "label": label,
            "role": role, "freshness": "current_capture"}


def _template(library, locator, reference, frame):
    request = {"template_id": locator["template_id"], "interface_key": reference["interface_key"],
               "state_key": reference["state_key"], "frame_sha256": frame["sha256"]}
    evidence = {"sha256": frame["sha256"], "image_path": frame["image_path"],
                "capture_id": frame["capture_id"]}
    match = match_template_frame(library, request, Path(frame["image_path"]), evidence)
    status = match.get("status")
    if status == "matched":
        return _candidate(frame, match["candidate"]["bbox"], "memory_template",
                          match.get("label", ""), "control", match["candidate"].get("score", 0.0)), "matched"
    if status in {"not_found", "viewport_changed_relearn_required", "template_has_insufficient_detail"}:
        return None, "miss"
    if status == "ambiguous":
        return None, "ambiguous"
    return None, "invalid"


def _row_bindings(bindings, frame):
    required = {"action", "run_id", "inputs", "outputs"}
    if not isinstance(bindings, dict) or not required <= set(bindings):
        return None, "trial_bindings_required"
    if (set(bindings) != required or not isinstance(bindings["run_id"], str)
            or not bindings["run_id"].strip() or not isinstance(bindings["inputs"], dict)
            or not isinstance(bindings["outputs"], dict)
            or "run_id" in frame and frame["run_id"] != bindings["run_id"]):
        return None, "trial_bindings_invalid"
    return {key: bindings[key] for key in ("run_id", "inputs", "outputs")}, None


def _row_error(error):
    reason = str(error)
    if reason in {"visible_row_missing", "uia_container_missing", "row_action_missing",
                  "uia_property_missing", "uia_property_value_missing"}:
        return "miss", reason
    if reason in {"visible_row_ambiguous", "uia_container_ambiguous", "row_action_ambiguous",
                  "uia_property_ambiguous"}:
        return "ambiguous", reason
    if reason in {"uia_snapshot_incomplete", "uia_controls_missing_or_unbounded", "uia_rows_unbounded"}:
        return "unsupported", reason
    return "invalid", reason


def resolve_target_recipe(library, reference: dict, *, frame: dict, observations: dict, bindings: dict) -> dict:
    recipe = load_target_recipe(library, reference)
    return _resolve_loaded_recipe(library, reference, recipe, frame=frame, observations=observations, bindings=bindings)


def _resolve_loaded_recipe(library, reference: dict, recipe: dict, *, frame: dict,
                           observations: dict, bindings: dict) -> dict:
    action = bindings.get("action") if isinstance(bindings, dict) else None
    goal = action.get("goal") if isinstance(action, dict) and action.get("kind") == "click" else (
        action.get("field_goal") if isinstance(action, dict) and action.get("kind") == "input_sequence" else None)
    if not isinstance(goal, str) or not goal.strip():
        return _result("invalid", "action_binding_missing", reference, frame, goal)
    if action_semantics_sha256(action, scope=recipe["scope"], strategies=recipe["strategies"]) != recipe["action_semantics_sha256"]:
        return _result("invalid", "action_semantics_changed", reference, frame, goal)
    try:
        validate_editorial_action(recipe, action)
    except ValueError as error:
        return _result("invalid", str(error), reference, frame, goal)
    if not _frame_valid(frame):
        return _result("invalid", "current_frame_invalid", reference, frame, goal)
    row_bindings = None
    if any(strategy["kind"] == "visible_row" for strategy in recipe["strategies"]):
        row_bindings, binding_error = _row_bindings(bindings, frame)
        if binding_error:
            status = "unsupported" if binding_error == "trial_bindings_required" else "invalid"
            return _result(status, binding_error, reference, frame, goal)
    scope = recipe["scope"]
    application, anchors = scope.get("application"), scope.get("anchors")
    if not application or not anchors:
        return _result("unsupported", "context_anchor_missing", reference, frame, goal)
    live_app = frame.get("application")
    if not isinstance(live_app, dict) or any(live_app.get(key) != value for key, value in application.items()):
        return _result("invalid", "application_identity_mismatch", reference, frame, goal)
    needs_uia = any(row["kind"] in {"uia", "visible_row"} for row in [*anchors, *recipe["strategies"]])
    snapshot, uia_error = _uia_snapshot(observations, frame) if needs_uia else (None, None)
    if uia_error == "uia_binding_changed":
        return _result("invalid", uia_error, reference, frame, goal)
    if uia_error:
        return _result("unsupported", uia_error, reference, frame, goal)
    anchor_evidence = []
    for anchor in anchors:
        if anchor["kind"] == "uia":
            control, status = _unique_control(snapshot, anchor)
            if status != "matched":
                return _result(status, "context_anchor_" + status, reference, frame, goal)
            anchor_evidence.append({"kind": "uia", "bbox": deepcopy(control.get("bbox")),
                                    "name": anchor["name"], "control_type": anchor["control_type"]})
        else:
            if any(row["kind"] == "template" and row["template_id"] == anchor["template_id"]
                   for row in recipe["strategies"]):
                return _result("invalid", "context_anchor_is_target", reference, frame, goal)
            candidate, status = _template(library, anchor, reference, frame)
            if status != "matched":
                return _result(status, "context_anchor_" + status, reference, frame, goal)
            anchor_evidence.append({"kind": "template", "template_id": anchor["template_id"],
                                    "bbox": candidate["bbox"]})
    for strategy in recipe["strategies"]:
        if strategy["kind"] == "uia":
            control, status = _unique_control(snapshot, strategy)
            if status != "matched":
                if status == "ambiguous":
                    return _result(status, "target_ambiguous", reference, frame, goal,
                                   evidence={"anchors": anchor_evidence})
                continue
            if any(row["kind"] == "uia" and row["bbox"] == control.get("bbox") for row in anchor_evidence):
                return _result("invalid", "context_anchor_is_target", reference, frame, goal)
            candidate = _candidate(frame, control.get("bbox"), "memory_uia", control.get("name", ""),
                                   control.get("control_type", "control"), 1.0)
        elif strategy["kind"] == "visible_row":
            capture = {key: deepcopy(frame[key]) for key in ("capture_id", "window_identity", "image_size", "sha256")}
            capture["run_id"] = row_bindings["run_id"]
            try:
                row_result = resolve_uia_row(snapshot, strategy, capture=capture, bindings=row_bindings)
            except ValueError as error:
                status, reason = _row_error(error)
                return _result(status, reason, reference, frame, goal,
                               evidence={"anchors": anchor_evidence})
            row_candidate = row_result["candidate"]
            candidate = _candidate(frame, row_candidate["bbox"], "memory_visible_row",
                                   row_candidate["label"], row_candidate["role"], 1.0)
            if candidate is None:
                return _result("invalid", "visible_row_geometry_invalid", reference, frame, goal)
            if any(anchor["bbox"] == candidate["bbox"] for anchor in anchor_evidence):
                return _result("invalid", "context_anchor_is_target", reference, frame, goal)
            return _result("matched", "unique_current_row_action", reference, frame, goal,
                           candidate=candidate, verified=True,
                           evidence={"anchors": anchor_evidence, "strategy": deepcopy(strategy),
                                     "row": row_result["evidence"], "capture_id": frame["capture_id"],
                                     "sha256": frame["sha256"], "run_id": row_bindings["run_id"]})
        else:
            candidate, status = _template(library, strategy, reference, frame)
            if status == "ambiguous":
                return _result(status, "target_ambiguous", reference, frame, goal,
                               evidence={"anchors": anchor_evidence})
            if status == "invalid":
                return _result(status, "target_template_invalid", reference, frame, goal)
            if candidate is not None and any(row["bbox"] == candidate["bbox"] for row in anchor_evidence):
                return _result("invalid", "context_anchor_is_target", reference, frame, goal)
        if candidate is None:
            continue
        return _result("matched", "unique_current_target", reference, frame, goal,
                       candidate=candidate, verified=True,
                       evidence={"anchors": anchor_evidence, "strategy": deepcopy(strategy),
                                 "capture_id": frame["capture_id"], "sha256": frame["sha256"]})
    return _result("miss", "target_not_found", reference, frame, goal,
                   evidence={"anchors": anchor_evidence})


__all__ = ["resolve_target_recipe"]
