from __future__ import annotations

from app.learn.pathgraph_candidate import _validate_candidate


def test_terminal_blocker_candidate_does_not_require_action_template() -> None:
    reviewed = {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "counts_as_pure_model_generated": False,
        "draft": {
            "blockers": [
                {
                    "blocker_id": "external_application_login_required",
                    "reason": "login_required",
                    "safe_stop_required": True,
                }
            ],
            "verification_rules": [
                {
                    "rule_id": "verify_safe_stop",
                    "expected_decision": "safe_stop",
                }
            ],
        },
    }
    graph = {
        "states": [{"state_id": "external_application_login_required"}],
        "action_templates": [],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
    }
    interface_map = {
        "regions": [{"region_id": "login_required_modal"}],
    }

    report = _validate_candidate(
        reviewed=reviewed,
        graph=graph,
        interface_map=interface_map,
    )

    action_check = next(
        check
        for check in report["checks"]
        if check["check_id"] == "action_templates_present"
    )
    assert action_check["passed"] is True
    assert action_check["details"] == {
        "count": 0,
        "terminal_safe_stop_without_action": True,
    }
    assert report["validation_status"] == "passed_candidate"
