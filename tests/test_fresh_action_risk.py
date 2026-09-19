import json

import pytest

from app.gate.fresh_action_risk import classify_fresh_action_risk
from app.operation.page_structure.schemas import (
    InteractionPolicy,
    PageElement,
    VerificationHints,
)
from app.operation.recognition.schemas import (
    LocalGroundingCandidateResult,
    RecognitionCandidate,
    ScoreBreakdown,
)
from app.vision.schemas import BBox


def _candidate(label: str, *, candidate_id: str = "candidate.view", role: str = "button") -> RecognitionCandidate:
    bbox = BBox(100, 80, 160, 50)
    element = PageElement(
        element_id="element.view",
        label=label,
        role=role,
        interaction_type="click",
        description="",
        text=label,
        bbox=bbox,
        semantic_bbox=None,
        click_point={"x": 150, "y": 105},
        click_strategy="safe_center",
        possible_destinations=[],
        verification_hints=VerificationHints(),
        interaction_policy=InteractionPolicy(),
        fusion_confidence=0.9,
        coordinate_confidence="high",
        memory_key="",
        sources=["uia"],
    )
    return RecognitionCandidate(
        candidate_id=candidate_id,
        rank=1,
        element_id=element.element_id,
        label=label,
        role=role,
        text=label,
        score=0.9,
        eligible=True,
        reasons=[],
        score_breakdown=ScoreBreakdown(),
        element=element,
        refined_bbox={"x": 100, "y": 80, "w": 160, "h": 50},
    )


def _local(candidate: RecognitionCandidate, *, matched_text: str | None = None) -> LocalGroundingCandidateResult:
    return LocalGroundingCandidateResult(
        candidate_id=candidate.candidate_id,
        element_id=candidate.element_id,
        status="grounded",
        crop_path=None,
        crop_bbox={"x": 80, "y": 60, "w": 200, "h": 90},
        refined_click_point={"x": 150, "y": 105},
        coordinate_source="local_ocr",
        confidence=0.9,
        matched_text=matched_text if matched_text is not None else candidate.label,
        matched_text_bbox={"x": 110, "y": 90, "w": 120, "h": 30},
        reasons=[],
    )


def _control(control_id: str, name: str, bbox: dict[str, int], *, control_type: str = "Button") -> dict:
    return {
        "provider": "windows_uia",
        "control_id": control_id,
        "name": name,
        "control_type": control_type,
        "automation_id": control_id,
        "class_name": "Button",
        "bbox": bbox,
        "screen_bbox": dict(bbox),
        "enabled": True,
        "visible": True,
        "patterns": ["Invoke"],
    }


def _uia(*controls: dict) -> dict:
    return {
        "provider": "windows_uia",
        "provider_version": "windows_uia_provider_v1",
        "status": "ok",
        "window": {
            "handle": 4242,
            "process_id": 9001,
            "bbox": {"x": 0, "y": 0, "w": 800, "h": 600},
        },
        "control_count": len(controls),
        "controls": list(controls),
    }


def _classify(label: str, *, proposed: str = "open_detail", candidate_id: str = "candidate.view", controls=()):
    candidate = _candidate(label, candidate_id=candidate_id)
    return classify_fresh_action_risk(
        proposed_semantic_action=proposed,
        goal=f"Open {label}",
        candidate=candidate,
        local=_local(candidate),
        capture_id="fresh-capture.0123456789abcdef",
        uia_snapshot=_uia(*controls),
    )


@pytest.mark.parametrize(
    "label,reason",
    [
        ("Submit application", "final_submit_target"),
        ("Delete account", "destructive_delete_target"),
        ("Pay now", "payment_or_purchase_target"),
        ("Confirm order", "final_submit_target"),
        ("Confirm", "final_submit_target"),
        ("确认", "final_submit_target"),
        ("发送申请", "final_submit_target"),
        ("立即支付", "payment_or_purchase_target"),
        ("删除账户", "destructive_delete_target"),
    ],
)
def test_observed_danger_overrides_malicious_open_detail_proposal(label, reason):
    result = _classify(label, proposed="open_detail")

    assert result["hard_blocked"] is True
    assert reason in result["reasons"]
    assert result["proposed_semantic_action"] == "open_detail"
    assert result["candidate_id"] == "candidate.view"
    assert result["element_id"] == "element.view"
    assert result["capture_id"] == "fresh-capture.0123456789abcdef"
    assert result["evidence"][0]["source"] == "selected_candidate"


def test_unrelated_whole_screen_danger_control_does_not_block_selected_view_details():
    result = _classify(
        "View details",
        controls=(_control("delete_elsewhere", "Delete account", {"x": 500, "y": 400, "w": 120, "h": 40}),),
    )

    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_navigation"
    assert [item["source"] for item in result["evidence"]] == ["selected_candidate"]
    assert "Delete account" not in json.dumps(result, ensure_ascii=False)


def test_unrelated_confirm_label_does_not_block_local_navigation():
    result = _classify('View details', controls=(
        _control('confirm-elsewhere', '确认', {'x': 500, 'y': 400, 'w': 120, 'h': 40}),))
    assert result['hard_blocked'] is False
    assert '确认' not in json.dumps(result['evidence'], ensure_ascii=False)


def test_actionable_danger_control_overlapping_selected_point_hard_blocks():
    result = _classify(
        "View details",
        controls=(_control("delete_child", "Delete account", {"x": 125, "y": 90, "w": 80, "h": 30}),),
    )

    assert result["hard_blocked"] is True
    assert "destructive_delete_target" in result["reasons"]
    assert [item["source"] for item in result["evidence"]] == [
        "selected_candidate",
        "overlapping_uia_control",
    ]
    assert result["evidence"][1]["control_id"] == "delete_child"


def test_submit_search_is_not_classified_as_final_submit():
    result = _classify("Submit", candidate_id="submit_search")

    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_navigation"
    assert "submit_search_exempt" in result["reasons"]


@pytest.mark.parametrize("label", ["Apply", "Apply now", "Quick Apply", "立即申请"])
def test_apply_is_ambiguous_and_blocked_in_first_click_slice(label):
    result = _classify(label, proposed="open_detail")

    assert result["hard_blocked"] is True
    assert result["risk_class"] == "ambiguous_apply"
    assert "ambiguous_apply_target" in result["reasons"]


@pytest.mark.parametrize(
    "proposed,label",
    [
        ("open_detail", "View details"),
        ("back", "Back"),
        ("close_modal", "Close"),
    ],
)
def test_current_first_click_navigation_semantics_are_low_risk(proposed, label):
    result = _classify(label, proposed=proposed)

    assert result["contract_version"] == "fresh_action_candidate_risk_v1"
    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_navigation"
    assert result["reasons"] == ["observed_low_risk_navigation"]
    assert json.loads(json.dumps(result, ensure_ascii=False, sort_keys=True)) == result
    assert not {"authority", "approved", "execute_binding_enabled"} & set(result)


def test_goal_text_cannot_turn_safe_selected_target_into_danger_evidence():
    candidate = _candidate("View details")
    result = classify_fresh_action_risk(
        proposed_semantic_action="open_detail",
        goal="Open details and do not click Submit application or Pay now",
        candidate=candidate,
        local=_local(candidate),
        capture_id="fresh-capture.0123456789abcdef",
        uia_snapshot=_uia(),
    )

    assert result["hard_blocked"] is False
    assert result["evidence"][0]["texts"] == ["View details"]


def test_unresolved_actionable_uia_geometry_fails_closed():
    malformed = _control("danger_unknown", "Delete account", {"x": 125, "y": 90, "w": 80, "h": 30})
    malformed.pop("bbox")

    result = _classify("View details", controls=(malformed,))

    assert result["hard_blocked"] is True
    assert result["risk_class"] == "unresolved"
    assert result["evidence"] == [{
        "source": "selected_candidate",
        "candidate_id": "candidate.view",
        "element_id": "element.view",
        "role": "button",
        "bbox": {"x": 100, "y": 80, "w": 160, "h": 50},
        "click_point": {"x": 150, "y": 105},
        "texts": ["View details"],
    }]
    assert "uia_control_geometry_unresolved" in result["reasons"]


def test_missing_chosen_point_returns_explicit_unresolved_block():
    candidate = _candidate("View details")
    local = _local(candidate)
    local.refined_click_point = None

    result = classify_fresh_action_risk(
        proposed_semantic_action="open_detail",
        goal="Open View details",
        candidate=candidate,
        local=local,
        capture_id="fresh-capture.0123456789abcdef",
        uia_snapshot=_uia(),
    )

    assert result["hard_blocked"] is True
    assert result["risk_class"] == "unresolved"
    assert result["reasons"] == ["chosen_point_unresolved"]


def test_unsupported_first_click_semantic_is_never_downgraded_by_safe_label():
    result = _classify("View details", proposed="open_apply_flow")

    assert result["hard_blocked"] is True
    assert result["risk_class"] == "unsupported"
    assert "unsupported_first_click_semantic" in result["reasons"]
