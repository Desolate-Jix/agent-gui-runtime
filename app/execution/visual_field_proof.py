"""视觉字段的后验凭据；截图判断与原生读值分别绑定，不授予输入权限。"""
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import json
from math import isfinite
from pathlib import Path
from threading import get_ident
from time import perf_counter_ns, sleep
from weakref import WeakKeyDictionary

from PIL import Image, ImageChops

from app.core.local_input_policy import current_local_operator_identity, require_local_operator_input
from app.core.receipt_action import _receipt_action
from .decision_check import _evaluate, _identity, _candidate, decision_frame


VISUAL_FOCUS_CONDITION = (
    "The specified ordinary readable text field visibly has keyboard focus, is enabled and editable, "
    "and is not a password or masked field.")
VISUAL_SELECTION_CONDITION = (
    "The specified ordinary readable text field retains keyboard focus and the same complete existing text shown "
    "in the original post-click image is now visibly selected for replacement; it is enabled, editable, unmasked, "
    "and no other field or popup has taken focus.")
from app.judgment.visual_action_conditions import (VISUAL_FIELD_FRESHNESS_CONDITION, VISUAL_VALUE_CONDITION,
    VISUAL_TEXT_VALUE_CONDITION, VISUAL_INPUT_CLICKED_CONDITION, VISUAL_INPUT_READY_CONDITION, VISUAL_REPLACEMENT_READY_CONDITION)
_ISSUER = object()
_KEYBOARD_ISSUED = WeakKeyDictionary()
_UNAVAILABLE = {"text_field_uia_unavailable", "text_field_provider_unavailable",
    "text_field_hit_provider_unavailable", "text_field_value_pattern_unavailable",
    "text_field_value_unavailable", "text_field_text_unavailable", "text_field_control_unavailable"}


class VisualFieldChanged(ValueError):
    def __init__(self, frame, *, native_snapshot=None):
        self.frame = deepcopy(frame)
        self.native_snapshot = native_snapshot
        super().__init__("visual_field_fresh_proof_required")


class VisualFieldReviewRequired(ValueError):
    def __init__(self, reason, *, request, assessment, _issuer=None):
        if _issuer is not _ISSUER:
            raise ValueError("visual_field_review_issuer_invalid")
        self._issuer = _issuer
        self._reference_json = _json({"schema": "visual_field_main_handoff.v1", "reason": reason,
            "request": request, "assessment": assessment, "automatic_retry_allowed": False,
            "authorizes_action": False,
            "allowed_next_steps": ["inspect_original_evidence", "close_or_explicitly_replan"]})
        super().__init__(reason)

    def to_reference(self):
        if self._issuer is not _ISSUER:
            raise ValueError("visual_field_review_issuer_invalid")
        return json.loads(self._reference_json)


def _raise_field_review(service, request, result, context, reason):
    # 只把原服务已认证的只读判断交回 Main；鉴权与取消失败不冒充模型拒绝。
    if result.get("disposition") == "review_required":
        if service.validate_result(result, **request) is not True:
            raise ValueError("visual_field_review_authentication_invalid")
        _deadline(context)
        raise VisualFieldReviewRequired(reason, request=request, assessment=result, _issuer=_ISSUER)
    raise ValueError(reason)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _deadline(context):
    cancelled = context.get("cancelled")
    if cancelled is not None:
        if not callable(cancelled):
            raise ValueError("visual_field_cancel_predicate_invalid")
        if cancelled():
            raise ValueError("visual_field_cancelled")
    value = context.get("deadline_ns")
    if type(value) is not int or value <= perf_counter_ns():
        raise ValueError("visual_field_deadline_expired")
    return value


@dataclass(frozen=True, slots=True)
class VisualValueReading:
    _json_value: str = field(repr=False)
    _owner: int = field(repr=False)
    _issuer: object = field(repr=False)

    def reference(self):
        if self._issuer is not _ISSUER or self._owner != get_ident():
            raise ValueError("visual_field_value_reading_invalid")
        return json.loads(self._json_value)


@dataclass(frozen=True, slots=True)
class VisualFieldProof:
    _json_value: str = field(repr=False)
    _service: object = field(repr=False)
    _deadline_ns: int = field(repr=False)
    _owner: int = field(repr=False)
    _issuer: object = field(repr=False)
    _keyboard_issued: bool = field(default=False, init=False, repr=False)
    _focus_snapshot: object = field(default=None, repr=False)
    _cancelled: object = field(default=None, repr=False)
    _capture_visibility_json: str | None = field(default=None, repr=False)

    def request(self):
        return deepcopy(_checked_proof(self)["request"])

    def assessment(self):
        return deepcopy(_checked_proof(self)["assessment"])

    def to_reference(self):
        value = _checked_proof(self)
        action = value["request"]["action"]
        reading = action.get("value_reading") or action.get("focus_value_snapshot") or {}
        reference = {"schema": "visual_field_proof.v1", "evidence_kind": "visual", "phase": action["field_phase"],
            "source": reading.get("source", "decision_visual"),
            "focus_stage": action.get("focus_stage"),
            "field": deepcopy(action["field"]), "frame": deepcopy(value["request"]["frames"][-1]),
            "frames": deepcopy(value["request"]["frames"]),
            "focus_receipt_sha256": action["focus_receipt_sha256"],
            "input_receipt_sha256": action["input_receipt_sha256"],
            "selection_dispatch": deepcopy(action.get("selection_dispatch")),
            "request_sha256": value["assessment"]["request_sha256"],
            "value_sha256": sha256(action["actual_text"].encode("utf-8")).hexdigest()
                if action["actual_text"] is not None else None,
            "reading": deepcopy(action["value_reading"]), "artifact_is_authorization": False}
        if "field_content_result" in value["assessment"]:
            reference["field_content_result"] = deepcopy(value["assessment"]["field_content_result"])
        if "field_content_ocr" in action:
            reference["field_content_ocr"] = deepcopy(action["field_content_ocr"])
        if action.get("value_verification") == "visual":
            reference["value_verification"] = "visual"
        if "field_freshness_context" in action:
            reference["freshness_review"] = {**deepcopy(action["field_freshness_context"]),
                "request_sha256": value["assessment"]["request_sha256"],
                "assessment_sha256": _digest(value["assessment"]), "review_count": 1}
        return reference


def _checked_proof(proof):
    if (type(proof) is not VisualFieldProof or proof._issuer is not _ISSUER
            or proof._owner != get_ident()):
        raise ValueError("visual_field_proof_issuer_or_owner_invalid")
    _deadline({"deadline_ns": proof._deadline_ns, "cancelled": proof._cancelled})
    value = json.loads(proof._json_value)
    if proof._service.validate_result(value["assessment"], **value["request"]) is not True:
        raise ValueError("visual_field_proof_authentication_invalid")
    _deadline({"deadline_ns": proof._deadline_ns, "cancelled": proof._cancelled})
    return value


def visual_field_is_empty(proof):
    """新请求使用绑定原图的本地 OCR；历史请求保留原分类语义。"""
    from app.judgment.field_content_choice import field_content_requested
    value = _checked_proof(proof)
    result = value["assessment"]
    request = value["request"]
    if "field_content_ocr" in request["action"]:
        return (result.get("adopted") is True and result.get("verdict") == "success"
            and _ocr_content_state(request) == "empty")
    return (field_content_requested(value["request"])
        and result.get("adopted") is True and result.get("verdict") == "success"
        and (result.get("field_content_result") or {}).get("choice") == "empty")


def _ocr_content_state(request):
    from .field_content_ocr import validate_field_content
    action = request["action"]
    content = action["field_content_ocr"]
    if (type(content) is not dict or set(content) != {"schema", "clear_existing", "reading"}
            or content["schema"] != "visual_field_content_ocr.v1" or type(content["clear_existing"]) is not bool
            or "field_content_check" in action or action["field_phase"] != "focus"
            or action["focus_stage"] != "after_click" or len(request["frames"]) != 1):
        raise ValueError("visual_field_ocr_binding_invalid")
    return validate_field_content(content["reading"], frame=request["frames"][0], field=action["field"])


def _claim_keyboard_proof(proof):
    value = _checked_proof(proof)
    if "field_freshness_context" in value["request"]["action"]:
        raise ValueError("visual_field_keyboard_proof_consumed")
    issued = _KEYBOARD_ISSUED.setdefault(proof._service, set())
    binding = value["assessment"]["request_sha256"]
    if proof._keyboard_issued or binding in issued:
        raise ValueError("visual_field_keyboard_proof_consumed")
    issued.add(binding)
    object.__setattr__(proof, "_keyboard_issued", True)


def _field(expected, focus_receipt):
    if (not isinstance(expected, dict) or set(expected) != {"field_goal", "bbox", "click_point",
            "window_identity", "window_rect", "field_kind", "expected_text"}
            or expected.get("field_kind") not in {"text", "search", "address_bar"}
            or type(expected.get("expected_text")) is not str or not expected["expected_text"]
            or len(expected["expected_text"]) > 20000):
        raise ValueError("visual_field_description_invalid")
    selected = _candidate({"bbox": expected["bbox"]}, expected["click_point"])
    field_value = deepcopy(expected)
    field_value["bbox"] = selected["bbox"]
    identity = _identity(focus_receipt.get("target_identity"))
    geometry = focus_receipt.get("target_window_geometry") or {}
    rect = geometry.get("rect")
    if (geometry.get("coordinate_space") != "screen_pixels" or geometry.get("rect_format") != "ltrb"
            or type(rect) is not list or len(rect) != 4 or any(type(n) is not int for n in rect)
            or expected["window_rect"] != [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]]
            or _identity(expected["window_identity"]) != identity
            or expected["field_goal"] != (focus_receipt.get("request") or {}).get("goal")):
        raise ValueError("visual_field_window_binding_invalid")
    box = selected["bbox"]
    if (min(box["x"], box["y"]) < 0 or box["x"] + box["w"] > expected["window_rect"][2]
            or box["y"] + box["h"] > expected["window_rect"][3]):
        raise ValueError("visual_field_bbox_invalid")
    data = (focus_receipt.get("response") or {}).get("data") or {}
    data = data.get("result", data)
    chosen = (data.get("recognition_plan") or {}).get("recommended_target")
    if (data.get("selected_click_point_coordinate_space") != "capture_image_pixels"
            or data.get("selected_click_point") != expected["click_point"]
            or _candidate(chosen, expected["click_point"])["bbox"] != box):
        raise ValueError("visual_field_original_candidate_changed")
    field_value["window_identity"] = identity
    return field_value


def _completed(receipt, operation):
    if not isinstance(receipt, dict):
        raise ValueError("visual_field_original_input_not_completed")
    data = (receipt.get("response") or {}).get("data") or {}
    data = data.get("result", data)
    if (receipt.get("contract_version") != "local_direct_step_v1" or receipt.get("operation") != operation
            or receipt.get("phase") != "returned" or receipt.get("local_input_scope_closed") is not True
            or not receipt.get("finished_at") or (receipt.get("response") or {}).get("success") is not True
            or _receipt_action(receipt, operation) is not True
            or (operation == "execute_recognition_plan" and (data.get("click_result") or {}).get("clicked") is not True)
            or (operation == "type_text" and (data.get("type_result") or data).get("typed") is not True)):
        raise ValueError("visual_field_original_input_not_completed")


def _validate_png(frame, expected):
    with Image.open(frame["image_path"]) as image:
        if image.format != "PNG" or getattr(image, "is_animated", False) or image.size != tuple(expected["window_rect"][2:]):
            raise ValueError("visual_field_image_geometry_invalid")
        image.verify()



def _focus_target_binding(context, focus_receipt, expected, *, required=False):
    """原候选判断必须认证到本次计划和实际点击，值判断只保存本地绑定。"""
    from .action_review import normalize_action_review_context, CANDIDATE_CONDITION
    from app.judgment.target_identity import normalize_target_identity
    from app.judgment.target_check import normalize_target_check
    data = focus_receipt["response"]["data"]
    data = data.get("result", data)
    summary = data.get("action_assessment")
    original = context.get("action_review")
    if original is None:
        source_action = (summary.get("evaluation_request", {}).get("action") or {}) if isinstance(summary, dict) else {}
        if {"target_identity", "target_check"}.intersection(source_action):
            raise ValueError("visual_field_target_review_context_required")
        return None
    checked = normalize_action_review_context(original)
    if checked["plan"]["schema_version"] != "task_plan.v3":
        return None
    step = next(row for row in checked["plan"]["steps"] if row["step_id"] == checked["step_id"])
    permitted = step["action"]
    if summary is None and (not required or "target_identity" in permitted):
        return None
    try:
        request = summary["evaluation_request"]
        action = request["action"]
        raw = summary["judgment"]["judgment_result"]
        candidate = _candidate(data["recognition_plan"]["recommended_target"], expected["click_point"])
        frame = request["frames"][0]
        if (summary["scope"] != "candidate" or summary["disposition"] != "pass"
                or summary["authorizes_action"] is not False
                or summary["envelope_sha256"] != action["envelope_sha256"]
                or request["condition"] != CANDIDATE_CONDITION or request["phase"] != "before_action"
                or request["step_id"] != checked["step_id"] or len(request["frames"]) != 1
                or request["execution_request_id"] != "attempt-" + _digest([
                    checked["run_id"], checked["step_id"], checked["attempt_id"]])[:40]
                or request["request_id"] != "action-review-" + summary["envelope_sha256"][:40]
                or request["review_context"]["source_id"] != checked["run_id"]
                or request["review_context"]["source_sha256"] != _digest(checked["plan"])
                or action["operation"] != "execute_recognition_plan" or action["review_scope"] != "candidate"
                or action["permitted_action"] != permitted or permitted.get("kind") != "input_sequence"
                or action["goal"] != permitted["field_goal"] or permitted["field_goal"] != expected["field_goal"]
                or action["source_candidate"] != candidate
                or action["candidate"] != {**candidate, "capture_id": frame["capture_id"]}
                or action["target_window_identity"] != expected["window_identity"]
                or frame["window_identity"] != expected["window_identity"]
                or raw.get("adopted") is not True or raw.get("verdict") != "success"
                or context["service"].validate_result(raw, **request) is not True):
            raise ValueError("visual_field_target_identity_source_invalid")
        if {"target_identity", "target_check"} <= set(action):
            raise ValueError("visual_field_target_review_sources_conflict")
        if "target_check" in action:
            key = "target_check"
            spec = normalize_target_check(action[key])
            if ("target_identity" in permitted or spec["target"] != expected["field_goal"]
                    or spec["kind"] != "input_field"):
                raise ValueError("visual_field_target_check_goal_mismatch")
        elif "target_identity" in action:
            key = "target_identity"
            spec = normalize_target_identity(action[key])
            if "target_identity" in permitted:
                if spec != permitted["target_identity"]:
                    raise ValueError("visual_field_target_identity_source_invalid")
            elif next(row["description"] for row in spec["choices"] if row["value"] == spec["expected"]) != expected["field_goal"]:
                raise ValueError("visual_field_target_identity_goal_mismatch")
        else:
            return None
        return {"schema": key + "_binding.v1", "goal": expected["field_goal"], key: spec,
            "focus_receipt_sha256": _digest(focus_receipt), "action_review_sha256": _digest(checked),
            "source_request_sha256": raw["request_sha256"], "source_assessment_sha256": _digest(raw)}
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        raise ValueError("visual_field_target_identity_source_invalid") from error


def _request(*, phase, focus_receipt, input_receipt, frame, expected_field, context, value_reading,
             focus_observation=None):
    _deadline(context)
    native_evidence = context.get("native_field_evidence", True)
    if type(native_evidence) is not bool:
        raise ValueError("visual_field_native_evidence_mode_invalid")
    _completed(focus_receipt, "execute_recognition_plan")
    expected = _field(expected_field, focus_receipt)
    if phase not in {"focus", "value"} or phase == "focus" and input_receipt is not None:
        raise ValueError("visual_field_phase_invalid")
    source = focus_receipt
    reading = None
    focus_data = (focus_receipt.get("response") or {}).get("data") or {}
    compound = "visual_compound_input" in focus_data.get("result", focus_data)
    if compound and (native_evidence or phase != "value"):
        raise ValueError("visual_compound_value_phase_required")
    direct = False
    if phase == "value":
        if not isinstance(input_receipt, dict):
            raise ValueError("visual_field_original_input_not_completed")
        if compound:
            from app.core.visual_compound_input import validate_visual_compound_receipt
            if input_receipt != focus_receipt:
                raise ValueError("visual_compound_original_receipt_required")
            validate_visual_compound_receipt(input_receipt, expected,
                execution_request_id=context["execution_request_id"])
        else:
            _completed(input_receipt, "type_text")
        if not compound:
            command = input_receipt.get("request") or {}
            raw_present = "text" in command
            summary_present = "text_length" in command or "text_sha256" in command
            text_bound = ((raw_present or summary_present)
                and (not raw_present or command["text"] == expected["expected_text"])
                and (not summary_present or (type(command.get("text_length")) is int
                    and command["text_length"] == len(expected["expected_text"])
                    and type(command.get("text_sha256")) is str
                    and command["text_sha256"] == sha256(expected["expected_text"].encode("utf-8")).hexdigest())))
            direct = command.get("clear_existing") is False
            if direct:
                focus_proof = context.get("typing_focus_proof")
                if native_evidence or not visual_field_is_empty(focus_proof):
                    raise ValueError("visual_field_direct_input_proof_required")
                proven = focus_proof.request()["action"]
                if proven["field"] != expected or proven["focus_receipt_sha256"] != _digest(focus_receipt):
                    raise ValueError("visual_field_direct_input_binding_invalid")
            if (not text_bound or type(command.get("clear_existing")) is not bool
                    or command.get("click_before_typing", False) is not False or command.get("submit", False) is not False
                    or _identity(input_receipt.get("target_identity")) != expected["window_identity"]):
                raise ValueError("visual_field_input_binding_invalid")
        if native_evidence:
            if type(value_reading) is not VisualValueReading:
                raise ValueError("visual_field_value_reading_required")
            reading = value_reading.reference()
            if reading["text"] != expected["expected_text"]:
                raise ValueError("visual_field_value_mismatch")
        elif value_reading is not None:
            raise ValueError("visual_field_native_evidence_disabled")
        source = input_receipt
    observation = source.get("observation") or {}
    after = decision_frame(frame, expected["window_identity"], role="after")
    if (observation.get("status") != "captured"
            or after != decision_frame(observation.get("capture"), expected["window_identity"], role="after")
            or Path(after["image_path"]).resolve() == Path(source["capture"]["image_path"]).resolve()
            or after["capture_id"] == source["capture"].get("capture_id")
            or phase == "value" and not compound and (after["capture_id"] == focus_receipt["observation"]["capture"].get("capture_id")
                or Path(after["image_path"]).resolve() == Path(focus_receipt["observation"]["capture"]["image_path"]).resolve())):
        raise ValueError("visual_field_new_after_frame_required")
    _validate_png(after, expected)
    if reading is not None and (reading["frame_sha256"] != after["sha256"] or reading["capture_id"] != after["capture_id"]
            or reading["bbox"] != expected["bbox"]):
        raise ValueError("visual_field_value_reading_binding_invalid")
    action = {"operation": "visual_field_check", "field_phase": phase, "field": expected,
        "focus_stage": "after_click" if phase == "focus" else None,
        "focus_receipt_sha256": _digest(focus_receipt), "input_receipt_sha256": _digest(input_receipt) if input_receipt else None,
        "expected_text": expected["expected_text"] if phase == "value" else None,
        "actual_text": reading["text"] if reading else None, "value_reading": reading}
    if not native_evidence:
        from app.judgment.executed_click_annotation import executed_click_reference
        executed = executed_click_reference(focus_receipt, expected)
        if phase == "focus" and executed is None:
            raise ValueError("visual_field_executed_click_required")
        if executed is not None:
            action["executed_click"] = executed
            action["field_image_scope"] = {"schema": "visual_field_roi.v1", "padding": 16}
    target_binding = (_focus_target_binding(context, focus_receipt, expected, required=phase == "value")
        if not native_evidence and (phase == "value" or "target_identity" not in context) else None)
    if phase == "focus" and not native_evidence:
        from app.judgment.target_identity import normalize_target_identity
        if "target_identity" in context:
            action["target_identity"] = normalize_target_identity(context["target_identity"])
        elif target_binding is not None:
            key = "target_check" if "target_check" in target_binding else "target_identity"
            action[key] = deepcopy(target_binding[key])
    elif phase == "value" and not native_evidence and target_binding is not None:
        key = "target_check" if "target_check" in target_binding else "target_identity"
        action[key + "_binding"] = target_binding
    if phase == "focus" and "field_content_check" in context:
        action["field_content_check"] = deepcopy(context["field_content_check"])
    if phase == "focus" and "field_content_ocr" in context:
        if native_evidence:
            raise ValueError("visual_field_ocr_route_invalid")
        action["field_content_ocr"] = deepcopy(context["field_content_ocr"])
        _ocr_content_state({"action": action, "frames": [after]})
    if phase == "value" and not native_evidence:
        action["value_verification"] = "visual"
        if direct:
            action["direct_input_focus_request_sha256"] = context["typing_focus_proof"].assessment()["request_sha256"]
    frames = [after]
    if focus_observation is not None:
        raise ValueError("visual_input_ready_single_frame_required")
    execution_id = context["execution_request_id"]
    return {"request_id": "visual-field-" + _digest([execution_id, source["step_id"], phase])[:32],
        "execution_request_id": execution_id, "condition": ((VISUAL_FOCUS_CONDITION if native_evidence else VISUAL_INPUT_CLICKED_CONDITION) if phase == "focus"
            else VISUAL_VALUE_CONDITION if native_evidence else VISUAL_TEXT_VALUE_CONDITION),
        "frames": frames, "mode": "execution", "phase": "after_action", "step_id": source["step_id"],
        "action": action, "review_context": deepcopy(context.get("review_context"))}


def build_visual_field_proof(*, phase, focus_receipt, input_receipt, frame, assessment,
                             expected_field, context, value_reading=None, focus_snapshot=None, focus_observation=None):
    request = _request(phase=phase, focus_receipt=focus_receipt, input_receipt=input_receipt, frame=frame,
        expected_field=expected_field, context=context, value_reading=value_reading, focus_observation=focus_observation)
    if focus_snapshot is not None:
        if context.get("native_field_evidence", True) is False:
            raise ValueError("visual_field_native_evidence_disabled")
        request["action"]["focus_value_snapshot"] = _focus_snapshot_reference(focus_snapshot, request)
    result = deepcopy(assessment.get("judgment_result", assessment))
    if "request_budget_seconds" in result:
        request["request_budget_seconds"] = result["request_budget_seconds"]
    if (result.get("adopted") is not True or result.get("verdict") != "success"
            or result.get("status") != "completed" or result.get("disposition", "continue") != "continue"):
        _raise_field_review(context["service"], request, result, context, "visual_field_requires_review")
    if context["service"].validate_result(result, **request) is not True:
        raise ValueError("visual_field_proof_authentication_invalid")
    _deadline(context)
    return VisualFieldProof(_json({"request": request, "assessment": result}), context["service"],
        context["deadline_ns"], get_ident(), _ISSUER, _focus_snapshot=focus_snapshot, _cancelled=context.get("cancelled"),
        _capture_visibility_json=_known_visibility_json(
            focus_observation if focus_observation is not None else
                (input_receipt if phase == "value" else focus_receipt)["observation"]["capture"], request["action"]["field"]))


def assess_visual_field(*, phase, focus_receipt, input_receipt, frame, expected_field, context, value_reading=None,
                        focus_snapshot=None, focus_observation=None):
    kwargs = dict(phase=phase, focus_receipt=focus_receipt, input_receipt=input_receipt, frame=frame,
        expected_field=expected_field, context=context, value_reading=value_reading, focus_observation=focus_observation)
    request = _request(**kwargs)
    if focus_snapshot is not None:
        if context.get("native_field_evidence", True) is False:
            raise ValueError("visual_field_native_evidence_disabled")
        request["action"]["focus_value_snapshot"] = _focus_snapshot_reference(focus_snapshot, request)
    call = {key: value for key, value in request.items() if key != "mode"}
    assessment = _evaluate(context["service"], **call, deadline_ns=context["deadline_ns"])
    return build_visual_field_proof(**kwargs, assessment=assessment, focus_snapshot=focus_snapshot)


def _focus_snapshot_reference(snapshot, request):
    from app.agent.text_field_evidence import TextFieldSnapshot
    expected = request["action"]["field"]
    if type(snapshot) is not TextFieldSnapshot or request["action"]["field_phase"] != "focus":
        raise ValueError("visual_field_focus_snapshot_invalid")
    identity, bound = snapshot.identity, expected["window_identity"]
    point, current = expected["click_point"], identity.control_bbox
    if (snapshot.capture_id != request["frames"][-1]["capture_id"]
            or (identity.window_handle, identity.process_id, identity.process_create_time) != (
                bound["handle"], bound["process_id"], bound["process_create_time"])
            or identity.window_rect != tuple(expected["window_rect"])
            or not (current[0] <= point["x"] < current[0] + current[2]
                and current[1] <= point["y"] < current[1] + current[3])):
        raise ValueError("visual_field_focus_snapshot_binding_invalid")
    return snapshot.to_reference()


def read_visual_focus_snapshot(*, frame, expected_field, manager):
    from app.agent.windows_text_field_reader import TextFieldReadError
    normalized = decision_frame(frame, expected_field["window_identity"], role="after")
    try:
        return _read_bounded_text(normalized, expected_field, manager)
    except TextFieldReadError as error:
        if error.reason_code not in _UNAVAILABLE:
            raise
        return None


def assess_visual_selection(proof, *, frame, dispatch):
    from app.core.typing_dispatch import TypingDispatchReceipt
    previous = _checked_proof(proof)
    if type(dispatch) is not TypingDispatchReceipt:
        raise ValueError("visual_field_selection_dispatch_invalid")
    fact = dispatch.reference()
    if fact["selection_dispatch"] != "completed" or fact["text_dispatch"] != "not_started" or "selection_evidence" not in fact:
        raise ValueError("visual_field_selection_dispatch_invalid")
    request = deepcopy(previous["request"])
    request.pop("request_budget_seconds", None)
    request["request_id"] += "-selection"
    # 新视觉路线只核对替换内容；旧原生焦点条件保持原义。
    request["condition"] = (VISUAL_REPLACEMENT_READY_CONDITION
        if previous["request"]["condition"] == VISUAL_INPUT_READY_CONDITION else VISUAL_SELECTION_CONDITION)
    after = decision_frame(frame, request["action"]["field"]["window_identity"], role="after")
    _validate_png(after, request["action"]["field"])
    before = {**previous["request"]["frames"][-1], "role": "before"}
    request["frames"] = [before, after]
    if (after["capture_id"] == before["capture_id"]
            or Path(after["image_path"]).resolve() == Path(before["image_path"]).resolve()):
        raise ValueError("visual_field_selection_frame_not_fresh")
    request["action"].pop("field_content_check", None)
    request["action"].pop("field_content_ocr", None)
    request["action"].pop("target_identity", None)
    request["action"].pop("target_check", None)
    request["action"].update(focus_stage="after_selection", selection_dispatch=fact,
        prior_focus_request_sha256=previous["assessment"]["request_sha256"])
    assessment = _evaluate(proof._service, **{k: v for k, v in request.items() if k != "mode"}, deadline_ns=proof._deadline_ns)
    result = deepcopy(assessment.get("judgment_result", assessment))
    if "request_budget_seconds" in result:
        request["request_budget_seconds"] = result["request_budget_seconds"]
    if result.get("adopted") is not True or result.get("verdict") != "success" or result.get("disposition") != "continue":
        _raise_field_review(proof._service, request, result,
            {"deadline_ns": proof._deadline_ns, "cancelled": proof._cancelled}, "visual_field_selection_requires_review")
    if proof._service.validate_result(result, **request) is not True:
        raise ValueError("visual_field_selection_authentication_invalid")
    _deadline({"deadline_ns": proof._deadline_ns, "cancelled": proof._cancelled})
    return VisualFieldProof(_json({"request": request, "assessment": result}), proof._service,
        proof._deadline_ns, get_ident(), _ISSUER, _cancelled=proof._cancelled,
        _capture_visibility_json=_known_visibility_json(frame, request["action"]["field"]))


def verify_visual_selection(proof, manager, dispatch, reviewer, *, frame, native_snapshot=None):
    from app.agent.text_field_evidence import TextFieldSnapshot
    from app.agent.windows_text_field_reader import TextFieldReadError
    value = _checked_proof(proof)
    expected = value["request"]["action"]["field"]
    fresh = decision_frame(frame, expected["window_identity"], role="after")
    _validate_png(fresh, expected)
    before = proof._focus_snapshot
    if before is not None:
        if _focus_snapshot_reference(before, value["request"]) != value["request"]["action"].get("focus_value_snapshot"):
            raise ValueError("visual_field_selection_binding_invalid")
        try:
            current = native_snapshot if native_snapshot is not None else _read_bounded_text(fresh, expected, manager)
        except TextFieldReadError as error:
            if error.reason_code not in _UNAVAILABLE:
                raise
        else:
            if (type(current) is not TextFieldSnapshot or current.identity != before.identity or current.value != before.value
                    or current.source != before.source
                    or current.selection is not None and current.selection != (0, len(before.value))
                    or current.read_id == before.read_id or current.observed_at_ns <= before.observed_at_ns):
                raise ValueError("visual_field_selection_changed")
            _verify_window(expected, manager)
            _checked_proof(proof)
            # 原生双读确认空值时没有需要选中的字符，仍先核对同一字段、值与新快照。
            if current.selection is not None or current.value == "":
                return None
    if reviewer is None:
        raise ValueError("visual_field_fresh_proof_required")
    _verify_window(expected, manager)
    selected = reviewer(proof, fresh, dispatch)
    _checked_proof(proof)
    current = _checked_proof(selected)
    action = current["request"]["action"]
    if (selected._service is not proof._service or selected._deadline_ns != proof._deadline_ns
            or action.get("focus_stage") != "after_selection" or action.get("field") != expected
            or action.get("selection_dispatch") != dispatch.reference()
            or action.get("prior_focus_request_sha256") != value["assessment"]["request_sha256"]
            or selected._cancelled is not proof._cancelled
            or current["request"]["frames"] != [{**value["request"]["frames"][-1], "role": "before"}, fresh]
            or current["request"]["condition"] != (VISUAL_REPLACEMENT_READY_CONDITION
                if value["request"]["condition"] == VISUAL_INPUT_READY_CONDITION else VISUAL_SELECTION_CONDITION)):
        raise ValueError("visual_field_selection_binding_invalid")
    revalidate_visual_field(selected, manager)
    return selected


def _read_bounded_text(frame, expected, manager):
    from app.agent.native_identity import WindowsNativeIdentityReader
    from app.agent.windows_text_field_reader import WindowsTextFieldReader
    identity, point = expected["window_identity"], expected["click_point"]
    return WindowsTextFieldReader(window_manager=manager,
        native_identity_reader=WindowsNativeIdentityReader(window_manager=manager)).read_focused_at_point(
        target_field_id="visual-field", capture_id=frame["capture_id"], target_window_handle=identity["handle"],
        target_process_id=identity["process_id"], process_create_time=identity["process_create_time"],
        window_rect=tuple(expected["window_rect"]), click_point=(point["x"], point["y"]))


def _read_roi_text(frame, expected, context):
    from app.core.ocr_service import ocr_service
    engine_reused = ocr_service._rapid_engine is not None
    box = expected["bbox"]
    folder = Path(context["service"].session_dir) / "visual-field-proof"
    folder.mkdir(parents=True, exist_ok=True)
    crop = folder / (frame["sha256"] + "-" + _digest(box)[:16] + "-roi.png")
    with Image.open(frame["image_path"]) as image:
        image.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(crop)
    # 只调用维护的轻量引擎处理目标 ROI，不触发全窗扫描或其他引擎。
    try:
        raw = ocr_service._scan_with_rapidocr(crop)
    except Exception as error:
        raise ValueError("visual_field_roi_ocr_unavailable") from error
    matches = ocr_service._parse_matches(raw)
    if (len(matches) != 1 or type(matches[0].score) not in {int, float}
            or not isfinite(matches[0].score) or not .99 <= matches[0].score <= 1):
        raise ValueError("visual_field_roi_text_ambiguous")
    return matches[0].text, {"crop_sha256": sha256(crop.read_bytes()).hexdigest(),
        "score": matches[0].score, "engine": "rapidocr_onnxruntime", "engine_reused": engine_reused}


def _verify_read_window(expected, manager):
    from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
    from app.agent.windows_text_field_reader import TextFieldReadError
    identity = expected["window_identity"]
    current = validate_native_identity_fact(WindowsNativeIdentityReader(window_manager=manager).read_identity(identity["handle"]),
        target_window_handle=identity["handle"], expected_process_id=identity["process_id"])
    bound = manager.get_bound_window()
    if (current is None or current["process_create_time"] != identity["process_create_time"] or bound is None
            or expected["window_rect"] != [bound.rect.left, bound.rect.top, bound.rect.right - bound.rect.left,
                bound.rect.bottom - bound.rect.top]):
        raise TextFieldReadError("visual_field_read_window_changed")


def read_visual_value(*, frame, expected_field, context, manager):
    from app.agent.windows_text_field_reader import TextFieldReadError
    _deadline(context)
    normalized = decision_frame(frame, expected_field["window_identity"], role="after")
    started = perf_counter_ns()
    try:
        snapshot = _read_bounded_text(normalized, expected_field, manager)
        text, source, evidence = snapshot.value, snapshot.source, snapshot.to_reference()
    except TextFieldReadError as error:
        if error.reason_code not in _UNAVAILABLE:
            raise
        if context.get("ocr_enabled") is not True:
            raise TextFieldReadError("visual_field_value_unavailable") from error
        try:
            _verify_read_window(expected_field, manager)
            text, evidence = _read_roi_text(normalized, expected_field, context)
            _verify_read_window(expected_field, manager)
        except (OSError, ValueError, RuntimeError) as failure:
            raise TextFieldReadError("visual_field_value_unavailable") from failure
        source = "roi_ocr"
    if type(text) is not str or source not in {"uia_value", "uia_text", "roi_ocr"}:
        raise TextFieldReadError("visual_field_value_unavailable")
    _deadline(context)
    return VisualValueReading(_json({"text": text, "source": source, "frame_sha256": normalized["sha256"],
        "capture_id": normalized["capture_id"], "bbox": expected_field["bbox"],
        "elapsed_ms": (perf_counter_ns() - started) / 1_000_000, "evidence": evidence}), get_ident(), _ISSUER)


def capture_visual_field_frame(manager, context):
    from app.core.screenshot import ScreenshotService
    return ScreenshotService(window_manager=manager,
        capture_dir=Path(context["service"].session_dir) / "visual-field-proof" / "freshness").capture_window(
            focus_window=False, purpose="visual-field-freshness")


def _verify_focus_observation_window(manager, focus_receipt, expected):
    from app.agent.native_identity import (
        WindowsNativeIdentityReader, validate_native_identity_fact, normalize_windows_executable_path)
    identity = expected["window_identity"]
    fact = validate_native_identity_fact(WindowsNativeIdentityReader(window_manager=manager).read_identity(identity["handle"]),
        target_window_handle=identity["handle"], expected_process_id=identity["process_id"],
        expected_executable_path=normalize_windows_executable_path(focus_receipt["target_identity"].get("executable_path")))
    bound = manager.get_bound_window()
    if (fact is None or fact["process_create_time"] != identity["process_create_time"] or bound is None
            or bound.handle != identity["handle"] or bound.process_id != identity["process_id"]
            or getattr(bound, "is_active", None) is not True
            or expected["window_rect"] != [bound.rect.left, bound.rect.top,
                bound.rect.right-bound.rect.left, bound.rect.bottom-bound.rect.top]):
        raise ValueError("visual_focus_observation_window_changed")


def capture_visual_focus_observation(manager, context, *, focus_receipt, expected_field):
    """退役的只读采图辅助；执行输入不会调用，也不签发判断凭据。"""
    from app.core.screenshot import ScreenshotService
    delay = context.get("focus_observation_delay_ms")
    if context.get("native_field_evidence") is not False or type(delay) is not int or delay != 500:
        raise ValueError("visual_focus_observation_route_invalid")
    original = focus_receipt["observation"]["capture"]
    _request(phase="focus", focus_receipt=focus_receipt, input_receipt=None, frame=original,
        expected_field=expected_field, context=context, value_reading=None)
    _verify_focus_observation_window(manager, focus_receipt, expected_field)
    ready_at = perf_counter_ns() + delay * 1_000_000
    if _deadline(context) <= ready_at:
        raise ValueError("visual_field_deadline_expired")
    while perf_counter_ns() < ready_at:
        _deadline(context)
        sleep(max(0, min(.025, (ready_at-perf_counter_ns()) / 1_000_000_000)))
    _deadline(context)
    _verify_focus_observation_window(manager, focus_receipt, expected_field)
    captured = ScreenshotService(window_manager=manager,
        capture_dir=Path(context["service"].session_dir) / "visual-field-proof" / "focus-observation").capture_window(
            focus_window=False, purpose="visual-field-focus-observation")
    _deadline(context)
    _verify_focus_observation_window(manager, focus_receipt, expected_field)
    normalized = decision_frame(captured, expected_field["window_identity"], role="after")
    captured = {**captured, "capture_id": normalized["capture_id"], "sha256": normalized["sha256"],
        "window_identity": deepcopy(expected_field["window_identity"])}
    # 此辅助只返回观察图，不再签发可进入新输入链的双帧焦点判断。
    _validate_png(normalized, expected_field)
    before = decision_frame(original, expected_field["window_identity"], role="after")
    source = focus_receipt["capture"]
    rect = expected_field["window_rect"]
    if (captured.get("window_rect") != [rect[0], rect[1], rect[0]+rect[2], rect[1]+rect[3]]
            or normalized["capture_id"] in {before["capture_id"], source.get("capture_id")}
            or Path(normalized["image_path"]).resolve() in {
                Path(before["image_path"]).resolve(), Path(source["image_path"]).resolve()}):
        raise ValueError("visual_focus_observation_binding_invalid")
    _deadline(context)
    return captured


def _verify_window(expected, manager):
    if not require_local_operator_input(manager):
        raise ValueError("visual_field_original_input_scope_required")
    identity = _identity(current_local_operator_identity(manager))
    bound = manager.get_bound_window()
    if (identity != expected["window_identity"] or bound is None or bound.handle != identity["handle"]
            or bound.process_id != identity["process_id"] or expected["window_rect"] != [bound.rect.left,
                bound.rect.top, bound.rect.right - bound.rect.left, bound.rect.bottom - bound.rect.top]):
        raise ValueError("visual_field_window_binding_changed")
    return identity


def _native_reference(reference, expected, frame):
    from app.agent.text_field_evidence import TextFieldIdentity
    keys = {"contract_version", "identity", "capture_id", "read_id", "observed_at_ns",
        "source", "value_sha256", "value_length", "selection"}
    if type(reference) is not dict or set(reference) != keys:
        return None
    try:
        identity = reference["identity"]
        native = TextFieldIdentity(**{**identity, "runtime_id": tuple(identity["runtime_id"]),
            "window_rect": tuple(identity["window_rect"]), "control_bbox": tuple(identity["control_bbox"])})
        bound, point, box = expected["window_identity"], expected["click_point"], native.control_bbox
        length, digest, selection = reference["value_length"], reference["value_sha256"], reference["selection"]
        if (reference["contract_version"] != "text_field_snapshot_reference_v1"
                or reference["source"] not in {"uia_value", "uia_text"}
                or reference["capture_id"] != frame["capture_id"]
                or type(reference["read_id"]) is not str or not reference["read_id"]
                or type(reference["observed_at_ns"]) is not int or reference["observed_at_ns"] <= 0
                or (native.window_handle, native.process_id, native.process_create_time) != (
                    bound["handle"], bound["process_id"], bound["process_create_time"])
                or native.window_rect != tuple(expected["window_rect"])
                or not (box[0] <= point["x"] < box[0]+box[2] and box[1] <= point["y"] < box[1]+box[3])
                or type(length) is not int or not 0 <= length <= 32768
                or type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                or selection is not None and (type(selection) is not list or len(selection) != 2
                    or any(type(n) is not int for n in selection) or not 0 <= selection[0] <= selection[1] <= length)):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return deepcopy(reference)


def _native_baseline(proof, value):
    request, action = value["request"], value["request"]["action"]
    frame, expected = request["frames"][-1], action["field"]
    if "field_freshness_context" in action:
        reference = action["field_freshness_context"]["native_current_snapshot"]
    elif action["field_phase"] == "focus" and proof._focus_snapshot is not None:
        reference = _focus_snapshot_reference(proof._focus_snapshot, request)
        if reference != action.get("focus_value_snapshot"):
            raise ValueError("visual_field_native_binding_invalid")
    elif action["field_phase"] == "value":
        reading = action.get("value_reading") or {}
        reference = reading.get("evidence")
        if (reading.get("source") not in {"uia_value", "uia_text"} or type(reference) is not dict
                or reading.get("capture_id") != frame["capture_id"]
                or reading.get("frame_sha256") != frame["sha256"]
                or reference.get("source") != reading["source"]
                or reference.get("value_sha256") != sha256(expected["expected_text"].encode("utf-8")).hexdigest()
                or reference.get("value_length") != len(expected["expected_text"])):
            return None
    else:
        return None
    return _native_reference(reference, expected, frame)


def _check_native_current(current, baseline, expected, fresh, *, selection_pending=False):
    from app.agent.text_field_evidence import TextFieldSnapshot
    reference = _native_reference(current.to_reference(), expected, fresh) if type(current) is TextFieldSnapshot else None
    if (reference is None or any(reference[key] != baseline[key]
            for key in ("identity", "source", "value_sha256", "value_length"))
            or reference["read_id"] == baseline["read_id"]
            or reference["observed_at_ns"] <= baseline["observed_at_ns"]
            or not selection_pending and reference["selection"] != baseline["selection"]):
        raise ValueError("visual_field_native_changed")
    return reference


def _field_difference(original, fresh, expected):
    box = expected["bbox"]
    roi = (box["x"], box["y"], box["x"]+box["w"], box["y"]+box["h"])
    with Image.open(original["image_path"]) as before, Image.open(fresh["image_path"]) as after:
        channels = ImageChops.difference(before.convert("RGBA"), after.convert("RGBA")).split()
        difference = channels[0]
        for channel in channels[1:]:
            difference = ImageChops.lighter(difference, channel)
        changed = difference.crop(roi).getbbox()
    return ({"x": changed[0]+box["x"], "y": changed[1]+box["y"],
        "w": changed[2]-changed[0], "h": changed[3]-changed[1]} if changed else None)


def _field_visibility(capture, expected):
    from .target_freshness import _visibility, _overlap
    box = expected["bbox"]
    target = (box["x"], box["y"], box["x"]+box["w"], box["y"]+box["h"])
    if any(_overlap(mask, target) for mask in _visibility(capture, tuple(expected["window_rect"][2:]))):
        raise ValueError("visual_field_occluded")


def _known_visibility_json(capture, expected):
    """只冻结原采集明确提供的遮罩集合；缺失不能推断成无遮挡。"""
    from .target_freshness import _visibility
    if capture.get("capture_visibility") is None:
        return None
    try:
        return _json(_visibility(capture, tuple(expected["window_rect"][2:])))
    except ValueError:
        return None


def _native_bound_caret_change(original, fresh, changed, baseline):
    """完整原图只能差一个控件内部的单色细竖线；不是任意 ROI 变化豁免。"""
    selection = baseline["selection"]
    if (type(selection) is not list or len(selection) != 2 or selection[0] != selection[1]
            or changed is None or not 1 <= changed["w"] <= 2 or not 8 <= changed["h"] <= 40):
        return False
    x, y, w, h = (changed[key] for key in ("x", "y", "w", "h"))
    left, top, width, height = baseline["identity"]["control_bbox"]
    if not (left < x and top < y and x+w < left+width and y+h < top+height and h <= height):
        return False
    before_bytes, after_bytes = (Path(frame["image_path"]).read_bytes() for frame in (original, fresh))
    if any(sha256(data).hexdigest() != frame["sha256"]
            for data, frame in ((before_bytes, original), (after_bytes, fresh))):
        return False
    with Image.open(BytesIO(before_bytes)) as before, Image.open(BytesIO(after_bytes)) as after:
        if before.size != after.size:
            return False
        before, after = before.convert("RGBA"), after.convert("RGBA")
        channels = ImageChops.difference(before, after).split()
        difference = channels[0]
        for channel in channels[1:]:
            difference = ImageChops.lighter(difference, channel)
        roi = (x, y, x+w, y+h)
        if difference.getbbox() != roi:
            return False
        old, new = before.crop(roi).getcolors(1), after.crop(roi).getcolors(1)
        return (old is not None and new is not None and old[0][0] == new[0][0] == w*h
            and old[0][1][:3] != new[0][1][:3] and old[0][1][3] == new[0][1][3])


def _field_freshness_request(proof, *, frame, native_snapshot):
    previous = _checked_proof(proof)
    request = deepcopy(previous["request"])
    expected = request["action"]["field"]
    baseline = _native_baseline(proof, previous)
    if baseline is None or "field_freshness_context" in request["action"]:
        raise ValueError("visual_field_native_freshness_unavailable")
    after = decision_frame(frame, expected["window_identity"], role="after")
    _validate_png(after, expected)
    current = _check_native_current(native_snapshot, baseline, expected, after)
    changed = _field_difference(request["frames"][-1], after, expected)
    if changed is None:
        raise ValueError("visual_field_freshness_change_missing")
    request.pop("request_budget_seconds", None)
    request["request_id"] += "-freshness"
    request["condition"] = VISUAL_FIELD_FRESHNESS_CONDITION
    request["action"].pop("target_identity", None)
    request["action"].pop("target_check", None)
    request["frames"] = [{**request["frames"][-1], "role": "before"}, after]
    request["action"].update(focus_stage="before_keyboard_freshness", field_freshness_context={
        "schema": "visual_field_freshness.v1", "changed_region": changed,
        "original_condition": previous["request"]["condition"],
        "prior_request_sha256": previous["assessment"]["request_sha256"],
        "prior_assessment_sha256": _digest(previous["assessment"]),
        "native_before_snapshot": baseline, "native_current_snapshot": current})
    return request


def assess_visual_field_freshness(proof, *, frame, native_snapshot):
    request = _field_freshness_request(proof, frame=frame, native_snapshot=native_snapshot)
    assessment = _evaluate(proof._service, **{k: v for k, v in request.items() if k != "mode"}, deadline_ns=proof._deadline_ns)
    result = deepcopy(assessment.get("judgment_result", assessment))
    if "request_budget_seconds" in result:
        request["request_budget_seconds"] = result["request_budget_seconds"]
    if result.get("adopted") is not True or result.get("verdict") != "success" or result.get("disposition") != "continue":
        _raise_field_review(proof._service, request, result,
            {"deadline_ns": proof._deadline_ns, "cancelled": proof._cancelled}, "visual_field_freshness_requires_review")
    if proof._service.validate_result(result, **request) is not True:
        raise ValueError("visual_field_freshness_authentication_invalid")
    _checked_proof(proof)
    return VisualFieldProof(_json({"request": request, "assessment": result}), proof._service,
        proof._deadline_ns, get_ident(), _ISSUER, _cancelled=proof._cancelled,
        _capture_visibility_json=_known_visibility_json(frame, request["action"]["field"]))


def verify_visual_field_freshness(proof, reviewed, manager, *, frame, native_snapshot):
    current = _checked_proof(reviewed)
    expected = _field_freshness_request(proof, frame=frame, native_snapshot=native_snapshot)
    actual = {key: value for key, value in current["request"].items() if key != "request_budget_seconds"}
    if (reviewed._service is not proof._service or reviewed._deadline_ns != proof._deadline_ns
            or reviewed._cancelled is not proof._cancelled or actual != expected):
        raise ValueError("visual_field_freshness_binding_invalid")
    revalidate_visual_field(reviewed, manager)
    return reviewed


def revalidate_visual_field(proof, manager, *, selection_pending=False):
    value = _checked_proof(proof)
    expected = value["request"]["action"]["field"]
    identity = _verify_window(expected, manager)
    baseline = _native_baseline(proof, value)
    # 已认证语义不因像素表现重复否决；仅原生事实或真实选区变化需要新采集。
    if baseline is None and not selection_pending:
        _checked_proof(proof)
        return deepcopy(value["request"]["frames"][-1])
    current = capture_visual_field_frame(manager, {"service": proof._service})
    fresh = decision_frame(current, identity, role="after")
    _validate_png(fresh, expected)
    native = None
    if baseline is not None:
        native = _read_bounded_text(fresh, expected, manager)
        _check_native_current(native, baseline, expected, fresh, selection_pending=selection_pending)
    if _verify_window(expected, manager) != identity:
        raise ValueError("visual_field_window_binding_changed")
    _checked_proof(proof)
    if selection_pending:
        raise VisualFieldChanged(fresh, native_snapshot=native)
    return fresh
