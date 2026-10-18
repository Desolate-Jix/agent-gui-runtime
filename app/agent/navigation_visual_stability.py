"""仅证明已批准低风险导航控件的局部像素稳定，不签发动作权限。"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from typing import Any, Mapping
from weakref import WeakKeyDictionary

from PIL import Image, ImageChops

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.fresh_learning_action_preview import (
    CONTROL_TARGET_CONTRACT_VERSION,
    FreshLearningActionPreview,
    _decision_and_risk,
    _parse_projected_recognition,
)
from app.agent.learned_control_reference import recognition_target_from_learned_control
from app.agent.text_visual_stability import (
    TextVisualPixelsChanged,
    _bounded_background_delta,
    _canonical_bytes,
    _digest,
    _load_bound_png,
    _pixel_sha256,
    _protected_bbox,
    _sha_value,
    _stable_evidence,
    _xywh_to_box,
)
from app.operation.recognition.control_target import control_target_matches, uia_control_matches
from app.agent.automatic_safety_policy import (
    MODE_PREVIEW_VERSION, action_selection, preview_automatic_safety_interception,
    validate_automatic_safety_interception,
)


_POLICY = "open_detail_protected_pixels_v1"
_FLAGS = {"artifact_is_authorization", "execute_binding_enabled", "action_executed"}
_SEAL = object()
_ISSUED: WeakKeyDictionary = WeakKeyDictionary()
_SCOPES: WeakKeyDictionary = WeakKeyDictionary()


class NavigationVisualPixelsChanged(ValueError):
    """身份和图像完整性有效，但变化超出导航局部像素策略。"""


class NavigationVisualStabilityAttestation:
    """只接受本进程局部像素校验签发的不可变证明。"""

    __slots__ = ("_reference_json", "_sealed", "__weakref__")

    def __init__(self, *args, **kwargs) -> None:
        raise TypeError("navigation visual stability attestation cannot be constructed directly")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("navigation visual stability attestation is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("navigation visual stability attestation is immutable")

    def _require_sealed(self) -> None:
        if (type(self) is not NavigationVisualStabilityAttestation
                or getattr(self, "_sealed", None) is not _SEAL
                or _ISSUED.get(self) != getattr(self, "_reference_json", None)):
            raise TypeError("navigation visual stability attestation is not trusted")

    def to_reference(self) -> dict[str, Any]:
        self._require_sealed()
        return json.loads(self._reference_json.decode("utf-8"))

    def validate_binding(
        self,
        before_evidence: Mapping[str, Any],
        after_evidence: Mapping[str, Any],
        expectation_reference: Mapping[str, Any],
    ) -> None:
        reference = self.to_reference()
        if _digest(_full_evidence(before_evidence)) != reference["before_evidence_sha256"]:
            raise ValueError("navigation visual stability original evidence binding changed")
        if _digest(_full_evidence(after_evidence)) != reference["after_evidence_sha256"]:
            raise ValueError("navigation visual stability current evidence binding changed")
        if not isinstance(expectation_reference, Mapping):
            raise TypeError("navigation visual stability expectation must be a mapping")
        if _digest(dict(expectation_reference)) != reference["navigation_expectation_sha256"]:
            raise ValueError("navigation visual stability expectation binding changed")


def navigation_visual_expectation(approved_preview: FreshLearningActionPreview) -> dict[str, Any]:
    """从严格预览派生当前控件绑定；首次学习不冒充已学习引用。"""
    if type(approved_preview) is not FreshLearningActionPreview:
        raise TypeError("navigation visual stability requires a typed approved preview")
    data = FreshLearningActionPreview.from_dict(approved_preview.to_dict()).to_dict()
    first_learning = (data["contract_version"] == "fresh_learning_action_preview_v1"
                      and FreshLearningIntent.from_dict(data["intent"]).learned_control is None)
    if not first_learning and data["contract_version"] not in {CONTROL_TARGET_CONTRACT_VERSION, MODE_PREVIEW_VERSION}:
        raise ValueError("navigation visual stability requires a v2 control-target or v1 first-learning preview")
    return _expectation_from_parts(
        data["preview_sha256"], data["intent"],
        _full_evidence(data["observation_evidence"]), data["uia_snapshot"],
        automatic_safety_interception=preview_automatic_safety_interception(data),
    )


class NavigationVisualStabilityScope:
    """始终固定对照批准原帧，不将后续帧推进为新基线。"""

    __slots__ = ("_expectation_json", "_original_evidence_json", "_original_png_bytes", "__weakref__")

    def __init__(
        self,
        approved_preview: FreshLearningActionPreview,
        original_png_bytes: bytes,
    ) -> None:
        expectation = navigation_visual_expectation(approved_preview)
        original = _full_evidence(approved_preview.to_dict()["observation_evidence"])
        if type(original_png_bytes) is not bytes:
            raise TypeError("navigation visual stability requires immutable original PNG bytes")
        _load_navigation_png(original_png_bytes, original)
        object.__setattr__(self, "_expectation_json", _canonical_bytes(expectation))
        object.__setattr__(self, "_original_evidence_json", _canonical_bytes(original))
        object.__setattr__(self, "_original_png_bytes", original_png_bytes)
        _SCOPES[self] = (self._expectation_json, self._original_evidence_json, self._original_png_bytes)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("navigation visual stability scope is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("navigation visual stability scope is immutable")

    @property
    def expectation_reference(self) -> dict[str, Any]:
        expectation, _ = self._revalidate_original()
        return expectation

    def validate(
        self,
        current_evidence: Mapping[str, Any],
        current_png_bytes: bytes,
        current_uia_snapshot=None,
    ) -> NavigationVisualStabilityAttestation:
        expectation, original = self._revalidate_original()
        reference = _recomputed_reference(
            expectation, original, _full_evidence(current_evidence),
            self._original_png_bytes, current_png_bytes,
            current_uia_snapshot=current_uia_snapshot,
        )
        proof = object.__new__(NavigationVisualStabilityAttestation)
        raw = _canonical_bytes(reference)
        object.__setattr__(proof, "_reference_json", raw)
        object.__setattr__(proof, "_sealed", _SEAL)
        # 独立签发登记可拒绝 object.__new__ 伪造及绕过常规赋值的修改。
        _ISSUED[proof] = raw
        return proof

    def _revalidate_original(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if (type(self) is not NavigationVisualStabilityScope or _SCOPES.get(self) != (
                getattr(self, "_expectation_json", None), getattr(self, "_original_evidence_json", None),
                getattr(self, "_original_png_bytes", None))):
            raise TypeError("navigation visual stability scope is not trusted")
        original = _full_evidence(json.loads(self._original_evidence_json.decode("utf-8")))
        expectation = _verified_expectation(
            json.loads(self._expectation_json.decode("utf-8")), original,
        )
        _load_navigation_png(self._original_png_bytes, original)
        return expectation, original


def verify_navigation_visual_stability_reference(
    reference: Mapping[str, Any],
    original_evidence: Mapping[str, Any],
    current_evidence: Mapping[str, Any],
    expectation_reference: Mapping[str, Any],
    original_png_bytes: bytes,
    current_png_bytes: bytes,
) -> None:
    """只读重算封存引用，绝不恢复本进程可用于动作校验的密封对象。"""
    if not isinstance(reference, Mapping):
        raise TypeError("navigation visual stability reference must be a mapping")
    original = _full_evidence(original_evidence)
    expected = _recomputed_reference(
        _verified_expectation(expectation_reference, original), original,
        _full_evidence(current_evidence), original_png_bytes, current_png_bytes,
        current_uia_snapshot=reference.get('current_uia_snapshot'),
    )
    if _canonical_bytes(dict(reference)) != _canonical_bytes(expected):
        raise ValueError("navigation visual stability reference differs from recomputed proof")


def _full_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    _stable_evidence(value)
    data = json.loads(_canonical_bytes(dict(value)).decode("utf-8"))
    if (set(data) != {"contract_version", "target", "application", "uia", "capture", "recognition", *_FLAGS}
            or data["contract_version"] != "fresh_learning_observation_v1"
            or any(data[key] is not False for key in _FLAGS)):
        raise ValueError("navigation visual stability full observation evidence is invalid")
    capture = data["capture"]
    if (any(type(capture.get(key)) is not int for key in ("captured_at_ns", "observed_at_ns"))
            or not capture["capture_started_ns"] <= capture["captured_at_ns"] <= capture["observed_at_ns"]):
        raise ValueError("navigation visual stability capture chronology is invalid")
    recognition = data["recognition"]
    if (not isinstance(recognition, dict)
            or set(recognition) != {"status", "goal", "result_sha256", "result_projection_contract", "result_is_original", "result"}
            or recognition["result_projection_contract"] != "fresh_read_only_recognition_projection_v1"
            or recognition["result_is_original"] is not False):
        raise ValueError("navigation visual stability recognition provenance is invalid")
    if recognition["status"] == "not_requested":
        if any(recognition[key] is not None for key in ("goal", "result_sha256", "result")):
            raise ValueError("navigation visual stability passive capture contains recognition")
    elif recognition["status"] == "completed":
        _sha_value(recognition["result_sha256"], "recognition")
        if not isinstance(recognition["goal"], str) or not isinstance(recognition["result"], dict):
            raise ValueError("navigation visual stability completed recognition is invalid")
    else:
        raise ValueError("navigation visual stability recognition status is unsupported")
    return data


def _expectation_from_parts(preview_sha, intent_value, original, uia, *, automatic_safety_interception=True) -> dict[str, Any]:
    _sha_value(preview_sha, "approved preview")
    intent = FreshLearningIntent.from_dict(intent_value)
    strict = validate_automatic_safety_interception(automatic_safety_interception)
    if strict and intent.semantic_action != "open_detail":
        raise ValueError("navigation visual stability requires open_detail navigation")
    target = (_selected_target(original, uia, intent) if strict
              else _manual_selected_target(original, uia, intent))
    return json.loads(_canonical_bytes({
        "contract_version": "navigation_visual_expectation_v1" if strict else "navigation_visual_expectation_v2",
        **({} if strict else {'automatic_safety_interception': False}),
        "approved_preview_sha256": preview_sha,
        "intent": intent.to_dict(),
        "original_evidence_sha256": _digest(original),
        "uia_snapshot": uia,
        "selected_target": target,
    }).decode("utf-8"))


def _verified_expectation(value, original) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("navigation visual stability expectation must be a mapping")
    try:
        result = _expectation_from_parts(
            value["approved_preview_sha256"], value["intent"], original, value["uia_snapshot"],
            automatic_safety_interception=value.get('automatic_safety_interception', True),
        )
    except (KeyError, TypeError) as error:
        raise ValueError("navigation visual stability expectation reference is invalid") from error
    if _canonical_bytes(dict(value)) != _canonical_bytes(result):
        raise ValueError("navigation visual stability expectation differs from original evidence")
    return result


def _selected_target(evidence, uia, intent, *, automatic_safety_interception=True) -> dict[str, Any]:
    from app.gate.fresh_action_risk import _actionable, _contains
    from app.operation.recognition.control_target import control_target_ocr_matches
    from app.operation.recognition.control_corroboration import has_current_control_ocr_binding
    from app.operation.recognition.native_control_hit_binding import has_current_native_control_hit

    target = recognition_target_from_learned_control(intent.learned_control, semantic_action="open_detail")
    strict = validate_automatic_safety_interception(automatic_safety_interception)
    raw_decision, risk = _decision_and_risk(evidence, uia, intent,
        require_control_target=intent.learned_control is not None,
        automatic_safety_interception=strict)
    if strict and (risk["risk_class"] != "low_risk_navigation" or risk["hard_blocked"] is not False):
        raise ValueError("navigation visual stability target is not low-risk navigation")
    _validate_uia(uia, evidence)
    candidates, local = _parse_projected_recognition(evidence["recognition"]["result"])
    decision = action_selection(raw_decision, candidates, local, automatic_safety_interception=strict)
    if target is None:
        # 当前目标来自重新计算的原 Gate，不允许调用方用标签自授学习引用。
        selected = [item for item in candidates.candidates if item.candidate_id == decision["selected_candidate_id"]]
        if len(selected) != 1:
            raise ValueError("navigation visual stability selected candidate is not unique")
        target = {"label": selected[0].label, "role": selected[0].role}
    if target["role"] not in {"button", "link"}:
        raise ValueError("navigation visual stability only supports buttons or links")
    matches = [candidate for candidate in candidates.candidates
        if any(control_target_matches(label, candidate.role, target)
               for label in (candidate.label, candidate.text, candidate.element.label, candidate.element.text))]
    if len(matches) != 1 or matches[0].candidate_id != decision["selected_candidate_id"]:
        raise ValueError("navigation visual stability candidate is not unique")
    candidate = matches[0]
    grounded = [item for item in local.results if item.candidate_id == candidate.candidate_id]
    if len(grounded) != 1:
        raise ValueError("navigation visual stability grounding is not unique")
    grounded = grounded[0]
    if (candidate.role != target["role"] or candidate.element.role != target["role"]
            or any(not control_target_matches(label, target["role"], target)
                   for label in (candidate.label, candidate.text, candidate.element.label,
                                 candidate.element.text))
            or not (control_target_ocr_matches(grounded.matched_text, candidate.role, target,
                                               candidate_label=candidate.label)
                    or has_current_control_ocr_binding(candidate, grounded, uia,
                        evidence['capture']['screenshot_sha256'])
                    or has_current_native_control_hit(candidate, grounded, uia,
                        evidence['capture']['screenshot_sha256']))):
        raise ValueError("navigation visual stability label or role differs from pinned control")
    point = decision["selected_click_point"]
    controls = [control for control in uia["controls"] if uia_control_matches(control, target)
                and _actionable(control) and control.get("enabled") is True and control.get("visible") is True
                and _contains(control["bbox"], point)]
    if len(controls) != 1:
        raise ValueError("navigation visual stability UIA target is not unique")
    control = controls[0]
    runtime_id = control.get("runtime_id")
    control_id = control.get("control_id")
    if (control.get("provider") != "windows_uia" or control.get("enabled") is not True
            or control.get("visible") is not True or not isinstance(control_id, str) or not control_id
            or type(runtime_id) is not list or not 1 <= len(runtime_id) <= 64
            or any(type(item) is not int for item in runtime_id)
            or sum(item.get("runtime_id") == runtime_id for item in uia["controls"]) != 1
            or sum(item.get("control_id") == control_id for item in uia["controls"]) != 1):
        raise ValueError("navigation visual stability requires unique real UIA runtime identity")
    viewport = evidence["capture"]["viewport_size"]
    element_bbox = _box(candidate.element.bbox.to_dict(), viewport)
    candidate_bbox = _box(candidate.refined_bbox or candidate.element.bbox.to_dict(), viewport)
    control_bbox = _box(control["bbox"], viewport)
    rect = evidence["target"]["rect"]
    screen_bbox = control.get("screen_bbox")
    if (not isinstance(screen_bbox, dict)
            or any(type(value) is not int for value in screen_bbox.values())
            or screen_bbox != {
            "x": control_bbox[0] + rect["x"], "y": control_bbox[1] + rect["y"],
            "w": control_bbox[2], "h": control_bbox[3]}):
        raise ValueError("navigation visual stability UIA screen geometry differs from bound window")
    point = decision["selected_click_point"]
    if (not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(number) is not int for number in point.values())
            or any(not (box[0] <= point["x"] < box[0] + box[2]
                        and box[1] <= point["y"] < box[1] + box[3])
                   for box in (element_bbox, candidate_bbox, control_bbox))):
        raise ValueError("navigation visual stability point lies outside bound target geometry")
    return {
        "candidate_id": candidate.candidate_id, "element_id": candidate.element_id,
        "label": candidate.label, "text": candidate.text, "role": candidate.role,
        "element_label": candidate.element.label, "element_text": candidate.element.text,
        "element_role": candidate.element.role, "matched_text": grounded.matched_text,
        "element_bbox": list(element_bbox), "candidate_bbox": list(candidate_bbox),
        "control_id": control_id, "runtime_id": runtime_id,
        "control_bbox": list(control_bbox), "click_point": point,
    }


def _manual_selected_target(evidence, uia, intent):
    """冻结当前真实控件身份；首次动作不需要伪造已学习控件引用。"""
    raw, risk = _decision_and_risk(evidence, uia, intent,
        require_control_target=intent.learned_control is not None, automatic_safety_interception=False)
    _validate_uia(uia, evidence)
    candidates, local = _parse_projected_recognition(evidence['recognition']['result'])
    selection = action_selection(raw, candidates, local, automatic_safety_interception=False)
    candidate = next(item for item in candidates.candidates if item.candidate_id == selection['selected_candidate_id'])
    grounded = next(item for item in local.results if item.candidate_id == candidate.candidate_id)
    point = selection['selected_click_point']
    if intent.semantic_action == 'scroll_region':
        from app.agent.fresh_scroll_region import current_scroll_container
        control = current_scroll_container(uia['controls'], point)
    elif intent.semantic_action == 'fill_field':
        from app.gate.fresh_action_risk import _editable_text_controls
        controls, reason = _editable_text_controls(uia['controls'], point)
        if reason is not None or len(controls) != 1:
            raise ValueError('manual text selection has no unique current field')
        matches = [item for item in uia['controls'] if item.get('control_id') == controls[0]['control_id']]
        if len(matches) != 1:
            raise ValueError('manual text selection has ambiguous current field')
        control = matches[0]
    else:
        from app.gate.fresh_action_risk import _actionable, _contains
        target = {'label': candidate.label, 'role': candidate.role}
        # 同名但未命中本次点的控件不构成歧义，重叠命中仍必须拒绝。
        matches = [item for item in uia['controls'] if uia_control_matches(item, target)
                   and _actionable(item) and item.get('enabled') is True
                   and item.get('visible') is True and _contains(item['bbox'], point)]
        if len(matches) != 1:
            raise ValueError('manual preview requires one identifiable current UIA control')
        control = matches[0]
    control_id = control.get('control_id')
    if (not isinstance(control_id, str) or not control_id
            or sum(item.get('control_id') == control_id for item in uia['controls']) != 1
            or control.get('enabled') is not True or control.get('visible') is not True):
        raise ValueError('manual preview current UIA identity is invalid')
    runtime_id = control.get('runtime_id')
    if runtime_id is not None and (not isinstance(runtime_id, list) or not runtime_id
            or any(type(item) is not int for item in runtime_id)
            or sum(item.get('runtime_id') == runtime_id for item in uia['controls']) != 1):
        raise ValueError('manual preview current UIA runtime identity is invalid')
    viewport = evidence['capture']['viewport_size']
    boxes = [_box(value, viewport) for value in (candidate.element.bbox.to_dict(),
        candidate.refined_bbox or candidate.element.bbox.to_dict(), control['bbox'])]
    if any(not (box[0] <= point['x'] < box[0] + box[2] and box[1] <= point['y'] < box[1] + box[3]) for box in boxes):
        raise ValueError('manual preview point is outside current control geometry')
    return {'candidate_id': candidate.candidate_id, 'element_id': candidate.element_id,
        'label': candidate.label, 'text': candidate.text, 'role': candidate.role,
        'element_label': candidate.element.label, 'element_text': candidate.element.text,
        'element_role': candidate.element.role, 'matched_text': grounded.matched_text,
        'element_bbox': list(boxes[0]), 'candidate_bbox': list(boxes[1]), 'control_bbox': list(boxes[2]),
        'control_id': control_id, 'runtime_id': runtime_id, 'control_name': control.get('name'),
        'control_type': control.get('control_type'), 'click_point': point}


def _validate_uia(uia, evidence) -> None:
    summary = evidence["uia"]
    if (not isinstance(uia, dict) or uia.get("provider") != "windows_uia"
            or not isinstance(uia.get("controls"), list)
            or any(not isinstance(control, dict) for control in uia["controls"])
            or uia.get("control_count") != len(uia["controls"])
            or any(uia.get(key) != summary[key] for key in ("provider", "provider_version", "status", "control_count"))
            or _digest(uia) != summary["snapshot_sha256"]):
        raise ValueError("navigation visual stability full UIA snapshot binding is invalid")
    window = uia.get("window")
    if (not isinstance(window, dict) or type(window.get("handle")) is not int
            or type(window.get("process_id")) is not int
            or window["handle"] != evidence["target"]["window_handle"]
            or window["process_id"] != evidence["target"]["process_id"]):
        raise ValueError("navigation visual stability UIA window identity is invalid")
    _box(window.get("bbox"), evidence["capture"]["viewport_size"])


def _load_navigation_png(png_bytes, evidence):
    image = _load_bound_png(png_bytes, evidence)
    # 当前截图服务输出单帧 RGB；拒绝会在 RGB 转换中丢失透明度的其他图片。
    with Image.open(BytesIO(png_bytes)) as opened:
        if opened.mode != "RGB" or "transparency" in opened.info or getattr(opened, "n_frames", 1) != 1:
            raise ValueError("navigation visual stability requires an opaque single-frame RGB capture")
    return image


def _box(value, viewport) -> tuple[int, int, int, int]:
    if not isinstance(value, dict) or set(value) != {"x", "y", "w", "h"}:
        raise ValueError("navigation visual stability target geometry is invalid")
    x, y, width, height = (value[key] for key in ("x", "y", "w", "h"))
    if (any(type(item) is not int for item in (x, y, width, height))
            or min(x, y) < 0 or min(width, height) <= 0
            or x + width > viewport["width"] or y + height > viewport["height"]):
        raise ValueError("navigation visual stability target geometry is outside capture")
    return x, y, width, height


def compare_navigation_uia(expectation, original, current, current_uia):
    """重用控件上下文规则，不把导航目标伪装成填写字段。"""
    from app.agent.control_uia_stability import ControlContextIdentity, compare_navigation_uia_context

    target = expectation['selected_target']
    window = original['target']
    if (not isinstance(target.get('runtime_id'), list) or not target['runtime_id']
            or any(type(item) is not int for item in target['runtime_id'])):
        raise ValueError('navigation UIA context requires an exact runtime identity')
    identity = ControlContextIdentity(
        window_handle=window['window_handle'], process_id=window['process_id'],
        process_create_time=original['application']['process_create_time'],
        runtime_id=tuple(target['runtime_id']),
        window_rect=tuple(window['rect'][key] for key in ('x', 'y', 'width', 'height')),
        control_bbox=tuple(target['control_bbox']))
    return compare_navigation_uia_context(control_identity=identity,
        original_evidence=original, original_uia=expectation['uia_snapshot'],
        current_evidence=current, current_uia=current_uia)


def _recomputed_reference(expectation, original, current, original_png_bytes, current_png_bytes,
                          *, current_uia_snapshot=None):
    if type(original_png_bytes) is not bytes or type(current_png_bytes) is not bytes:
        raise TypeError("navigation visual stability comparison requires immutable PNG bytes")
    if any(current[key] != original[key] for key in ("target", "application")):
        raise ValueError("navigation visual stability window, application or UIA identity changed")
    current_uia = expectation['uia_snapshot']
    uia_stability = None
    if current['uia'] != original['uia']:
        if current_uia_snapshot is None:
            raise ValueError('navigation visual stability UIA identity changed without current context proof')
        current_uia = current_uia_snapshot
        uia_stability = compare_navigation_uia(expectation, original, current, current_uia)
        if uia_stability is None:
            raise ValueError('navigation UIA delta has no classified context change')
    elif current_uia_snapshot is not None:
        _validate_uia(current_uia_snapshot, current)
        if current_uia_snapshot != current_uia:
            raise ValueError('navigation current UIA differs from its original identity')
    before, after = original["capture"], current["capture"]
    if (after["capture_id"] == before["capture_id"]
            or after["capture_started_ns"] <= before["observed_at_ns"]
            or after["capture_clock_id"] != before["capture_clock_id"]
            or after["viewport_size"] != before["viewport_size"]):
        raise ValueError("navigation visual stability requires a newer bound capture")
    if current["recognition"]["status"] == "completed":
        intent = FreshLearningIntent.from_dict(expectation['intent'])
        selected = (_selected_target(current, current_uia, intent)
            if expectation.get('automatic_safety_interception', True)
            else _manual_selected_target(current, current_uia, intent))
        # 点仍独立通过原 gate/risk 且绑定完整证据；本模块不决定两点可否等价。
        for key, value in expectation["selected_target"].items():
            if key == "click_point" or selected[key] == value:
                continue
            # 两帧均经严格目标和 OCR 佐证；仅比较空白等价，不改写原文或封存结构。
            if (key == "matched_text" and expectation.get('automatic_safety_interception', True)
                    and isinstance(value, str) and isinstance(selected[key], str)
                    and "".join(value.split()) == "".join(selected[key].split())):
                from app.agent.learned_control_reference import _placeholder_inside_current_field
                from app.gate.fresh_action_risk import _contains
                from app.operation.recognition.control_corroboration import has_current_control_ocr_binding

                corroborations = []
                for frame, target in ((original, expectation["selected_target"]), (current, selected)):
                    candidates, local = _parse_projected_recognition(frame["recognition"]["result"])
                    matches = [item for item in local.results
                        if item.candidate_id == target["candidate_id"] and item.element_id == target["element_id"]]
                    candidate_matches = [item for item in candidates.candidates if item.candidate_id == target['candidate_id']]
                    bound_ocr = (len(matches) == 1 and len(candidate_matches) == 1
                        and has_current_control_ocr_binding(candidate_matches[0], matches[0],
                            expectation['uia_snapshot'], frame['capture']['screenshot_sha256']))
                    if (len(matches) != 1 or not bound_ocr and (
                            matches[0].coordinate_source != "vista_point_v1_corroborated_by_local_ocr"
                            or not _placeholder_inside_current_field(matches[0],
                                dict(zip(("x", "y", "w", "h"), target["element_bbox"])))
                            or not _contains(matches[0].matched_text_bbox, target["click_point"]))):
                        raise ValueError("navigation whitespace equivalence lacks current OCR corroboration")
                    corroboration = matches[0].to_dict()
                    # 点的执行等价仍由后续层决定；其余局部证据不得随空白变化被忽略。
                    corroboration.pop("matched_text")
                    corroboration.pop("refined_click_point")
                    corroborations.append(corroboration)
                if corroborations[0] != corroborations[1]:
                    raise ValueError("navigation whitespace equivalence local evidence changed")
                continue
            raise ValueError("navigation visual stability recognized target identity or geometry changed")
    before_image = _load_navigation_png(original_png_bytes, original)
    after_image = _load_navigation_png(current_png_bytes, current)
    target = expectation["selected_target"]
    boxes = [target[key] for key in ("element_bbox", "candidate_bbox", "control_bbox")]
    left, top = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, bottom = max(box[0] + box[2] for box in boxes), max(box[1] + box[3] for box in boxes)
    protected = _protected_bbox((left, top, right - left, bottom - top), before_image.size)
    before_crop = before_image.crop(_xywh_to_box(protected))
    after_crop = after_image.crop(_xywh_to_box(protected))
    if expectation.get('automatic_safety_interception', True) and ImageChops.difference(before_crop, after_crop).getbbox() is not None:
        raise NavigationVisualPixelsChanged("navigation visual stability protected target pixels changed")
    try:
        changed_pixels, changed_bbox = _bounded_background_delta(before_image, after_image, protected,
            automatic_safety_interception=expectation.get('automatic_safety_interception', True))
    except TextVisualPixelsChanged as error:
        raise NavigationVisualPixelsChanged(str(error).replace("text visual stability", "navigation visual stability")) from error
    return {
        "contract_version": "navigation_visual_stability_attestation_v2" if uia_stability else "navigation_visual_stability_attestation_v1", "policy": (
            _POLICY if expectation.get('automatic_safety_interception', True) else 'manual_pixels_observation_v1'),
        "navigation_expectation_sha256": _digest(expectation),
        "before_evidence_sha256": _digest(original), "after_evidence_sha256": _digest(current),
        "before_screenshot_sha256": sha256(original_png_bytes).hexdigest(),
        "after_screenshot_sha256": sha256(current_png_bytes).hexdigest(),
        "protected_bbox": list(protected),
        "protected_before_sha256": _pixel_sha256(before_crop),
        "protected_after_sha256": _pixel_sha256(after_crop),
        "changed_pixels": changed_pixels,
        "changed_bbox": list(changed_bbox) if changed_bbox is not None else None,
        "recognition_status": current["recognition"]["status"],
        **({'uia_stability': uia_stability, 'current_uia_snapshot': current_uia} if uia_stability else {}),
    }


__all__ = [
    "NavigationVisualPixelsChanged", "NavigationVisualStabilityAttestation",
    "NavigationVisualStabilityScope", "navigation_visual_expectation",
    "verify_navigation_visual_stability_reference",
]
