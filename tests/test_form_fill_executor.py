from __future__ import annotations

import hashlib

from app.operation.form_fill_executor import (
    execute_form_choice_select,
    execute_form_dropdown_open,
    execute_form_option_select,
    execute_form_text_fill,
    verify_form_option_select_effect,
    verify_form_choice_select_effect,
    verify_form_text_fill_effect,
)


PRIVATE_VALUE = "PrivateFirst"


def _answer_decision(value: str = PRIVATE_VALUE) -> dict:
    return {
        "contract_version": "form_answer_decision_v1",
        "question_id": "q1",
        "policy": "auto_fill",
        "evidence_refs": ["profile:first_name"],
        "value_reference": "profile:first_name",
        "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "value_length": len(value),
        "value_preview": "<redacted:12 chars>",
        "pii_redacted": True,
    }


def _policy_gate(*, allowed: bool = True) -> dict:
    return {
        "contract_version": "form_action_gate_decision_v1",
        "question_id": "q1",
        "policy": "auto_fill",
        "policy_allowed": allowed,
        "reason": "policy_allowed" if allowed else "policy_blocked",
        "requires_current_grounding": True,
        "requires_action_gate": True,
        "artifact_is_authorization": False,
    }


def _candidate(*, capture_id: str = "capture-current", point: dict | None = None) -> dict:
    return {
        "candidate_id": "first-name-field",
        "bbox": {"x": 100, "y": 200, "w": 240, "h": 36},
        "click_point": point or {"x": 220, "y": 218},
        "candidate_freshness": {
            "contract_version": "action_candidate_freshness_v1",
            "capture_id": capture_id,
            "viewport_size": {"width": 1200, "height": 800},
            "source": "vista_point_v1",
            "freshness": "current_capture",
        },
    }


def _action_gate(*, allowed: bool = True, semantic_action: str = "fill_field") -> dict:
    return {
        "contract_version": "pre_click_decision_v1",
        "allowed": allowed,
        "semantic_action": semantic_action,
        "selected_candidate_id": "first-name-field",
        "selected_click_point": {"x": 220, "y": 218},
        "reason": "allowed" if allowed else "ambiguous_target",
    }


def _execute(dispatch, **overrides) -> dict:
    payload = {
        "question": {
            "contract_version": "form_question_contract_v1",
            "question_id": "q1",
            "label": "First name",
            "field_type": "text",
            "risk": "ordinary_field",
            "source_capture_id": "capture-current",
        },
        "answer_decision": _answer_decision(),
        "policy_gate": _policy_gate(),
        "candidate": _candidate(),
        "current_capture_id": "capture-current",
        "current_viewport_size": {"width": 1200, "height": 800},
        "approved_value": PRIVATE_VALUE,
        "action_gate": _action_gate(),
        "clear_existing": True,
        "dispatch": dispatch,
    }
    payload.update(overrides)
    return execute_form_text_fill(**payload)


def test_allowed_current_text_fill_dispatches_once_without_exposing_value() -> None:
    calls: list[dict] = []

    result = _execute(lambda **kwargs: calls.append(kwargs) or {"success": True})

    assert calls == [
        {
            "text": PRIVATE_VALUE,
            "x": 220,
            "y": 218,
            "click_before_typing": True,
            "clear_existing": True,
            "submit": False,
            "restore_clipboard": True,
        }
    ]
    assert result["contract_version"] == "form_fill_action_result_v1"
    assert result["dispatch_attempted"] is True
    assert result["dispatch_success"] is True
    assert result["fill_effect_success"] is None
    assert result["value_hash"] == hashlib.sha256(PRIVATE_VALUE.encode("utf-8")).hexdigest()
    assert result["value_length"] == len(PRIVATE_VALUE)
    assert result["pii_redacted"] is True
    assert PRIVATE_VALUE not in str(result)


def test_policy_rejection_prevents_dispatch() -> None:
    calls: list[dict] = []

    result = _execute(lambda **kwargs: calls.append(kwargs), policy_gate=_policy_gate(allowed=False))

    assert calls == []
    assert result["dispatch_attempted"] is False
    assert result["blocked_reason"] == "form_policy_not_allowed"


def test_stale_capture_prevents_dispatch() -> None:
    calls: list[dict] = []

    result = _execute(lambda **kwargs: calls.append(kwargs), candidate=_candidate(capture_id="capture-old"))

    assert calls == []
    assert result["dispatch_attempted"] is False
    assert "candidate_capture_id_stale" in result["freshness_decision"]["reasons"]


def test_point_outside_bbox_prevents_dispatch() -> None:
    calls: list[dict] = []

    result = _execute(lambda **kwargs: calls.append(kwargs), candidate=_candidate(point={"x": 600, "y": 600}))

    assert calls == []
    assert result["dispatch_attempted"] is False
    assert "candidate_click_point_outside_bbox" in result["freshness_decision"]["reasons"]


def test_clear_existing_must_be_explicitly_enabled() -> None:
    calls: list[dict] = []

    result = _execute(lambda **kwargs: calls.append(kwargs), clear_existing=False)

    assert calls == []
    assert result["blocked_reason"] == "clear_existing_required"


def test_final_action_is_blocked_even_when_supplied_gates_claim_allowed() -> None:
    calls: list[dict] = []
    final_question = {
        "contract_version": "form_question_contract_v1",
        "question_id": "q1",
        "label": "Submit application",
        "field_type": "action",
        "risk": "final_submit",
        "source_capture_id": "capture-current",
    }

    result = _execute(
        lambda **kwargs: calls.append(kwargs),
        question=final_question,
        action_gate=_action_gate(semantic_action="final_submit"),
    )

    assert calls == []
    assert result["blocked_reason"] == "final_action_forbidden"
    assert result["unsafe_prevented"] is True


def test_missing_or_rejected_action_gate_prevents_dispatch() -> None:
    calls: list[dict] = []

    missing = _execute(lambda **kwargs: calls.append(kwargs), action_gate={})
    rejected = _execute(lambda **kwargs: calls.append(kwargs), action_gate=_action_gate(allowed=False))

    assert calls == []
    assert missing["blocked_reason"] == "action_gate_missing_or_invalid"
    assert rejected["blocked_reason"] == "action_gate_rejected"


def test_value_hash_mismatch_prevents_dispatch_and_does_not_leak_value() -> None:
    calls: list[dict] = []

    result = _execute(lambda **kwargs: calls.append(kwargs), approved_value="DifferentPrivateValue")

    assert calls == []
    assert result["blocked_reason"] == "approved_value_evidence_mismatch"
    assert "DifferentPrivateValue" not in str(result)
    assert PRIVATE_VALUE not in str(result)


def _dispatched_fill_result() -> dict:
    return _execute(lambda **kwargs: {"success": True})


def test_fill_effect_verification_passes_only_for_changed_matching_value() -> None:
    result = verify_form_text_fill_effect(
        fill_result=_dispatched_fill_result(),
        current_capture_id="capture-current",
        observed_question_id="q1",
        before_value="",
        observed_value=PRIVATE_VALUE,
    )

    assert result["contract_version"] == "form_fill_effect_verification_v1"
    assert result["verified"] is True
    assert result["status"] == "text_fill_effect_verified"
    assert result["value_changed"] is True
    assert result["pii_redacted"] is True
    assert PRIVATE_VALUE not in str(result)


def test_dispatch_success_with_unchanged_field_is_verification_failure() -> None:
    result = verify_form_text_fill_effect(
        fill_result=_dispatched_fill_result(),
        current_capture_id="capture-current",
        observed_question_id="q1",
        before_value=PRIVATE_VALUE,
        observed_value=PRIVATE_VALUE,
    )

    assert result["verified"] is False
    assert "field_value_unchanged" in result["failure_reasons"]


def test_truncated_observed_value_is_verification_failure() -> None:
    result = verify_form_text_fill_effect(
        fill_result=_dispatched_fill_result(),
        current_capture_id="capture-current",
        observed_question_id="q1",
        before_value="",
        observed_value=PRIVATE_VALUE[:-2],
    )

    assert result["verified"] is False
    assert "observed_value_mismatch" in result["failure_reasons"]


def test_wrong_question_or_capture_is_verification_failure() -> None:
    wrong_question = verify_form_text_fill_effect(
        fill_result=_dispatched_fill_result(),
        current_capture_id="capture-current",
        observed_question_id="q2",
        before_value="",
        observed_value=PRIVATE_VALUE,
    )
    wrong_capture = verify_form_text_fill_effect(
        fill_result=_dispatched_fill_result(),
        current_capture_id="capture-new",
        observed_question_id="q1",
        before_value="",
        observed_value=PRIVATE_VALUE,
    )

    assert wrong_question["verified"] is False
    assert "question_id_mismatch" in wrong_question["failure_reasons"]
    assert wrong_capture["verified"] is False
    assert "capture_id_mismatch" in wrong_capture["failure_reasons"]


SELECTED_OPTION = "New Zealand"


def _select_question() -> dict:
    return {
        "contract_version": "form_question_contract_v1",
        "question_id": "q-country",
        "label": "Country",
        "field_type": "select",
        "risk": "ordinary_field",
        "source_capture_id": "capture-closed",
    }


def _select_answer_decision() -> dict:
    return {
        "contract_version": "form_answer_decision_v1",
        "question_id": "q-country",
        "policy": "auto_fill",
        "value_reference": "profile:country",
        "value_hash": hashlib.sha256(SELECTED_OPTION.encode("utf-8")).hexdigest(),
        "value_length": len(SELECTED_OPTION),
        "value_preview": f"<redacted:{len(SELECTED_OPTION)} chars>",
        "pii_redacted": True,
    }


def _select_policy_gate() -> dict:
    return {
        "contract_version": "form_action_gate_decision_v1",
        "question_id": "q-country",
        "policy": "auto_fill",
        "policy_allowed": True,
        "requires_current_grounding": True,
        "requires_action_gate": True,
        "artifact_is_authorization": False,
    }


def _dropdown_candidate(*, capture_id: str = "capture-closed") -> dict:
    return {
        "candidate_id": "country-dropdown",
        "question_id": "q-country",
        "bbox": {"x": 100, "y": 300, "w": 240, "h": 36},
        "click_point": {"x": 220, "y": 318},
        "candidate_freshness": {
            "contract_version": "action_candidate_freshness_v1",
            "capture_id": capture_id,
            "viewport_size": {"width": 1200, "height": 800},
            "source": "windows_uia",
            "freshness": "current_capture",
        },
    }


def _option_candidate(
    *,
    capture_id: str = "capture-open",
    question_id: str = "q-country",
    enabled: bool = True,
    matching_label_count: int = 1,
) -> dict:
    return {
        "candidate_id": "country-option-new-zealand",
        "question_id": question_id,
        "option_label": SELECTED_OPTION,
        "enabled": enabled,
        "matching_label_count": matching_label_count,
        "bbox": {"x": 100, "y": 336, "w": 240, "h": 34},
        "click_point": {"x": 220, "y": 353},
        "candidate_freshness": {
            "contract_version": "action_candidate_freshness_v1",
            "capture_id": capture_id,
            "viewport_size": {"width": 1200, "height": 800},
            "source": "windows_uia",
            "freshness": "current_capture",
        },
    }


def _dropdown_gate(*, semantic_action: str, candidate: dict, allowed: bool = True) -> dict:
    return {
        "contract_version": "pre_click_decision_v1",
        "allowed": allowed,
        "semantic_action": semantic_action,
        "selected_candidate_id": candidate["candidate_id"],
        "selected_click_point": candidate["click_point"],
    }


def _open_dropdown(dispatch, **overrides) -> dict:
    candidate = overrides.pop("candidate", _dropdown_candidate())
    payload = {
        "question": _select_question(),
        "answer_decision": _select_answer_decision(),
        "policy_gate": _select_policy_gate(),
        "candidate": candidate,
        "current_capture_id": "capture-closed",
        "current_viewport_size": {"width": 1200, "height": 800},
        "action_gate": _dropdown_gate(semantic_action="open_dropdown", candidate=candidate),
        "dispatch": dispatch,
    }
    payload.update(overrides)
    return execute_form_dropdown_open(**payload)


def _select_option(dispatch, *, open_result: dict | None = None, **overrides) -> dict:
    candidate = overrides.pop("candidate", _option_candidate())
    payload = {
        "question": _select_question(),
        "answer_decision": _select_answer_decision(),
        "policy_gate": _select_policy_gate(),
        "open_result": open_result or _open_dropdown(lambda **kwargs: {"success": True}),
        "candidate": candidate,
        "current_capture_id": "capture-open",
        "current_viewport_size": {"width": 1200, "height": 800},
        "approved_option": SELECTED_OPTION,
        "action_gate": _dropdown_gate(semantic_action="select_option", candidate=candidate),
        "dispatch": dispatch,
    }
    payload.update(overrides)
    return execute_form_option_select(**payload)


def test_dropdown_open_and_option_select_are_two_fresh_gated_actions() -> None:
    calls: list[tuple[str, dict]] = []

    opened = _open_dropdown(lambda **kwargs: calls.append(("open", kwargs)) or {"success": True})
    selected = _select_option(
        lambda **kwargs: calls.append(("select", kwargs)) or {"success": True},
        open_result=opened,
    )

    assert calls == [
        ("open", {"x": 220, "y": 318}),
        ("select", {"x": 220, "y": 353}),
    ]
    assert opened["capture_id"] == "capture-closed"
    assert selected["capture_id"] == "capture-open"
    assert selected["dispatch_success"] is True
    assert SELECTED_OPTION not in str(selected)


def test_option_select_requires_reobserve_after_dropdown_open() -> None:
    calls: list[dict] = []
    opened = _open_dropdown(lambda **kwargs: {"success": True})
    stale_candidate = _option_candidate(capture_id="capture-closed")

    result = _select_option(
        lambda **kwargs: calls.append(kwargs),
        open_result=opened,
        candidate=stale_candidate,
        current_capture_id="capture-closed",
        action_gate=_dropdown_gate(semantic_action="select_option", candidate=stale_candidate),
    )

    assert calls == []
    assert result["blocked_reason"] == "dropdown_reobserve_required"


def test_duplicate_option_label_is_rejected() -> None:
    calls: list[dict] = []
    candidate = _option_candidate(matching_label_count=2)

    result = _select_option(
        lambda **kwargs: calls.append(kwargs),
        candidate=candidate,
        action_gate=_dropdown_gate(semantic_action="select_option", candidate=candidate),
    )

    assert calls == []
    assert result["blocked_reason"] == "option_label_ambiguous"


def test_option_owned_by_different_question_is_rejected() -> None:
    calls: list[dict] = []
    candidate = _option_candidate(question_id="q-other")

    result = _select_option(
        lambda **kwargs: calls.append(kwargs),
        candidate=candidate,
        action_gate=_dropdown_gate(semantic_action="select_option", candidate=candidate),
    )

    assert calls == []
    assert result["blocked_reason"] == "option_question_ownership_mismatch"


def test_disabled_option_is_rejected() -> None:
    calls: list[dict] = []
    candidate = _option_candidate(enabled=False)

    result = _select_option(
        lambda **kwargs: calls.append(kwargs),
        candidate=candidate,
        action_gate=_dropdown_gate(semantic_action="select_option", candidate=candidate),
    )

    assert calls == []
    assert result["blocked_reason"] == "option_disabled"


def test_dropdown_dispatch_success_without_observed_selection_is_not_effect_success() -> None:
    selected = _select_option(lambda **kwargs: {"success": True})

    result = verify_form_option_select_effect(
        select_result=selected,
        current_capture_id="capture-after-select",
        observed_question_id="q-country",
        observed_value="Australia",
    )

    assert result["verified"] is False
    assert "observed_option_mismatch" in result["failure_reasons"]


def test_dropdown_effect_requires_new_capture_and_matching_selected_option() -> None:
    selected = _select_option(lambda **kwargs: {"success": True})

    verified = verify_form_option_select_effect(
        select_result=selected,
        current_capture_id="capture-after-select",
        observed_question_id="q-country",
        observed_value=SELECTED_OPTION,
    )
    stale = verify_form_option_select_effect(
        select_result=selected,
        current_capture_id="capture-open",
        observed_question_id="q-country",
        observed_value=SELECTED_OPTION,
    )

    assert verified["verified"] is True
    assert verified["status"] == "option_select_effect_verified"
    assert stale["verified"] is False
    assert "selection_reobserve_required" in stale["failure_reasons"]


def _choice_question(*, field_type: str = "radio") -> dict:
    return {
        "contract_version": "form_question_contract_v1",
        "question_id": "q-choice",
        "label": "Preferred contact",
        "field_type": field_type,
        "risk": "ordinary_field",
        "source_capture_id": "capture-choice",
    }


def _choice_answer(value: str) -> dict:
    return {
        "contract_version": "form_answer_decision_v1",
        "question_id": "q-choice",
        "policy": "auto_fill",
        "value_reference": "reviewed:choice",
        "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "value_length": len(value),
        "value_preview": f"<redacted:{len(value)} chars>",
        "pii_redacted": True,
    }


def _choice_policy_gate() -> dict:
    gate = _policy_gate()
    gate["question_id"] = "q-choice"
    return gate


def _choice_candidate(
    *,
    value: str,
    checked: bool = False,
    enabled: bool = True,
    matching_label_count: int = 1,
    question_id: str = "q-choice",
    capture_id: str = "capture-choice",
) -> dict:
    return {
        "candidate_id": "choice-control",
        "question_id": question_id,
        "option_value": value,
        "checked": checked,
        "enabled": enabled,
        "matching_label_count": matching_label_count,
        "bbox": {"x": 100, "y": 420, "w": 180, "h": 36},
        "click_point": {"x": 118, "y": 438},
        "candidate_freshness": {
            "contract_version": "action_candidate_freshness_v1",
            "capture_id": capture_id,
            "viewport_size": {"width": 1200, "height": 800},
            "source": "windows_uia",
            "freshness": "current_capture",
        },
    }


def _execute_choice(
    dispatch,
    *,
    field_type: str,
    approved_value: str,
    expected_checked: bool = True,
    semantic_action: str,
    candidate: dict | None = None,
) -> dict:
    selected = candidate or _choice_candidate(value=approved_value)
    return execute_form_choice_select(
        question=_choice_question(field_type=field_type),
        answer_decision=_choice_answer(approved_value),
        policy_gate=_choice_policy_gate(),
        candidate=selected,
        current_capture_id="capture-choice",
        current_viewport_size={"width": 1200, "height": 800},
        approved_value=approved_value,
        expected_checked=expected_checked,
        action_gate=_dropdown_gate(semantic_action=semantic_action, candidate=selected),
        semantic_action=semantic_action,
        dispatch=dispatch,
    )


def test_radio_and_checkbox_dispatch_one_gated_click() -> None:
    calls: list[tuple[str, dict]] = []

    radio = _execute_choice(
        lambda **kwargs: calls.append(("radio", kwargs)) or {"success": True},
        field_type="radio",
        approved_value="Email",
        semantic_action="select_radio",
    )
    checkbox = _execute_choice(
        lambda **kwargs: calls.append(("checkbox", kwargs)) or {"success": True},
        field_type="checkbox",
        approved_value="true",
        semantic_action="toggle_checkbox",
    )

    assert calls == [("radio", {"x": 118, "y": 438}), ("checkbox", {"x": 118, "y": 438})]
    assert radio["dispatch_success"] is True
    assert checkbox["dispatch_success"] is True
    assert "Email" not in str(radio)


def test_already_selected_choice_does_not_dispatch() -> None:
    calls: list[dict] = []
    candidate = _choice_candidate(value="Email", checked=True)

    result = _execute_choice(
        lambda **kwargs: calls.append(kwargs),
        field_type="radio",
        approved_value="Email",
        semantic_action="select_radio",
        candidate=candidate,
    )

    assert calls == []
    assert result["status"] == "already_satisfied"
    assert result["action_required"] is False


def test_disabled_duplicate_or_wrong_owner_choice_is_rejected() -> None:
    calls: list[dict] = []

    disabled = _execute_choice(
        lambda **kwargs: calls.append(kwargs),
        field_type="radio",
        approved_value="Email",
        semantic_action="select_radio",
        candidate=_choice_candidate(value="Email", enabled=False),
    )
    duplicate = _execute_choice(
        lambda **kwargs: calls.append(kwargs),
        field_type="radio",
        approved_value="Email",
        semantic_action="select_radio",
        candidate=_choice_candidate(value="Email", matching_label_count=2),
    )
    wrong_owner = _execute_choice(
        lambda **kwargs: calls.append(kwargs),
        field_type="checkbox",
        approved_value="true",
        semantic_action="toggle_checkbox",
        candidate=_choice_candidate(value="true", question_id="q-other"),
    )

    assert calls == []
    assert disabled["blocked_reason"] == "choice_disabled"
    assert duplicate["blocked_reason"] == "choice_label_ambiguous"
    assert wrong_owner["blocked_reason"] == "choice_question_ownership_mismatch"


def test_choice_effect_requires_new_capture_after_dispatch() -> None:
    selected = _execute_choice(
        lambda **kwargs: {"success": True},
        field_type="checkbox",
        approved_value="true",
        semantic_action="toggle_checkbox",
    )

    verified = verify_form_choice_select_effect(
        choice_result=selected,
        current_capture_id="capture-choice-after",
        observed_question_id="q-choice",
        observed_checked=True,
    )
    stale = verify_form_choice_select_effect(
        choice_result=selected,
        current_capture_id="capture-choice",
        observed_question_id="q-choice",
        observed_checked=True,
    )

    assert verified["verified"] is True
    assert stale["verified"] is False
    assert "choice_reobserve_required" in stale["failure_reasons"]


def test_choice_dispatch_success_with_wrong_checked_state_fails_verification() -> None:
    selected = _execute_choice(
        lambda **kwargs: {"success": True},
        field_type="radio",
        approved_value="Email",
        semantic_action="select_radio",
    )

    result = verify_form_choice_select_effect(
        choice_result=selected,
        current_capture_id="capture-choice-after",
        observed_question_id="q-choice",
        observed_checked=False,
    )

    assert result["verified"] is False
    assert "observed_checked_state_mismatch" in result["failure_reasons"]
