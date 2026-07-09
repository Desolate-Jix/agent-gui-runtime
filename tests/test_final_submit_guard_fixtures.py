from __future__ import annotations

import pytest

from app.gate.danger import scoped_final_submit_visible_blocker


FINAL_SUBMIT_FIXTURES = [
    ("submit_application", "Submit application", "button", {"x": 100, "y": 700, "w": 180, "h": 44}),
    ("send_application", "Send application", "button", {"x": 100, "y": 700, "w": 180, "h": 44}),
    ("complete", "Complete", "button", {"x": 100, "y": 700, "w": 140, "h": 44}),
    ("apply_now", "Apply now", "button", {"x": 100, "y": 700, "w": 140, "h": 44}),
    ("confirm", "Confirm", "button", {"x": 100, "y": 700, "w": 140, "h": 44}),
    ("review_and_submit", "Review and submit", "button", {"x": 100, "y": 700, "w": 180, "h": 44}),
    ("submit", "Submit", "button", {"x": 100, "y": 700, "w": 120, "h": 44}),
    ("disabled_submit", "Submit application", "button", {"x": 100, "y": 700, "w": 180, "h": 44}),
    ("sticky_footer_submit", "Submit application", "button", {"x": 400, "y": 940, "w": 220, "h": 48}),
    ("modal_submit", "Send application", "button", {"x": 560, "y": 560, "w": 180, "h": 48}),
]


@pytest.mark.parametrize(("case_id", "text", "role", "bbox"), FINAL_SUBMIT_FIXTURES)
def test_final_submit_guard_fixture_suite_blocks_submit_surfaces(case_id: str, text: str, role: str, bbox: dict) -> None:
    container = {"x": 0, "y": 0, "w": 1200, "h": 1000}
    item = {
        "collection": "available_actions",
        "id": case_id,
        "text": text,
        "role": role,
        "bbox": bbox,
        "disabled": case_id == "disabled_submit",
    }

    surface_context = "final_review_submit" if case_id == "review_and_submit" else "final_review"
    blocker = scoped_final_submit_visible_blocker(
        [item],
        active_container=container,
        active_flow_started=True,
        surface_context=surface_context,
    )
    result = {
        "unsafe_prevented": blocker["blocked"],
        "real_clicks": 0,
        "submit_clicks": 0,
        "blocker": blocker,
    }

    assert result["unsafe_prevented"] is True
    assert result["real_clicks"] == 0
    assert result["submit_clicks"] == 0
    assert blocker["matched_items"][0]["id"] == case_id


def test_apply_now_is_not_globally_blocked_outside_active_application_flow() -> None:
    blocker = scoped_final_submit_visible_blocker(
        [
            {
                "collection": "available_actions",
                "id": "seek_apply_entry",
                "text": "Apply now",
                "role": "button",
                "bbox": {"x": 100, "y": 200, "w": 180, "h": 44},
            }
        ],
        active_container={"x": 0, "y": 0, "w": 1200, "h": 1000},
        active_flow_started=False,
    )

    assert blocker["blocked"] is False
    assert blocker["reason"] == "no_scoped_final_submit_visible"


def test_apply_now_is_allowed_in_apply_entry_context() -> None:
    blocker = scoped_final_submit_visible_blocker(
        [
            {
                "collection": "available_actions",
                "id": "seek_apply_entry",
                "text": "Apply now",
                "role": "button",
                "bbox": {"x": 100, "y": 700, "w": 180, "h": 44},
            }
        ],
        active_container={"x": 0, "y": 0, "w": 1200, "h": 1000},
        active_flow_started=True,
        surface_context="apply_entry",
    )

    assert blocker["blocked"] is False
    assert blocker["reason"] == "no_scoped_final_submit_visible"


def test_apply_now_is_blocked_in_final_review_context() -> None:
    blocker = scoped_final_submit_visible_blocker(
        [
            {
                "collection": "available_actions",
                "id": "final_apply_now",
                "text": "Apply now",
                "role": "button",
                "bbox": {"x": 100, "y": 700, "w": 180, "h": 44},
            }
        ],
        active_container={"x": 0, "y": 0, "w": 1200, "h": 1000},
        active_flow_started=True,
        surface_context="final_review",
    )

    assert blocker["blocked"] is True
    assert blocker["matched_items"][0]["id"] == "final_apply_now"
