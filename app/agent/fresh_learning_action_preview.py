"""首次动作的当前证据预览；复用点击前策略，但不产生执行权限。"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping

from app.agent.fresh_learning_action_contracts import (
    FreshLearningClaimObservation, FreshLearningIntent, canonical_json_bytes,
    payload_sha256, validate_source_reference,
)
from app.agent.automatic_safety_policy import (
    MODE_PREVIEW_VERSION, FRESH_PREVIEW_VERSIONS, action_selection, automatic_safety_report,
    preview_action_selection, preview_automatic_safety_interception, validate_automatic_safety_interception,
)


CONTRACT_VERSION = "fresh_learning_action_preview_v1"
CONTROL_TARGET_CONTRACT_VERSION = "fresh_learning_action_preview_v2"
_FLAGS = ("artifact_is_authorization", "execute_binding_enabled", "action_executed")
_KEYS = {"contract_version", "session_id", "observation_id", "intent", "source_sha256",
         "capture_source", "observation_evidence", "uia_snapshot", "pre_click_decision",
         "risk", "preview_sha256", *_FLAGS}
_TEXT_KEYS = {"text_execution_ref", "text_field_expectation_ref"}


def _validate_text_preview(data, intent):
    from app.agent.text_execution import validate_text_execution_reference
    from app.agent.text_field_evidence import validate_text_field_expectation_reference
    from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence

    declaration = intent.text_parameters_ref
    execution = validate_text_execution_reference(data["text_execution_ref"], declaration)
    expected = validate_text_field_expectation_reference(data["text_field_expectation_ref"], declaration)
    evidence = data["observation_evidence"]
    target, capture = evidence["target"], evidence["capture"]
    before, application = expected["before"], evidence["application"]
    _application_identity_from_evidence({"application": application})
    identity, rect = before["identity"], target["rect"]
    point = preview_action_selection(data)["selected_click_point"]
    x, y, width, height = identity["control_bbox"]
    if (expected["text_execution_ref"] != execution
            or identity["window_handle"] != target["window_handle"]
            or identity["process_id"] != target["process_id"]
            or identity["window_rect"] != [rect[k] for k in ("x", "y", "width", "height")]
            or "process_create_time" not in application or "executable_path" not in application
            or identity["process_create_time"] != application.get("process_create_time")
            or before["capture_id"] != capture["capture_id"]
            or before["observed_at_ns"] < capture["observed_at_ns"]
            or not (x <= point["x"] < x + width and y <= point["y"] < y + height)):
        raise ValueError("fresh text field preview does not match current evidence")


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        converter = getattr(value, "to_dict", None)
        value = converter() if callable(converter) else value
    if not isinstance(value, Mapping):
        raise ValueError("fresh preview requires a mapping")
    return dict(value)


def _parse_projected_recognition(projection):
    from app.agent.live_runtime_composition import _parse_recognition

    value = json.loads(canonical_json_bytes(_mapping(projection)))
    for result in value.get("narrow_search_result", {}).get("results", []):
        # 公共投影不含本地裁剪路径；路径不参与定位或权限判断。
        if "crop_path" in result:
            raise ValueError("public recognition projection contains private crop path")
        result["crop_path"] = None
    return _parse_recognition(value)


def _validate_editable_ocr_bindings(candidates, local, uia, screenshot_sha256, *, goal, semantic_action,
                                   observation_evidence=None):
    """字段别名只能来自当前控件内的 OCR；重算证据而不是接受生产者的放行标记。"""
    from app.operation.recognition.editable_control_corroboration import (
        REASON, EVIDENCE_KEY, has_current_editable_control_ocr_binding,
    )

    for candidate in candidates.candidates:
        matches = [item for item in local.results if item.candidate_id == candidate.candidate_id]
        from app.operation.recognition.native_field_hit_binding import EVIDENCE_KEY as HIT_KEY, validate_hit_observation
        if HIT_KEY in candidate.element.evidence:
            if observation_evidence is None or semantic_action != 'fill_field' or len(matches) != 1:
                raise ValueError('native field hit requires an owned fill observation')
            validate_hit_observation(candidate.element.evidence[HIT_KEY], observation_evidence,
                                     uia, matches[0].refined_click_point)
        marked = EVIDENCE_KEY in candidate.element.evidence
        reason_present = any(REASON in item.reasons for item in matches)
        if not marked and not reason_present:
            continue
        if (semantic_action != 'fill_field' or not marked or len(matches) != 1
                or not has_current_editable_control_ocr_binding(
                    candidate, matches[0], uia, screenshot_sha256, goal,
                    control_target=candidates.summary.get('control_target'))):
            raise ValueError('fresh preview current editable field OCR binding is invalid')
    if any(REASON in item.reasons and not any(
            item.candidate_id == candidate.candidate_id for candidate in candidates.candidates)
            for item in local.results):
        raise ValueError('fresh preview current editable field OCR binding has no candidate')


def _decision_and_risk(evidence, uia, intent, *, original=None, require_control_target=False,
                       automatic_safety_interception=True):
    from app.agent.live_runtime_composition import _parse_recognition, _validated_uia_snapshot
    from app.agent.fresh_learning_observation import _require_uia_rect
    from app.operation.recognition.decision import decide_pre_click
    from app.gate.fresh_action_risk import classify_fresh_action_risk

    strict = validate_automatic_safety_interception(automatic_safety_interception)
    target = _mapping(evidence.get("target"))
    capture = _mapping(evidence.get("capture"))
    viewport = _mapping(capture.get("viewport_size"))
    rect = _mapping(target.get("rect"))
    if (type(target.get("window_handle")) is not int or target["window_handle"] <= 0
            or type(target.get("process_id")) is not int or target["process_id"] <= 0
            or any(type(viewport.get(k)) is not int or viewport[k] <= 0 for k in ("width", "height"))
            or rect.get("width") != viewport["width"] or rect.get("height") != viewport["height"]):
        raise ValueError("fresh preview target rectangle is invalid")
    checked_uia = _validated_uia_snapshot(uia, expected_identity=(
        target["window_handle"], target["process_id"], (viewport["width"], viewport["height"])))
    _require_uia_rect(checked_uia, rect)
    if payload_sha256(checked_uia) != _mapping(evidence.get("uia")).get("snapshot_sha256"):
        raise ValueError("fresh preview UIA digest mismatch")
    recognition = _mapping(evidence.get("recognition"))
    if (recognition.get("status") != "completed" or recognition.get("goal") != intent.goal
            or recognition.get("result_is_original") is not False
            or recognition.get("result_projection_contract") != "fresh_read_only_recognition_projection_v1"):
        raise ValueError("fresh preview recognition provenance mismatch")
    projection = _mapping(recognition.get("result"))
    candidates, local = _parse_projected_recognition(projection) if original is None else _parse_recognition(original)
    if candidates.goal != intent.goal or local.goal != intent.goal or projection.get("goal") != intent.goal:
        raise ValueError("fresh preview recognition goal mismatch")
    _validate_editable_ocr_bindings(candidates, local, checked_uia, capture.get('screenshot_sha256'),
                                  goal=intent.goal, semantic_action=intent.semantic_action,
                                  observation_evidence=evidence)
    from app.operation.recognition.control_corroboration import REASON, has_current_control_ocr_binding
    from app.operation.recognition.native_control_hit_binding import (
        EVIDENCE_KEY as ICON_KEY, REASON as ICON_REASON, COORDINATE_SOURCE as ICON_SOURCE,
        has_current_native_control_hit, validate_control_hit_observation)
    from app.operation.recognition.scroll_grounding import (
        EVIDENCE_KEY as SCROLL_KEY, COORDINATE_SOURCE as SCROLL_SOURCE, has_current_scroll_grounding)
    for candidate in candidates.candidates:
        matches = [r for r in local.results if r.candidate_id == candidate.candidate_id]
        scroll_proof = candidate.element.evidence.get(SCROLL_KEY)
        scroll_marked = (SCROLL_KEY in candidate.element.evidence
            or candidates.summary.get("semantic_action") == "scroll_region"
            or candidate.element.interaction_type == "scroll"
            or candidate.element.click_strategy == SCROLL_SOURCE
            or any(r.coordinate_source == SCROLL_SOURCE or "current_scroll_container_empty_point" in r.reasons for r in matches))
        if scroll_marked:
            # 观察模式仅关闭策略拦截，不能关闭新滚动主路径的来源和意图完整性。
            if (intent.semantic_action != "scroll_region" or len(matches) != 1
                    or not isinstance(scroll_proof, dict)
                    or scroll_proof.get("scroll_parameters") != intent.scroll_parameters
                    or "current_scroll_container_empty_point" not in matches[0].reasons
                    or not has_current_scroll_grounding(candidate, matches[0], checked_uia,
                        capture.get("screenshot_sha256"), goal=intent.goal)):
                raise ValueError("fresh preview current scroll container binding is invalid")
        has_proof = ICON_KEY in candidate.element.evidence
        marked = any(ICON_REASON in r.reasons or r.coordinate_source == ICON_SOURCE for r in matches)
        if has_proof or marked:
            if (intent.semantic_action != 'open_detail' or len(matches) != 1
                    or not has_current_native_control_hit(candidate, matches[0], checked_uia,
                                                         capture.get('screenshot_sha256'))):
                raise ValueError('fresh preview native control hit binding is invalid')
            validate_control_hit_observation(candidate.element.evidence[ICON_KEY], evidence,
                checked_uia, matches[0].refined_click_point)
    for result in local.results:
        if REASON in result.reasons:
            matches = [item for item in candidates.candidates if item.candidate_id == result.candidate_id]
            if len(matches) != 1 or not has_current_control_ocr_binding(
                    matches[0], result, checked_uia, capture.get('screenshot_sha256')):
                raise ValueError('fresh preview current control OCR binding is invalid')
    recorded_target = candidates.summary.get("control_target")
    if recorded_target is not None or require_control_target:
        from app.agent.learned_control_reference import recognition_target_from_learned_control
        expected_target = recognition_target_from_learned_control(intent.learned_control,
            semantic_action=intent.semantic_action)
        if recorded_target != expected_target or require_control_target and expected_target is None:
            raise ValueError("fresh preview control target differs from pinned learned control")
    decision = decide_pre_click(goal=intent.goal, candidates=candidates, grounding=local,
        uia_snapshot=checked_uia, screenshot_sha256=capture.get('screenshot_sha256')).to_dict()
    selection = action_selection(decision, candidates, local, automatic_safety_interception=strict)
    chosen = [x for x in candidates.candidates if x.candidate_id == selection["selected_candidate_id"]]
    grounded = [x for x in local.results if x.candidate_id == selection["selected_candidate_id"]]
    if len(chosen) != 1 or len(grounded) != 1:
        raise ValueError("fresh preview candidate is ambiguous")
    candidate, result = chosen[0], grounded[0]
    if selection["selected_click_point"] != result.refined_click_point:
        raise ValueError("fresh preview point differs from local grounding")
    bbox = candidate.refined_bbox or candidate.element.bbox.to_dict()
    if (bbox["x"] < 0 or bbox["y"] < 0 or bbox["x"] + bbox["w"] > viewport["width"]
            or bbox["y"] + bbox["h"] > viewport["height"]):
        raise ValueError("fresh preview candidate outside capture")
    risk = classify_fresh_action_risk(proposed_semantic_action=intent.semantic_action, goal=intent.goal,
        candidate=candidate, local=result, capture_id=capture["capture_id"], uia_snapshot=checked_uia)
    if risk["hard_blocked"] is not False and (strict or risk['risk_class'] in {'unresolved', 'unsupported'}):
        raise ValueError("fresh preview observed target risk blocked: " + ",".join(risk["reasons"]))
    if intent.semantic_action == "scroll_region":
        from app.agent.fresh_scroll_region import fresh_scroll_dispatch
        fresh_scroll_dispatch(intent, risk, evidence).validate_point(
            tuple(selection["selected_click_point"][k] for k in ("x", "y")))
    if intent.learned_control is not None:
        from app.agent.learned_control_reference import validate_current_learned_control
        validate_current_learned_control(intent.learned_control, candidate, result, checked_uia, evidence['application'],
            semantic_action=intent.semantic_action, control_target=recorded_target,
            screenshot_sha256=capture.get('screenshot_sha256'))
    return decision, risk


@dataclass(frozen=True, slots=True)
class FreshLearningActionPreview:
    _payload_json: bytes = field(repr=False)

    @classmethod
    def from_dict(cls, value: Any) -> "FreshLearningActionPreview":
        from app.agent.fresh_learning_archive import _reference

        data = _mapping(value)
        intent = FreshLearningIntent.from_dict(data.get("intent"))
        keys = _KEYS | _TEXT_KEYS if intent.semantic_action == "fill_field" else _KEYS
        if data.get('contract_version') == MODE_PREVIEW_VERSION:
            keys = keys | {'automatic_safety_interception', 'action_selection', 'automatic_safety_report'}
        if set(data) != keys or data.get("contract_version") not in FRESH_PREVIEW_VERSIONS:
            raise ValueError("fresh preview requires exact contract fields")
        strict = preview_automatic_safety_interception(data)
        if any(data[k] is not False for k in _FLAGS):
            raise ValueError("fresh preview cannot grant action authority")
        if data["preview_sha256"] != payload_sha256({k: v for k, v in data.items() if k != "preview_sha256"}):
            raise ValueError("fresh preview digest mismatch")
        if (data["session_id"], data["observation_id"], data["source_sha256"]) != (
                intent.session_id, intent.observation_id, intent.source_sha256):
            raise ValueError("fresh preview intent binding mismatch")
        evidence = _mapping(data["observation_evidence"])
        if (set(evidence) != {"contract_version", "capture", "target", "application", "uia", "recognition", *_FLAGS}
                or evidence["contract_version"] != "fresh_learning_observation_v1"
                or any(evidence[k] is not False for k in _FLAGS)):
            raise ValueError("fresh preview observation evidence is invalid")
        capture = _mapping(evidence["capture"])
        reference = _reference(data["capture_source"])
        if any(reference[k] != capture.get(k) for k in ("capture_id", "screenshot_sha256")):
            raise ValueError("fresh preview capture reference mismatch")
        content_hash = payload_sha256({"evidence_json": canonical_json_bytes(evidence).decode("utf-8"),
                                      "screenshot_sha256": capture["screenshot_sha256"]})
        if reference["content_sha256"] != content_hash:
            raise ValueError("fresh preview evidence archive digest mismatch")
        decision, risk = _decision_and_risk(evidence, _mapping(data["uia_snapshot"]), intent,
            require_control_target=data['contract_version'] == CONTROL_TARGET_CONTRACT_VERSION
                or data['contract_version'] == MODE_PREVIEW_VERSION and intent.learned_control is not None,
            automatic_safety_interception=strict)
        if decision != data["pre_click_decision"] or risk != data["risk"]:
            raise ValueError("fresh preview gate or risk differs from current evidence")
        if data['contract_version'] == MODE_PREVIEW_VERSION:
            candidates, local = _parse_projected_recognition(evidence['recognition']['result'])
            selected = action_selection(decision, candidates, local, automatic_safety_interception=strict)
            if data['action_selection'] != selected or data['automatic_safety_report'] != automatic_safety_report(decision, risk):
                raise ValueError('fresh preview manual selection or original policy report differs')
            if not strict:
                # 在批准前拒绝无法绑定真实控件的观察模式，不等到消费后才发现不支持。
                from app.agent.navigation_visual_stability import _manual_selected_target
                _manual_selected_target(evidence, data['uia_snapshot'], intent)
        if intent.semantic_action == "fill_field":
            _validate_text_preview(data, intent)
        return cls(canonical_json_bytes(data))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._payload_json.decode("utf-8"))

    @property
    def content_sha256(self) -> str:
        return self.to_dict()["preview_sha256"]


def validate_fresh_preview_binding(preview, observation, intent, source_reference) -> dict[str, Any]:
    data = FreshLearningActionPreview.from_dict(preview).to_dict()
    observation = FreshLearningClaimObservation.from_dict(_mapping(observation)).to_dict()
    intent = FreshLearningIntent.from_dict(_mapping(intent))
    source = validate_source_reference(_mapping(source_reference))
    if (data["intent"] != intent.to_dict() or observation["source"] != source
            or data["source_sha256"] != source["source_sha256"]
            or data["session_id"] != observation["session_id"]
            or data["observation_id"] != observation["observation_id"]):
        raise ValueError("fresh preview claim binding mismatch")
    evidence = data["observation_evidence"]
    target = evidence["target"]
    capture = evidence["capture"]
    previous = observation["capture"]
    if (evidence["application"] != observation["application"]
            or target["window_handle"] != source["target_window_handle"]
            or target["process_id"] != source["target_process_id"]
            or capture["capture_id"] == previous["capture_id"]
            or capture.get("capture_clock_id") != previous.get("capture_clock_id")
            or any(type(capture.get(k)) is not int for k in ("capture_started_ns", "captured_at_ns", "observed_at_ns"))
            or not previous["observed_at_ns"] <= capture["capture_started_ns"] <= capture["captured_at_ns"] <= capture["observed_at_ns"]):
        raise ValueError("fresh preview capture epoch or application binding mismatch")
    scope = {k: source[k] for k in ("connection_id", "task_id", "segment_id")}
    expected_id = payload_sha256({"scope": scope, "content_sha256": data["capture_source"]["content_sha256"],
                                  "capture_id": capture["capture_id"]})
    if expected_id != data["capture_source"]["source_id"]:
        raise ValueError("fresh preview capture scope mismatch")
    return data


def _execution_comparison_value(preview: FreshLearningActionPreview) -> dict[str, Any]:
    value = preview.to_dict()
    source = value["capture_source"]
    for key in ("source_id", "content_sha256", "capture_id"):
        source[key] = "<fresh-capture-derived>"
    capture = value["observation_evidence"]["capture"]
    for key in ("capture_id", "capture_started_ns", "captured_at_ns", "observed_at_ns"):
        capture[key] = "<fresh-capture-derived>"
    # 原始识别结果包含本地图片路径；每份预览已分别证明其原始值与公共投影一致。
    value["observation_evidence"]["recognition"]["result_sha256"] = (
        "<fresh-capture-derived>"
    )
    value["risk"]["capture_id"] = "<fresh-capture-derived>"
    from app.operation.recognition.native_field_hit_binding import EVIDENCE_KEY as HIT_KEY
    for candidate in value['observation_evidence']['recognition']['result']['candidate_result']['candidates']:
        for hit_key in (HIT_KEY, 'current_native_control_hit'):
            hit = candidate['element'].get('evidence', {}).get(hit_key)
            if hit is None:
                continue
            for key in ('capture_id','capture_started_ns','captured_at_ns','before_hit_ns','after_hit_ns'):
                hit[key] = '<fresh-hit-derived>'
            for key in ('capture_id','observed_at_ns'):
                hit['hit'][key] = '<fresh-hit-derived>'
    value["preview_sha256"] = "<fresh-capture-derived>"
    if "text_field_expectation_ref" in value:
        before = value["text_field_expectation_ref"]["before"]
        for key in ("capture_id", "read_id", "observed_at_ns"):
            before[key] = "<fresh-field-read-derived>"
    return value


def _manual_execution_comparison_value(preview):
    """观察模式比较执行协议，不将两次独立重算的策略告警伪装为相同。"""
    checked = FreshLearningActionPreview.from_dict(preview)
    data = checked.to_dict()
    if preview_automatic_safety_interception(data):
        raise ValueError('manual comparison requires a frozen manual preview')
    from app.agent.navigation_visual_stability import _manual_selected_target
    target = _manual_selected_target(data['observation_evidence'], data['uia_snapshot'],
        FreshLearningIntent.from_dict(data['intent']))
    target.pop('click_point')
    value = _execution_comparison_value(checked)
    value['manual_target_identity'] = target
    from app.operation.recognition.native_control_ocr_observation import KEY, validated_native_ocr
    selection = preview_action_selection(data)
    candidates, local = _parse_projected_recognition(data['observation_evidence']['recognition']['result'])
    chosen = _unique_navigation_item(candidates.candidates, selection['selected_candidate_id'], selection['selected_element_id'])
    grounded = _unique_navigation_item(local.results, selection['selected_candidate_id'], selection['selected_element_id'])
    if KEY in chosen.element.evidence:
        observed = validated_native_ocr(chosen, grounded, data['observation_evidence']['capture']['screenshot_sha256'])
        if observed is None:
            raise ValueError('manual target OCR observation is invalid')
        value['manual_target_ocr_observation'] = {
            'classification': observed['classification'], 'target_bbox': observed['target_bbox'],
            'matches': [observed['matches'][index] for index in observed['target_match_indices']]}
    value['pre_click_decision'] = '<independently-recomputed-policy-advice>'
    value['risk'] = '<independently-recomputed-policy-advice>'
    value['automatic_safety_report'] = '<independently-recomputed-policy-advice>'
    value['observation_evidence']['recognition'] = '<independently-validated-current-recognition>'
    value['action_selection']['selected_click_point'] = '<current-point-inside-the-same-control>'
    value['capture_source']['screenshot_sha256'] = '<archived-current-pixel-observation>'
    value['observation_evidence']['capture']['screenshot_sha256'] = '<archived-current-pixel-observation>'
    return value


def _unique_navigation_item(items, candidate_id, element_id):
    """先拒绝重复候选标识，再核对确切元素；不丢弃其他候选。"""
    matches = [item for item in items if (
        item.get('candidate_id') if isinstance(item, Mapping) else item.candidate_id) == candidate_id]
    if len(matches) != 1:
        raise ValueError('navigation equivalence requires one exact selected target')
    item = matches[0]
    actual_element = item.get('element_id') if isinstance(item, Mapping) else item.element_id
    if actual_element != element_id:
        raise ValueError('navigation equivalence requires one exact selected target')
    return item


def _selected_navigation_triplet(data):
    """返回完整数组内选中三元组的引用，归一不改变未选中证据。"""
    selection = preview_action_selection(data)
    candidate_id, element_id = selection['selected_candidate_id'], selection['selected_element_id']
    recognition = data['observation_evidence']['recognition']['result']
    return tuple(_unique_navigation_item(items, candidate_id, element_id) for items in (
        recognition['candidate_result']['candidates'], recognition['narrow_search_result']['results'],
        data['pre_click_decision']['candidate_decisions']))


def _navigation_frame_target(data, point, *, require_ocr):
    from app.agent.navigation_visual_stability import _selected_target
    from app.agent.learned_control_reference import _placeholder_inside_current_field
    from app.gate.fresh_action_risk import _contains
    from app.operation.recognition.control_corroboration import has_current_control_ocr_binding
    from app.operation.recognition.native_control_hit_binding import has_current_native_control_hit

    evidence = data['observation_evidence']
    try:
        target = _selected_target(evidence, data['uia_snapshot'], FreshLearningIntent.from_dict(data['intent']))
        if require_ocr:
            candidates, local = _parse_projected_recognition(evidence['recognition']['result'])
            candidate = _unique_navigation_item(candidates.candidates, target['candidate_id'], target['element_id'])
            grounded = _unique_navigation_item(local.results, target['candidate_id'], target['element_id'])
            bound_ocr = has_current_control_ocr_binding(candidate, grounded, data['uia_snapshot'],
                evidence['capture']['screenshot_sha256'])
            bound_ocr = bound_ocr or has_current_native_control_hit(candidate, grounded, data['uia_snapshot'],
                evidence['capture']['screenshot_sha256'])
            if not bound_ocr and (grounded.candidate_id != candidate.candidate_id or grounded.element_id != candidate.element_id
                    or grounded.coordinate_source != 'vista_point_v1_corroborated_by_local_ocr'
                    or not _placeholder_inside_current_field(grounded, candidate.element.bbox.to_dict())
                    or not _contains(grounded.matched_text_bbox, point)):
                raise ValueError('navigation local OCR is not bound to the current target point')
    except ValueError as error:
        raise ValueError('navigation target or surrounding evidence drifted: ' + str(error)) from error
    return target


def _normalize_navigation_disambiguation(candidate, data, point, target, *, direct):
    from app.agent.learned_control_reference import recognition_target_from_learned_control
    from app.operation.recognition.control_target import uia_action_identity_matches
    from app.gate.fresh_action_risk import _contains

    evidence = candidate['element'].get('evidence', {})
    if 'current_uia_point_disambiguation' not in evidence:
        return
    fact = evidence['current_uia_point_disambiguation']
    binding = recognition_target_from_learned_control(data['intent'].get('learned_control'), semantic_action='open_detail')
    # 排除项仍按生产者的完整同名同角色集合核验；选中项另有可见、可操作和唯一身份约束。
    matches = [control for control in data['uia_snapshot']['controls']
               if uia_action_identity_matches(control, goal=data['intent']['goal'], control_target=binding)]
    ids = [control.get('control_id') for control in matches]
    hits = [control.get('control_id') for control in matches if _contains(control['bbox'], point)]
    if (not direct or not isinstance(fact, dict)
            or set(fact) != {'source', 'screenshot_sha256', 'point', 'selected_control_id',
                             'excluded_control_ids', 'matching_control_count'}
            or fact['source'] != 'current_screenshot_vista_point_and_uia_bbox_v1'
            or fact['screenshot_sha256'] != data['observation_evidence']['capture']['screenshot_sha256']
            or not isinstance(fact['point'], dict) or set(fact['point']) != {'x', 'y'}
            or any(type(number) is not int for number in fact['point'].values()) or fact['point'] != point
            or type(fact['matching_control_count']) is not int or fact['matching_control_count'] != len(matches)
            or len(matches) < 2 or any(not isinstance(item, str) or not item for item in ids)
            or len(set(ids)) != len(ids) or hits != [target['control_id']]
            or fact['selected_control_id'] != target['control_id']
            or fact['excluded_control_ids'] != [item for item in ids if item != target['control_id']]):
        raise ValueError('navigation current UIA disambiguation is not bound to this frame')
    # 只归一本帧已经验证的派生值；来源、身份、计数和全部未知字段仍不得改变。
    fact['point'] = '<verified-current-safe-point>'
    fact['screenshot_sha256'] = '<verified-current-capture-sha256>'


def _normalize_navigation_uia_context(before, frames, values):
    """两种策略共用完整树的上下文证明，只归一已证明的非目标名称。"""
    if frames[0]['uia_snapshot'] == frames[1]['uia_snapshot']:
        return
    if any(frame['intent']['semantic_action'] != 'open_detail' for frame in frames):
        raise ValueError('navigation UIA context requires a navigation target')
    from app.agent.navigation_visual_stability import compare_navigation_uia, navigation_visual_expectation
    try:
        transition = compare_navigation_uia(navigation_visual_expectation(before),
            frames[0]['observation_evidence'], frames[1]['observation_evidence'], frames[1]['uia_snapshot'])
    except ValueError as error:
        raise ValueError('navigation target or surrounding evidence drifted: ' + str(error)) from error
    if transition is None:
        raise ValueError('navigation UIA change has no context proof')
    for value in values:
        for change in transition['changes']:
            value['uia_snapshot']['controls'][change['index']]['name'] = '<verified-nontarget-toolbar-name>'
        value['observation_evidence']['uia']['snapshot_sha256'] = '<verified-navigation-uia-transition>'


def validate_navigation_execution_equivalence(approved, current) -> None:
    """仅比较已独立验证的导航事实；此函数不能代替原图证明或执行授权。"""
    import math
    import re
    from hashlib import sha1
    from app.gate.fresh_action_risk import _unique_texts
    from app.operation.recognition.control_corroboration import EVIDENCE_KEY, REASON, has_current_control_ocr_binding

    before = FreshLearningActionPreview.from_dict(approved)
    after = FreshLearningActionPreview.from_dict(current)
    frames = [item.to_dict() for item in (before, after)]
    if not preview_automatic_safety_interception(before):
        values = [_manual_execution_comparison_value(item) for item in (before, after)]
        _normalize_navigation_uia_context(before, frames, values)
        if values[0] != values[1]:
            raise ValueError('manual execution target, geometry or bound source changed')
        return
    values = [_execution_comparison_value(item) for item in (before, after)]
    first_learning = frames[0]['intent'].get('learned_control') is None
    _normalize_navigation_uia_context(before, frames, values)
    local_frames = [_selected_navigation_triplet(item)[1] for item in frames]
    ocr_texts = [item['matched_text'] for item in local_frames]
    sources = [item['coordinate_source'] for item in local_frames]
    from app.operation.recognition.native_control_hit_binding import COORDINATE_SOURCE as ICON_SOURCE
    if ICON_SOURCE in sources and sources[0] != sources[1]:
        raise ValueError('navigation grounding evidence source changed')
    ocr_spacing_changed = ocr_texts[0] != ocr_texts[1]
    if first_learning and (ocr_spacing_changed or preview_action_selection(before)['selected_click_point']
                           != preview_action_selection(after)['selected_click_point']):
        raise ValueError('first-learning navigation target point or OCR changed')
    if ocr_spacing_changed and ''.join(ocr_texts[0].split()) != ''.join(ocr_texts[1].split()):
        raise ValueError('navigation target or surrounding evidence drifted: local OCR changed beyond whitespace')
    points = []
    boxes = []
    direct_frames = []
    for value, frame in zip(values, frames):
        strict = preview_automatic_safety_interception(value)
        if (value['contract_version'] not in {CONTROL_TARGET_CONTRACT_VERSION, MODE_PREVIEW_VERSION, 'fresh_learning_action_preview_v1'}
                or value['intent']['semantic_action'] != 'open_detail'
                or (value['intent'].get('learned_control') is None) != first_learning
                or strict and (value['risk']['risk_class'] != 'low_risk_navigation'
                               or value['risk']['hard_blocked'] is not False)):
            raise ValueError('navigation equivalence requires a pinned low-risk target')
        decision = value['pre_click_decision']
        selection = preview_action_selection(value)
        point = selection['selected_click_point']
        if set(point) != {'x', 'y'} or any(type(point[k]) is not int for k in point):
            raise ValueError('navigation grounding point is invalid')
        points.append(dict(point))
        candidate, selected_local, selected_decision = _selected_navigation_triplet(value)
        if candidate['role'] not in {'button', 'link'}:
            raise ValueError('navigation equivalence only supports buttons and links')
        direct = candidate['element'].get('evidence', {}).get('vista_direct_identity')
        direct_frames.append(direct is not None)
        if direct is not None:
            # 模型点的标识由目标描述和当前点派生；不接受任意替换的来源标识。
            label = re.sub(r'\s+', ' ', value['intent']['goal']).strip()[:160]
            expected_id = 'vista_direct_' + sha1(f"{label}|{point['x']}|{point['y']}".encode('utf-8')).hexdigest()[:10]
            if (set(direct) != {'source', 'point', 'source_candidate_id'}
                    or direct['source'] != 'vista_direct_point_grounding'
                    or direct['point'] != point or direct['source_candidate_id'] != expected_id
                    or selected_local['coordinate_source'] not in {'vista_point_v1_corroborated_by_local_ocr', ICON_SOURCE}):
                raise ValueError('navigation direct grounding provenance changed')
            direct['point'] = '<verified-current-safe-point>'
            direct['source_candidate_id'] = '<verified-current-point-derived>'
        elif point != preview_action_selection(before)['selected_click_point']:
            raise ValueError('navigation point drift requires independent direct grounding')
        target = _navigation_frame_target(frame, point, require_ocr=direct is not None or ocr_spacing_changed)
        boxes.extend(target[key] for key in ('element_bbox', 'candidate_bbox', 'control_bbox'))
        if selected_local['coordinate_source'] == ICON_SOURCE:
            from app.operation.recognition.native_control_ocr_observation import KEY as OCR_KEY
            if OCR_KEY in candidate['element']['evidence']:
                candidate['element']['evidence'][OCR_KEY]['source_screenshot_sha256'] = '<verified-navigation-visual-delta>'
            # 原帧已分别核验完整命中证明；仅归一截图派生值，目标身份和像素仍须一致。
            icon = candidate['element']['evidence']['current_native_control_hit']
            icon['screenshot_sha256'] = '<verified-navigation-visual-delta>'
            icon['uia_snapshot_sha256'] = '<verified-navigation-uia-transition>'
            icon['hit']['point'] = '<verified-current-safe-point>'
        if REASON in selected_local['reasons']:
            checked_candidates, checked_local = _parse_projected_recognition(frame['observation_evidence']['recognition']['result'])
            checked_candidate = _unique_navigation_item(checked_candidates.candidates,
                selection['selected_candidate_id'], selection['selected_element_id'])
            checked_grounding = _unique_navigation_item(checked_local.results,
                selection['selected_candidate_id'], selection['selected_element_id'])
            if not has_current_control_ocr_binding(checked_candidate, checked_grounding,
                    frame['uia_snapshot'], frame['observation_evidence']['capture']['screenshot_sha256']):
                raise ValueError('navigation current control OCR binding is invalid')
            # 原帧完整重算后只归一当前截图和点；其余来源、框与文字继续比较。
            bound_proof = candidate['element']['evidence'][EVIDENCE_KEY]
            bound_proof['point'] = '<verified-current-safe-point>'
            bound_proof['screenshot_sha256'] = '<verified-navigation-visual-delta>'
            if ocr_spacing_changed:
                bound_proof['matched_text'] = target['label']
        _normalize_navigation_disambiguation(candidate, frame, point, target, direct=direct is not None)
        resolved = selected_decision.get('resolved_click_point')
        if (selected_local['refined_click_point'] != point or strict and selected_decision['click_point'] != point
                or not isinstance(resolved, dict) or resolved.get('chosen_point') != point
                or resolved.get('inside_bbox') is not True or resolved.get('raw_inside_bbox') is not True
                or resolved.get('raw_model_point') != point
                or resolved.get('chosen_point_source') != 'raw_grounding_point'
                or not isinstance(resolved.get('edge_margin_px'), (int, float))
                or not math.isfinite(resolved['edge_margin_px'])
                or strict and resolved['edge_margin_px'] < max(5, resolved.get('min_edge_margin_px', 5))):
            raise ValueError('navigation point is not independently safe inside the exact target')
        for item, key in ((selected_local, 'refined_click_point'), (selected_decision, 'click_point'),
                          (resolved, 'chosen_point'), (resolved, 'raw_model_point')):
            item[key] = '<verified-current-safe-point>'
        if decision['selected_click_point'] is not None:
            decision['selected_click_point'] = '<verified-current-safe-point>'
        if 'action_selection' in value:
            value['action_selection']['selected_click_point'] = '<verified-current-safe-point>'
        resolved['edge_margin_px'] = '<verified-current-safe-margin>'
        risk_targets = [item for item in value['risk']['evidence'] if item['source'] == 'selected_candidate']
        if len(risk_targets) != 1 or risk_targets[0].get('click_point') != point:
            raise ValueError('navigation risk point differs from current grounding')
        if ocr_spacing_changed:
            # 严格目标/角色和当前 OCR 已逐帧复核；只重建 OCR 对风险文本集合的贡献。
            texts = (candidate['label'], candidate['text'], candidate['element']['label'], candidate['element']['text'])
            if risk_targets[0].get('texts') != _unique_texts(*texts, selected_local['matched_text']):
                raise ValueError('navigation risk OCR text differs from current grounding')
            selected_local['matched_text'] = target['label']
            risk_targets[0]['texts'] = _unique_texts(*texts, target['label'])
        risk_targets[0]['click_point'] = '<verified-current-safe-point>'
        value['capture_source']['screenshot_sha256'] = '<verified-navigation-visual-delta>'
        value['observation_evidence']['capture']['screenshot_sha256'] = '<verified-navigation-visual-delta>'
    if points[0] != points[1] and not all(direct_frames):
        raise ValueError('navigation point drift requires independent direct grounding')
    if any(abs(points[0][key] - points[1][key]) > min(16, min(box[index] for box in boxes) / 4)
           for key, index in (('x', 2), ('y', 3))):
        raise ValueError('navigation grounding point exceeds its target-adaptive axis bound')
    if values[0] != values[1]:
        raise ValueError('navigation target or surrounding evidence drifted')


def validate_text_execution_equivalence(approved, current, *, uia_stability=None):
    """实时与重开共用；只归一已重算证明的 UIA 名称路径及派生摘要。"""
    before = FreshLearningActionPreview.from_dict(approved)
    after = FreshLearningActionPreview.from_dict(current)
    before_data, after_data = before.to_dict(), after.to_dict()
    if before_data['intent']['semantic_action'] != 'fill_field' or after_data['intent']['semantic_action'] != 'fill_field':
        raise ValueError('text equivalence requires fill previews')
    comparator = _execution_comparison_value if preview_automatic_safety_interception(before_data) else _manual_execution_comparison_value
    values = [comparator(before), comparator(after)]
    if uia_stability is not None:
        from app.agent.text_uia_stability import compare_fill_uia_context
        from app.agent.text_visual_stability import _verified_field_reference
        _, identity, _ = _verified_field_reference(before_data['text_field_expectation_ref'])
        recomputed = compare_fill_uia_context(field_identity=identity,
            original_evidence=before_data['observation_evidence'], original_uia=before_data['uia_snapshot'],
            current_evidence=after_data['observation_evidence'], current_uia=after_data['uia_snapshot'])
        if recomputed is None or canonical_json_bytes(recomputed) != canonical_json_bytes(uia_stability):
            raise ValueError('text UIA transition differs from recomputed evidence')
        for value in values:
            for change in recomputed['changes']:
                value['uia_snapshot']['controls'][change['index']]['name'] = '<verified-nontarget-toolbar-name>'
            value['observation_evidence']['uia']['snapshot_sha256'] = '<verified-text-uia-transition>'
    for value in values:
        value['capture_source']['screenshot_sha256'] = '<verified-text-visual-delta>'
        value['observation_evidence']['capture']['screenshot_sha256'] = '<verified-text-visual-delta>'
        # 两帧已分别重算字段证据，只有截图身份随类型化像素证明归一，目标事实不变。
        from app.operation.recognition.editable_control_corroboration import EVIDENCE_KEY
        recognition = value['observation_evidence']['recognition']
        if not isinstance(recognition, Mapping):
            continue
        for candidate in recognition['result']['candidate_result']['candidates']:
            binding = candidate['element'].get('evidence', {}).get(EVIDENCE_KEY)
            if binding is not None:
                binding['screenshot_sha256'] = '<verified-text-visual-delta>'
            from app.operation.recognition.native_field_hit_binding import EVIDENCE_KEY as HIT_KEY
            hit = candidate['element'].get('evidence', {}).get(HIT_KEY)
            if hit is not None:
                hit['screenshot_sha256'] = '<verified-text-visual-delta>'
                if uia_stability is not None:
                    hit['uia_snapshot_sha256'] = '<verified-text-uia-transition>'
    if values[0] != values[1]:
        raise ValueError('fresh text consume differs from the approved preview')


def validate_fresh_execution_preview(approved, current, *, text_visual_proof=None, navigation_visual_proof=None) -> None:
    """只允许重新采集产生的身份与摘要变化，目标证据必须逐项保持一致。"""

    approved_preview = FreshLearningActionPreview.from_dict(approved)
    current_preview = FreshLearningActionPreview.from_dict(current)
    before = approved_preview.to_dict()
    after = current_preview.to_dict()
    before_capture = before["observation_evidence"]["capture"]
    after_capture = after["observation_evidence"]["capture"]
    before_source = before["capture_source"]
    after_source = after["capture_source"]
    if (
        after_capture["capture_id"] == before_capture["capture_id"]
        or after_capture["capture_started_ns"] <= before_capture["observed_at_ns"]
        or after_source["source_id"] == before_source["source_id"]
        or after_source["content_sha256"] == before_source["content_sha256"]
    ):
        raise ValueError("fresh execution preview requires a newer capture")
    if "text_field_expectation_ref" in before:
        before_field = before["text_field_expectation_ref"]["before"]
        after_field = after.get("text_field_expectation_ref", {}).get("before", {})
        if (after_field.get("read_id") == before_field["read_id"]
                or after_field.get("observed_at_ns", 0) <= before_field["observed_at_ns"]):
            raise ValueError("fresh execution preview requires a newer field read")
    before_value = _execution_comparison_value(approved_preview)
    after_value = _execution_comparison_value(current_preview)
    if navigation_visual_proof is not None:
        from app.agent.navigation_visual_stability import (
            NavigationVisualStabilityAttestation, navigation_visual_expectation,
        )
        if text_visual_proof is not None or type(navigation_visual_proof) is not NavigationVisualStabilityAttestation:
            raise ValueError('navigation visual proof must be locally verified and exclusive')
        navigation_visual_proof.validate_binding(before['observation_evidence'], after['observation_evidence'],
            navigation_visual_expectation(approved_preview))
        validate_navigation_execution_equivalence(approved_preview, current_preview)
        return
    if text_visual_proof is not None:
        from app.agent.text_visual_stability import TextVisualStabilityAttestation
        if (type(text_visual_proof) is not TextVisualStabilityAttestation
                or before['intent']['semantic_action'] != 'fill_field'
                or after['intent']['semantic_action'] != 'fill_field'):
            raise ValueError("visual proof requires a locally verified fill expectation")
        text_visual_proof.validate_binding(before['observation_evidence'], after['observation_evidence'],
            before['text_field_expectation_ref'],
            automatic_safety_interception=preview_automatic_safety_interception(before))
        validate_text_execution_equivalence(approved_preview, current_preview,
            uia_stability=text_visual_proof.uia_stability_reference)
        return
    if before_value != after_value:
        raise ValueError("fresh execution preview drifted from approved evidence")


def build_fresh_learning_action_preview(*, bundle, capture_source, observation, intent, source_reference,
                                       text_field_expectation=None, automatic_safety_interception=True):
    from app.agent.fresh_learning_observation import FreshLearningActionObservation
    from app.agent.live_runtime_composition import _parse_recognition

    if type(bundle) is not FreshLearningActionObservation:
        raise TypeError("fresh preview requires original action observation")
    evidence = bundle.packet.evidence()
    original = bundle.recognition_result()
    raw_candidates, raw_local = _parse_recognition(original)
    projected_candidates, projected_local = _parse_projected_recognition(evidence["recognition"]["result"])
    for result in raw_local.results:
        result.crop_path = None
    if (sha256(bundle.packet.png_bytes).hexdigest() != evidence["capture"]["screenshot_sha256"]
            or sha256(bundle.recognition_json).hexdigest() != evidence["recognition"]["result_sha256"]
            or (raw_candidates, raw_local) != (projected_candidates, projected_local)):
        raise ValueError("fresh preview original recognition binding mismatch")
    intent = FreshLearningIntent.from_dict(_mapping(intent))
    from app.agent.learned_control_reference import recognition_target_from_learned_control
    target = recognition_target_from_learned_control(intent.learned_control, semantic_action=intent.semantic_action)
    strict = validate_automatic_safety_interception(automatic_safety_interception)
    decision, risk = _decision_and_risk(evidence, bundle.uia_snapshot(), intent, original=original,
        require_control_target=target is not None, automatic_safety_interception=strict)
    data = {"contract_version": CONTROL_TARGET_CONTRACT_VERSION if target is not None else CONTRACT_VERSION,
        "session_id": intent.session_id,
            "observation_id": intent.observation_id, "intent": intent.to_dict(),
            "source_sha256": intent.source_sha256, "capture_source": _mapping(capture_source),
            "observation_evidence": evidence, "uia_snapshot": bundle.uia_snapshot(),
            "pre_click_decision": decision, "risk": risk, **{k: False for k in _FLAGS}}
    if not strict:
        data.update(contract_version=MODE_PREVIEW_VERSION, automatic_safety_interception=False,
            action_selection=action_selection(decision, projected_candidates, projected_local, automatic_safety_interception=False),
            automatic_safety_report=automatic_safety_report(decision, risk))
    if intent.semantic_action == "fill_field":
        from app.agent.text_field_evidence import TextFieldExpectation
        from app.agent.text_execution import text_execution_reference
        from app.agent.text_parameters import text_parameter_reference

        if (type(text_field_expectation) is not TextFieldExpectation
                or text_parameter_reference(text_field_expectation.parameters.reviewed) != intent.text_parameters_ref):
            raise ValueError("fresh fill preview requires the matching local field expectation")
        data["text_execution_ref"] = text_execution_reference(text_field_expectation.parameters)
        data["text_field_expectation_ref"] = text_field_expectation.to_reference()
    elif text_field_expectation is not None:
        raise ValueError("non-text preview cannot carry a field expectation")
    data["preview_sha256"] = payload_sha256(data)
    return FreshLearningActionPreview.from_dict(validate_fresh_preview_binding(
        data, observation, intent, source_reference))
