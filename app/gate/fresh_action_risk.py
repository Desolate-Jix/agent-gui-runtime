"""首次点击候选的纯风险分类，不产生确认或执行权限。"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.gate.actions import classify_action_taxonomy
from app.gate.danger import scoped_final_submit_visible_blocker
from app.operation.recognition.schemas import (
    LocalGroundingCandidateResult,
    RecognitionCandidate,
)


CONTRACT_VERSION = "fresh_action_candidate_risk_v1"
_ALLOWED_FIRST_CLICK_SEMANTICS = {"open_detail", "back", "close_modal"}
_ACTIONABLE_CONTROL_TYPES = {
    "button",
    "hyperlink",
    "link",
    "menuitem",
    "menu item",
    "splitbutton",
    "split button",
    "checkbox",
    "check box",
    "radio button",
    "tab item",
    "tree item",
    "list item",
}
_ACTIONABLE_PATTERNS = {"invoke", "selection", "expandcollapse", "toggle"}
_EDITABLE_CONTROL_TYPES = {"edit", "textbox", "combobox", "combo box"}
_COMBOBOX_CONTROL_TYPES = {"combobox", "combo box"}
_EDITABLE_PATTERNS = {"value", "text", "valuepattern", "textpattern"}


def classify_fresh_action_risk(
    *,
    proposed_semantic_action: str,
    goal: str,
    candidate: RecognitionCandidate,
    local: LocalGroundingCandidateResult,
    capture_id: str,
    uia_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """只按当前选中目标及其点击点重叠控件分类风险。"""

    proposed = _text(proposed_semantic_action, "proposed semantic action")
    _text(goal, "goal")
    capture = _text(capture_id, "capture ID")
    if not isinstance(candidate, RecognitionCandidate):
        raise TypeError("candidate must be RecognitionCandidate")
    if not isinstance(local, LocalGroundingCandidateResult):
        raise TypeError("local must be LocalGroundingCandidateResult")

    candidate_bbox = _candidate_bbox(candidate)
    point = _point_or_none(local.refined_click_point)
    candidate_texts = _unique_texts(
        candidate.label,
        candidate.text,
        candidate.element.label,
        candidate.element.text,
        local.matched_text,
    )
    evidence = [
        {
            "source": "selected_candidate",
            "candidate_id": candidate.candidate_id,
            "element_id": candidate.element_id,
            "role": str(candidate.role or candidate.element.role or ""),
            "bbox": candidate_bbox,
            "click_point": point,
            "texts": candidate_texts,
        }
    ]

    from app.operation.recognition.native_control_ocr_observation import KEY, validated_native_ocr
    raw_ocr = candidate.element.evidence.get(KEY)
    if raw_ocr is not None:
        observed = validated_native_ocr(candidate, local, raw_ocr.get('source_screenshot_sha256'))
        if observed is None:
            raise ValueError('native control OCR risk evidence is invalid')
        for index in observed['target_match_indices']:
            item, crop = observed['matches'][index], observed['crop_bbox']
            box = item['bbox']
            evidence.append({'source': 'native_control_target_ocr',
                'candidate_id': candidate.candidate_id, 'element_id': candidate.element_id,
                'role': candidate.role, 'texts': [item['text']],
                'bbox': {'x': crop['x'] + box['x'], 'y': crop['y'] + box['y'],
                         'w': box['width'], 'h': box['height']}, 'click_point': point})

    identity_reasons: list[str] = []
    if candidate.element.interaction_type == "scroll" and proposed != "scroll_region":
        identity_reasons.append("scroll_container_cannot_authorize_click")
    if point is None:
        identity_reasons.append("chosen_point_unresolved")
    if local.candidate_id != candidate.candidate_id or local.element_id != candidate.element_id:
        identity_reasons.append("candidate_local_identity_mismatch")
    if local.status != "grounded":
        identity_reasons.append("local_grounding_not_grounded")
    if point is not None and not _contains(candidate_bbox, point):
        identity_reasons.append("chosen_point_outside_candidate")

    window, controls, uia_reason = _uia_parts(uia_snapshot)
    if uia_reason is not None:
        identity_reasons.append(uia_reason)
    elif point is not None and not _contains({"x": 0, "y": 0, "w": window["w"], "h": window["h"]}, point):
        identity_reasons.append("chosen_point_outside_uia_window")

    if not identity_reasons:
        overlap, overlap_reason = _overlapping_actionable_controls(controls, point)
        if overlap_reason is not None:
            identity_reasons.append(overlap_reason)
        else:
            evidence.extend(overlap)

    observed_taxonomy = _observed_taxonomy(evidence)
    if identity_reasons:
        return _result(
            proposed=proposed,
            observed_taxonomy=observed_taxonomy,
            risk_class="unresolved",
            hard_blocked=True,
            candidate=candidate,
            capture_id=capture,
            evidence=evidence,
            reasons=identity_reasons,
        )

    if proposed == "scroll_region":
        from app.agent.fresh_scroll_region import current_scroll_container

        try:
            scroll_binding = candidate.element.evidence.get("current_scroll_container_binding")
            parameters = scroll_binding["scroll_parameters"] if isinstance(scroll_binding, dict) else {}
            container = current_scroll_container(controls, point,
                axis=parameters.get("axis", "vertical"), target_container_id=parameters.get("target_container_id"))
        except ValueError:
            return _result(proposed=proposed, observed_taxonomy="scroll", risk_class="unresolved",
                hard_blocked=True, candidate=candidate, capture_id=capture, evidence=evidence,
                reasons=["scroll_container_missing_ambiguous_or_overlapped"])
        # 滚动容器不激活其中的提交按钮，仍拒绝把实际按钮/输入框当作滚轮落点。
        return {**_result(proposed=proposed, observed_taxonomy="scroll", risk_class="low_risk_scroll",
            hard_blocked=False, candidate=candidate, capture_id=capture, evidence=evidence,
            reasons=["observed_scroll_container"]), "scroll_target": container}

    editable: list[dict[str, Any]] = []
    editable_reason: str | None = None
    if proposed == "fill_field":
        editable_evidence, _ = _editable_text_evidence(controls, point)
        evidence.extend(editable_evidence)
        editable, editable_reason = _editable_text_controls(controls, point)

    danger_items = [
        {
            "collection": item["source"],
            "id": item.get("candidate_id") or item.get("control_id"),
            "text": " ".join(item["texts"]),
            "role": item.get("role"),
            "bbox": item.get("bbox"),
        }
        for item in evidence
    ]
    final_submit = scoped_final_submit_visible_blocker(
        danger_items,
        active_flow_started=True,
        surface_context=None,
    )
    all_text = " ".join(
        text for item in evidence for text in item["texts"]
    )
    normalized = _normalized(all_text)

    apply_only_submit_match = (
        final_submit["blocked"]
        and set(final_submit.get("matched_terms") or []) == {"apply now"}
    )
    reasons: list[str] = []
    if (final_submit["blocked"] and not apply_only_submit_match) or _send_or_confirm_match(normalized):
        reasons.append("final_submit_target")
    if _payment_or_purchase_match(normalized):
        reasons.append("payment_or_purchase_target")
    if _delete_match(normalized):
        reasons.append("destructive_delete_target")
    if reasons:
        return _result(
            proposed=proposed,
            observed_taxonomy=observed_taxonomy,
            risk_class="blocked_high_risk",
            hard_blocked=True,
            candidate=candidate,
            capture_id=capture,
            evidence=evidence,
            reasons=reasons,
        )

    if _apply_match(normalized):
        return _result(
            proposed=proposed,
            observed_taxonomy=observed_taxonomy,
            risk_class="ambiguous_apply",
            hard_blocked=True,
            candidate=candidate,
            capture_id=capture,
            evidence=evidence,
            reasons=["ambiguous_apply_target"],
        )

    if proposed == "fill_field":
        if editable_reason is not None:
            return _result(
                proposed=proposed,
                observed_taxonomy=observed_taxonomy,
                risk_class="unresolved",
                hard_blocked=True,
                candidate=candidate,
                capture_id=capture,
                evidence=evidence,
                reasons=[editable_reason],
            )
        # 某些原生 Edit 同时暴露 Invoke；它自身不是另一个覆盖控件，危险文本仍在上方统一检查。
        field = editable[0]
        from app.operation.recognition.native_field_hit_binding import EVIDENCE_KEY as HIT_KEY, disproved_container_ids
        hit = candidate.element.evidence.get(HIT_KEY)
        excluded = (disproved_container_ids(hit, uia_snapshot, point, hit.get('screenshot_sha256'))
                    if isinstance(hit, Mapping) and hit.get('capture_id') == capture else set())
        other_overlap = [
            item for item in overlap
            if not (
                bool(field["control_id"])
                and all(item[key] == field[key] for key in ("control_id", "role", "bbox", "texts"))
            )
            and not _confirmed_fill_field_ancestor_overlap(item, field, controls)
            and item['control_id'] not in excluded
        ]
        if other_overlap:
            return _result(
                proposed=proposed,
                observed_taxonomy=observed_taxonomy,
                risk_class="unresolved",
                hard_blocked=True,
                candidate=candidate,
                capture_id=capture,
                evidence=evidence,
                reasons=["editable_text_field_overlaps_actionable_control"],
            )
        return _result(
            proposed=proposed,
            observed_taxonomy=_observed_taxonomy(evidence),
            risk_class="low_risk_text_input",
            hard_blocked=False,
            candidate=candidate,
            capture_id=capture,
            evidence=evidence,
            reasons=["observed_editable_text_field"],
        )

    if proposed not in _ALLOWED_FIRST_CLICK_SEMANTICS:
        return _result(
            proposed=proposed,
            observed_taxonomy=observed_taxonomy,
            risk_class="unsupported",
            hard_blocked=True,
            candidate=candidate,
            capture_id=capture,
            evidence=evidence,
            reasons=["unsupported_first_click_semantic"],
        )

    # 字段内的值不能证明导航意图；字段中的独立按钮不按整个字段处理。
    field_roles = _EDITABLE_CONTROL_TYPES | {"input"}
    same_field = [raw for raw in controls if isinstance(raw, Mapping)
                  and raw.get("visible") is True and raw.get("enabled") is True
                  and _normalized(raw.get("control_type")) in _EDITABLE_CONTROL_TYPES
                  and raw.get("bbox") == candidate_bbox]
    if (any(_normalized(role) in field_roles for role in (candidate.role, candidate.element.role))
            or same_field):
        return _result(
            proposed=proposed, observed_taxonomy=observed_taxonomy,
            risk_class="unsupported", hard_blocked=True, candidate=candidate,
            capture_id=capture, evidence=evidence,
            reasons=["navigation_target_is_editable_field"],
        )

    safe_reasons = ["observed_low_risk_navigation"]
    if _submit_search_exempt(danger_items):
        safe_reasons.append("submit_search_exempt")
    return _result(
        proposed=proposed,
        observed_taxonomy=observed_taxonomy,
        risk_class="low_risk_navigation",
        hard_blocked=False,
        candidate=candidate,
        capture_id=capture,
        evidence=evidence,
        reasons=safe_reasons,
    )


def _candidate_bbox(candidate: RecognitionCandidate) -> dict[str, int]:
    value: Any = candidate.refined_bbox
    if value is None:
        value = candidate.element.bbox.to_dict()
    return _bbox(value, "candidate bbox")


def _point_or_none(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"x", "y"}:
        raise ValueError("local refined click point is invalid")
    x = _integer(value["x"], "local refined click x")
    y = _integer(value["y"], "local refined click y")
    return {"x": x, "y": y}


def _bbox(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "w", "h"}:
        raise ValueError(f"{label} is invalid")
    result = {key: _integer(value[key], f"{label} {key}") for key in ("x", "y", "w", "h")}
    if result["w"] < 1 or result["h"] < 1:
        raise ValueError(f"{label} is invalid")
    return result


def _uia_parts(value: Mapping[str, Any]) -> tuple[dict[str, int], list[Any], str | None]:
    if not isinstance(value, Mapping) or value.get("status") != "ok":
        return {}, [], "uia_snapshot_unavailable"
    window = value.get("window")
    controls = value.get("controls")
    if not isinstance(window, Mapping) or not isinstance(controls, list):
        return {}, [], "uia_snapshot_unresolved"
    try:
        bbox = _bbox(window.get("bbox"), "UIA window bbox")
    except ValueError:
        return {}, [], "uia_window_geometry_unresolved"
    count = value.get("control_count")
    if type(count) is not int or count != len(controls):
        return {}, [], "uia_control_count_mismatch"
    return {"w": bbox["w"], "h": bbox["h"]}, controls, None


def _overlapping_actionable_controls(
    controls: list[Any], point: Mapping[str, int]
) -> tuple[list[dict[str, Any]], str | None]:
    overlap: list[dict[str, Any]] = []
    for raw in controls:
        if not isinstance(raw, Mapping):
            return [], "uia_control_unresolved"
        if not _actionable(raw) or raw.get("enabled") is False or raw.get("visible") is False:
            continue
        try:
            bbox = _bbox(raw.get("bbox"), "UIA control bbox")
        except ValueError:
            return [], "uia_control_geometry_unresolved"
        if not _contains(bbox, point):
            continue
        overlap.append(
            {
                "source": "overlapping_uia_control",
                "control_id": str(raw.get("control_id") or ""),
                "role": str(raw.get("control_type") or ""),
                "bbox": bbox,
                "texts": _unique_texts(
                    raw.get("name"), raw.get("automation_id"), raw.get("class_name")
                ),
            }
        )
    overlap.sort(
        key=lambda item: (
            item["control_id"],
            item["role"],
            item["bbox"]["x"],
            item["bbox"]["y"],
            item["bbox"]["w"],
            item["bbox"]["h"],
            tuple(item["texts"]),
        )
    )
    return overlap, None


def _actionable(control: Mapping[str, Any]) -> bool:
    control_type = _normalized(control.get("control_type"))
    patterns = control.get("patterns")
    normalized_patterns = {
        _normalized(item) for item in patterns
    } if isinstance(patterns, (list, tuple)) else set()
    return control_type in _ACTIONABLE_CONTROL_TYPES or bool(
        normalized_patterns & _ACTIONABLE_PATTERNS
    )


def _editable_text_controls(
    controls: list[Any], point: Mapping[str, int]
) -> tuple[list[dict[str, Any]], str | None]:
    editable: list[dict[str, Any]] = []
    for raw in controls:
        if not isinstance(raw, Mapping):
            return [], "uia_control_unresolved"
        if _normalized(raw.get("control_type")) not in _EDITABLE_CONTROL_TYPES:
            continue
        try:
            bbox = _bbox(raw.get("bbox"), "UIA control bbox")
        except ValueError:
            return [], "uia_control_geometry_unresolved"
        if not _contains(bbox, point):
            continue
        if any(
            raw.get(key) is True
            for key in ("is_read_only", "readonly", "read_only", "is_password", "password", "is_password_field")
        ):
            return [], "text_field_readonly_or_password"
        if raw.get("enabled") is not True or raw.get("visible") is not True:
            continue
        patterns = raw.get("patterns")
        normalized_patterns = {
            _normalized(item) for item in patterns
        } if isinstance(patterns, (list, tuple)) else set()
        control_type = _normalized(raw.get("control_type"))
        if control_type in _COMBOBOX_CONTROL_TYPES:
            # ComboBox 必须同时暴露 Value 与 Text；仅选择/展开能力不能证明可填。
            if not {"value", "text"} <= normalized_patterns:
                return [], "text_field_edit_pattern_unresolved"
        elif not normalized_patterns & _EDITABLE_PATTERNS:
            return [], "text_field_edit_pattern_unresolved"
        editable.append(
            {
                "source": "editable_uia_control",
                "control_id": str(raw.get("control_id") or ""),
                "role": str(raw.get("control_type") or ""),
                "bbox": bbox,
                "texts": _unique_texts(
                    raw.get("name"), raw.get("automation_id"), raw.get("class_name")
                ),
            }
        )
    if not editable:
        return [], "editable_text_field_unresolved"
    if len(editable) != 1:
        return [], "multiple_editable_text_fields"
    return editable, None


def _editable_text_evidence(
    controls: list[Any], point: Mapping[str, int]
) -> tuple[list[dict[str, Any]], str | None]:
    evidence: list[dict[str, Any]] = []
    for raw in controls:
        if not isinstance(raw, Mapping):
            continue
        if _normalized(raw.get("control_type")) not in _EDITABLE_CONTROL_TYPES:
            continue
        try:
            bbox = _bbox(raw.get("bbox"), "UIA control bbox")
        except ValueError:
            continue
        if _contains(bbox, point):
            evidence.append(
                {
                    "source": "editable_uia_control",
                    "control_id": str(raw.get("control_id") or ""),
                    "role": str(raw.get("control_type") or ""),
                    "bbox": bbox,
                    "texts": _unique_texts(
                        raw.get("name"), raw.get("automation_id"), raw.get("class_name")
                    ),
                }
            )
    evidence.sort(key=lambda item: (item["control_id"], item["role"], item["bbox"]["x"], item["bbox"]["y"]))
    return evidence, None




def _confirmed_fill_field_ancestor_overlap(
    overlap: Mapping[str, Any], field: Mapping[str, Any], controls: list[Any],
) -> bool:
    """只忽略 UIA 已证明的 Group/Document 祖先，保留其危险文本供上游检查。"""
    if _normalized(overlap.get("role")) not in {"group", "document"}:
        return False
    if not _strictly_contains_bbox(overlap.get("bbox"), field.get("bbox")):
        return False
    index: dict[str, Mapping[str, Any]] = {}
    for raw in controls:
        if not isinstance(raw, Mapping):
            return False
        control_id = raw.get("control_id")
        if not isinstance(control_id, str) or not control_id or control_id != control_id.strip():
            return False
        if control_id in index:
            return False
        index[control_id] = raw
    field_id = field.get("control_id")
    if not isinstance(field_id, str) or not field_id or field_id not in index:
        return False
    chain = _ancestor_chain(index[field_id])
    if not chain or field_id in chain or overlap.get("control_id") not in chain:
        return False
    # Provider 为每个节点写入完整的 parent→root 链；该一致性可拒绝循环、未知和伪造短链。
    for position, ancestor_id in enumerate(chain):
        ancestor = index.get(ancestor_id)
        if ancestor is None or _ancestor_chain(ancestor) != chain[position + 1:]:
            return False
    return True


def _ancestor_chain(control: Mapping[str, Any]) -> tuple[str, ...] | None:
    if "ancestor_control_ids" not in control:
        return None
    value = control.get("ancestor_control_ids")
    if not isinstance(value, (list, tuple)):
        return None
    if any(not isinstance(item, str) or not item or item != item.strip() for item in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(value)


def _strictly_contains_bbox(container: Any, child: Any) -> bool:
    if not isinstance(container, Mapping) or not isinstance(child, Mapping):
        return False
    try:
        outer = _bbox(container, "ancestor bbox")
        inner = _bbox(child, "field bbox")
    except ValueError:
        return False
    contains = (
        outer["x"] <= inner["x"]
        and outer["y"] <= inner["y"]
        and outer["x"] + outer["w"] >= inner["x"] + inner["w"]
        and outer["y"] + outer["h"] >= inner["y"] + inner["h"]
    )
    return contains and outer != inner

def _observed_taxonomy(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    label = " ".join(text for item in evidence for text in item["texts"])
    return classify_action_taxonomy("", {}, label=label)


def _contains(bbox: Mapping[str, int], point: Mapping[str, int]) -> bool:
    return (
        bbox["x"] <= point["x"] < bbox["x"] + bbox["w"]
        and bbox["y"] <= point["y"] < bbox["y"] + bbox["h"]
    )


def _submit_search_exempt(items: list[dict[str, Any]]) -> bool:
    for item in items:
        text = _normalized(item.get("text"))
        identity = _normalized(item.get("id"))
        if "submit search" in f"{text} {identity}" or (
            "search" in identity and text == "submit"
        ):
            return True
    return False


def _send_or_confirm_match(text: str) -> bool:
    # 未知后果的确认不能被 Agent 标成普通导航；仅检查已选目标及其局部证据。
    return _has_phrase(text, ("send", "send message", "confirm", "confirm order", "发送", "确认", "确认订单"))


def _payment_or_purchase_match(text: str) -> bool:
    return _has_phrase(
        text,
        (
            "payment",
            "pay now",
            "make payment",
            "purchase",
            "buy now",
            "checkout",
            "付款",
            "支付",
            "购买",
            "结账",
        ),
    )


def _delete_match(text: str) -> bool:
    return _has_phrase(
        text,
        ("delete", "delete account", "remove account", "erase", "删除", "移除账户", "注销账户"),
    )


def _apply_match(text: str) -> bool:
    return _has_phrase(text, ("apply", "apply now", "quick apply", "申请", "立即申请"))


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text)
        for phrase in phrases
    )


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _unique_texts(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} is invalid")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} is invalid")
    return value


def _result(
    *,
    proposed: str,
    observed_taxonomy: dict[str, Any],
    risk_class: str,
    hard_blocked: bool,
    candidate: RecognitionCandidate,
    capture_id: str,
    evidence: list[dict[str, Any]],
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "proposed_semantic_action": proposed,
        "observed_taxonomy": observed_taxonomy,
        "risk_class": risk_class,
        "hard_blocked": hard_blocked,
        "candidate_id": candidate.candidate_id,
        "element_id": candidate.element_id,
        "capture_id": capture_id,
        "evidence": evidence,
        "reasons": list(dict.fromkeys(reasons)),
    }


__all__ = ["CONTRACT_VERSION", "classify_fresh_action_risk"]
