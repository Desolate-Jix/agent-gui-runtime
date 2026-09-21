"""首次字段读取使用真实识别协议和既有只读 UIA 读取器。"""

from hashlib import sha256
from collections.abc import Mapping
import time

from .text_field_evidence import TextFieldSnapshot
from .windows_text_field_reader import WindowsTextFieldReader


def _require_process_binding(owner, application):
    from .fresh_learning_observation import FreshLearningObservationError
    from .fresh_learning_runtime_source import _application_identity_from_evidence

    if (application.get('kind') != owner.application.get('kind')
            or 'process_create_time' not in application or 'executable_path' not in application
            or _application_identity_from_evidence({'application': application}) != owner.application):
        raise FreshLearningObservationError("fresh text field requires native process binding and matching application")


def _normalized_control_type(value):
    return " ".join(str(value or "").split()).casefold()


def _field_uia_identity(snapshot, point):
    """从一次 UIA 快照提取唯一当前字段的真实元素身份。"""
    from app.gate.fresh_action_risk import _editable_text_controls

    controls = snapshot.get("controls")
    if not isinstance(controls, list):
        raise ValueError("fresh text field UIA controls are invalid")
    editable, reason = _editable_text_controls(controls, point)
    if reason is not None or len(editable) != 1:
        raise ValueError("fresh text field current geometry is ambiguous")
    projected = editable[0]
    matches = [raw for raw in controls if isinstance(raw, Mapping)
               and raw.get("control_id") == projected["control_id"]
               and raw.get("bbox") == projected["bbox"]
               and _normalized_control_type(raw.get("control_type")) ==
                   _normalized_control_type(projected["role"])]
    if len(matches) != 1:
        raise ValueError("fresh text field UIA element identity is ambiguous")
    raw = matches[0]
    runtime_id = raw.get("runtime_id")
    if (not isinstance(runtime_id, (list, tuple)) or not 1 <= len(runtime_id) <= 64
            or any(type(item) is not int for item in runtime_id)):
        raise ValueError("fresh text field UIA runtime identity is unavailable")
    runtime_id = tuple(runtime_id)
    same_runtime = []
    for candidate in controls:
        if not isinstance(candidate, Mapping):
            continue
        candidate_runtime = candidate.get("runtime_id")
        if (isinstance(candidate_runtime, (list, tuple))
                and 1 <= len(candidate_runtime) <= 64
                and all(type(item) is int for item in candidate_runtime)
                and tuple(candidate_runtime) == runtime_id):
            same_runtime.append(candidate)
    if len(same_runtime) != 1 or same_runtime[0] is not raw:
        raise ValueError("fresh text field UIA runtime identity is ambiguous")
    control_type = _normalized_control_type(raw.get("control_type"))
    if control_type not in {"edit", "document", "combobox", "combo box"}:
        raise ValueError("fresh text field UIA control type is invalid")
    return {
        "runtime_id": runtime_id,
        "control_type": control_type,
        "bbox": dict(projected["bbox"]),
    }


def read_fresh_text_field_after(owner, *, packet, expectation):
    from .fresh_learning_observation import FreshLearningObservationError

    try:
        return _read_after(owner, packet, expectation)
    except FreshLearningObservationError:
        raise
    except Exception:
        raise FreshLearningObservationError("fresh text field post-read is unavailable") from None


def _read_after(owner, packet, expectation):
    from .fresh_learning_observation import (
        FreshLearningObservationPacket, FreshLearningObservationError, _bound_rect, _public_application,
        _require_uia_rect,
    )
    from .text_field_evidence import TextFieldExpectation, same_text_field_instance
    from .live_runtime_composition import _bound_identity, _validated_uia_snapshot

    if type(packet) is not FreshLearningObservationPacket or type(expectation) is not TextFieldExpectation:
        raise FreshLearningObservationError("fresh post-read requires an owned field expectation and capture")
    evidence = packet.evidence()
    capture, target, application = evidence['capture'], evidence['target'], evidence['application']
    _require_process_binding(owner, application)
    before = expectation.before
    identity = before.identity
    rect = target['rect']
    viewport = capture['viewport_size']
    if (sha256(packet.png_bytes).hexdigest() != capture['screenshot_sha256']
            or capture['capture_id'] == before.capture_id
            or capture['capture_started_ns'] <= before.observed_at_ns
            or capture['capture_clock_id'] != 'windows-perf-counter-v1'
            or target['window_handle'] != identity.window_handle or target['process_id'] != identity.process_id
            or application['process_create_time'] != identity.process_create_time
            or tuple(rect[key] for key in ('x', 'y', 'width', 'height')) != identity.window_rect
            or (viewport['width'], viewport['height']) != identity.window_rect[2:]):
        raise FreshLearningObservationError("fresh text post-read capture differs from the bound field")

    def verify_binding():
        bound = owner._window_manager.get_bound_window()
        if (_bound_identity(bound, target_window_handle=identity.window_handle) != (
                identity.window_handle, identity.process_id, identity.window_rect[2:])
                or _bound_rect(bound) != rect
                or _public_application(owner.application,
                    owner._read_application_fact(identity.window_handle, identity.process_id)) != application):
            raise FreshLearningObservationError("fresh text post-read native binding changed")

    verify_binding()
    if owner._text_field_reader is None:
        owner._text_field_reader = WindowsTextFieldReader(window_manager=owner._window_manager,
            native_identity_reader=owner._native_identity_reader)
    def current_identity():
        bound = owner._window_manager.get_bound_window()
        uia = _validated_uia_snapshot(owner._uia_provider.snapshot_window(bound),
            expected_identity=(identity.window_handle, identity.process_id, identity.window_rect[2:]))
        _require_uia_rect(uia, rect)
        # 填写可引起布局变化；只读寻回必须先匹配唯一实例，不能重用旧坐标猜字段。
        matches = [control for control in uia['controls'] if isinstance(control, Mapping)
            and isinstance(control.get('runtime_id'), (list, tuple))
            and all(type(item) is int for item in control['runtime_id'])
            and tuple(control['runtime_id']) == identity.runtime_id]
        if len(matches) != 1:
            raise FreshLearningObservationError("fresh text post-read current field identity changed")
        bbox = matches[0].get('bbox')
        if (not isinstance(bbox, Mapping) or set(bbox) != {'x', 'y', 'w', 'h'}
                or any(type(bbox[key]) is not int for key in bbox)
                or min(bbox['x'], bbox['y']) < 0 or min(bbox['w'], bbox['h']) <= 0
                or bbox['x'] + bbox['w'] > viewport['width']
                or bbox['y'] + bbox['h'] > viewport['height']):
            raise FreshLearningObservationError("fresh text post-read current field geometry is invalid")
        current = _field_uia_identity(uia, {
            'x': bbox['x'] + bbox['w'] // 2, 'y': bbox['y'] + bbox['h'] // 2})
        if current['runtime_id'] != identity.runtime_id:
            raise FreshLearningObservationError("fresh text post-read current field identity changed")
        return current

    captured_identity = current_identity()
    current_bbox = tuple(captured_identity['bbox'][key] for key in ('x', 'y', 'w', 'h'))
    x, y, width, height = current_bbox
    point = {'x': x + width // 2, 'y': y + height // 2}
    started = time.perf_counter_ns()
    # 此坐标仅用于只读寻回；实际 UIA 身份仍须与填写前一致，绝不从这里派发输入。
    actual = owner._text_field_reader.read_field(target_field_id=identity.target_field_id,
        capture_id=capture['capture_id'], target_window_handle=identity.window_handle,
        target_process_id=identity.process_id, process_create_time=identity.process_create_time,
        window_rect=identity.window_rect, target_bbox=current_bbox,
        click_point=(point['x'], point['y']), require_keyboard_focus=False,
        expected_runtime_id=captured_identity['runtime_id'],
        expected_control_type=captured_identity['control_type'])
    verify_binding()
    if current_identity() != captured_identity:
        raise FreshLearningObservationError("fresh text post-read current field identity changed")
    if (type(actual) is not TextFieldSnapshot or not same_text_field_instance(actual.identity, identity)
            or actual.identity.control_bbox != current_bbox
            or actual.capture_id != capture['capture_id']
            or actual.observed_at_ns < max(started, capture['observed_at_ns'])):
        raise FreshLearningObservationError("fresh text post-read returned stale evidence")
    return actual


def read_fresh_text_field(owner, *, bundle, target_field_id, decision, require_keyboard_focus=False,
                          automatic_safety_interception=True):
    from .fresh_learning_observation import FreshLearningObservationError

    try:
        return _read(owner, bundle, target_field_id, decision, require_keyboard_focus, automatic_safety_interception)
    except FreshLearningObservationError:
        raise
    except Exception:
        # 供应方异常可能含原文；此只读边界只报告可操作的失败类型。
        raise FreshLearningObservationError("fresh text field evidence or provider is unavailable") from None


def _read(owner, bundle, target_field_id, decision, require_keyboard_focus, automatic_safety_interception=True):
    from .fresh_learning_observation import (
        FreshLearningActionObservation, FreshLearningObservationError,
        _bound_rect, _public_application, _require_uia_rect,
    )
    from .fresh_learning_action_contracts import payload_sha256
    from .fresh_learning_action_preview import _parse_projected_recognition
    from .live_runtime_composition import _bound_identity, _parse_recognition, _validated_uia_snapshot
    from app.operation.recognition.decision import decide_pre_click
    from app.gate.fresh_action_risk import classify_fresh_action_risk, _editable_text_controls
    from .automatic_safety_policy import action_selection, validate_automatic_safety_interception
    strict = validate_automatic_safety_interception(automatic_safety_interception)

    def reject(reason):
        raise FreshLearningObservationError(reason)

    if (type(bundle) is not FreshLearningActionObservation or not isinstance(decision, Mapping)
            or type(require_keyboard_focus) is not bool or not isinstance(target_field_id, str)
            or not target_field_id.strip() or len(target_field_id) > 256):
        reject("fresh text field request is invalid")
    evidence = bundle.packet.evidence()
    capture, target, application = evidence['capture'], evidence['target'], evidence['application']
    _require_process_binding(owner, application)
    if (sha256(bundle.packet.png_bytes).hexdigest() != capture['screenshot_sha256']
            or sha256(bundle.recognition_json).hexdigest() != evidence['recognition']['result_sha256']):
        reject("fresh text field capture or recognition digest mismatch")
    window, pid = target['window_handle'], target['process_id']
    viewport = capture['viewport_size']
    rect = target['rect']
    expected_identity = (window, pid, (viewport['width'], viewport['height']))
    if rect['width'] != viewport['width'] or rect['height'] != viewport['height']:
        reject("fresh text field viewport differs from target")

    def verify_owner_binding():
        bound = owner._window_manager.get_bound_window()
        if (_bound_identity(bound, target_window_handle=window) != expected_identity
                or _bound_rect(bound) != rect
                or _public_application(owner.application, owner._read_application_fact(window, pid)) != application):
            reject("fresh text field native binding changed")

    verify_owner_binding()
    uia = _validated_uia_snapshot(bundle.uia_snapshot(), expected_identity=expected_identity)
    _require_uia_rect(uia, rect)
    if payload_sha256(uia) != evidence['uia']['snapshot_sha256']:
        reject("fresh text field UIA digest mismatch")
    candidates, grounding = _parse_recognition(bundle.recognition_result())
    projection = _parse_projected_recognition(evidence['recognition']['result'])
    for local in grounding.results:
        local.crop_path = None
    if ((candidates, grounding) != projection or candidates.goal != grounding.goal
            or candidates.goal != evidence['recognition']['goal']):
        reject("fresh text field recognition projection mismatch")
    current = decide_pre_click(goal=candidates.goal, candidates=candidates, grounding=grounding).to_dict()
    if dict(decision) != current or strict and current.get('allowed') is not True:
        reject("fresh pre-click decision differs from current evidence")
    current = action_selection(current, candidates, grounding, automatic_safety_interception=strict)
    selected = current['selected_candidate_id']
    chosen = [item for item in candidates.candidates if item.candidate_id == selected]
    locals_ = [item for item in grounding.results if item.candidate_id == selected]
    if len(chosen) != 1 or len(locals_) != 1:
        reject("fresh text field candidate is ambiguous")
    candidate, local = chosen[0], locals_[0]
    from .fresh_learning_action_preview import _validate_editable_ocr_bindings
    _validate_editable_ocr_bindings(candidates, grounding, uia, capture['screenshot_sha256'],
                                  goal=candidates.goal, semantic_action='fill_field', observation_evidence=evidence)
    risk = classify_fresh_action_risk(proposed_semantic_action='fill_field', goal=candidates.goal,
        candidate=candidate, local=local, capture_id=capture['capture_id'], uia_snapshot=uia)
    if risk['hard_blocked'] is not False and (strict or risk['risk_class'] in {'unresolved', 'unsupported'}):
        reject("fresh text field target risk is blocked")
    editable, reason = _editable_text_controls(uia['controls'], current['selected_click_point'])
    if reason is not None or len(editable) != 1:
        reject("fresh text field current geometry is ambiguous")
    # 模型点框不是字段边界；只读复核使用本次 UIA 中唯一字段的真实矩形。
    bbox_map = editable[0]['bbox']
    bbox = tuple(bbox_map[key] for key in ('x', 'y', 'w', 'h'))
    point = tuple(current['selected_click_point'][key] for key in ('x', 'y'))
    if (any(type(number) is not int for number in (*bbox, *point))
            or bbox[0] < 0 or bbox[1] < 0 or bbox[0] + bbox[2] > viewport['width']
            or bbox[1] + bbox[3] > viewport['height']):
        reject("fresh text field candidate is outside capture")
    try:
        captured_field_identity = _field_uia_identity(
            uia, {"x": point[0], "y": point[1]},
        )
    except ValueError:
        reject("fresh text field UIA element identity is unavailable")

    def verify_current_field_identity():
        bound = owner._window_manager.get_bound_window()
        if (_bound_identity(bound, target_window_handle=window) != expected_identity
                or _bound_rect(bound) != rect):
            reject("fresh text field native binding changed")
        try:
            current_uia = _validated_uia_snapshot(
                owner._uia_provider.snapshot_window(bound), expected_identity=expected_identity,
            )
            _require_uia_rect(current_uia, rect)
            current_field_identity = _field_uia_identity(
                current_uia, {"x": point[0], "y": point[1]},
            )
        except (TypeError, ValueError):
            reject("fresh text field current UIA element identity is unavailable")
        if current_field_identity != captured_field_identity:
            reject("fresh text field current UIA element identity changed")

    if owner._text_field_reader is None:
        owner._text_field_reader = WindowsTextFieldReader(window_manager=owner._window_manager,
            native_identity_reader=owner._native_identity_reader)
    verify_current_field_identity()
    started = time.perf_counter_ns()
    window_rect = tuple(rect[key] for key in ('x', 'y', 'width', 'height'))
    actual = owner._text_field_reader.read_field(target_field_id=target_field_id,
        capture_id=capture['capture_id'], target_window_handle=window, target_process_id=pid,
        process_create_time=application['process_create_time'], window_rect=window_rect,
        target_bbox=bbox, click_point=point, require_keyboard_focus=require_keyboard_focus,
        expected_runtime_id=captured_field_identity['runtime_id'],
        expected_control_type=captured_field_identity['control_type'])
    verify_owner_binding()
    verify_current_field_identity()
    if (type(actual) is not TextFieldSnapshot or actual.capture_id != capture['capture_id']
            or actual.observed_at_ns < max(started, capture['observed_at_ns'])
            or actual.identity.target_field_id != target_field_id
            or actual.identity.window_handle != window or actual.identity.process_id != pid
            or actual.identity.process_create_time != application['process_create_time']
            or actual.identity.runtime_id != captured_field_identity['runtime_id']
            or actual.identity.window_rect != window_rect
            or actual.identity.control_bbox != bbox):
        reject("fresh text field result differs from capture binding")
    x, y, width, height = actual.identity.control_bbox
    if not (x <= point[0] < x + width and y <= point[1] < y + height):
        reject("fresh text field result does not contain selected point")
    return actual
