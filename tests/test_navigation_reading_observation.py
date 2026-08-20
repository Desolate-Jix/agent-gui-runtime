from __future__ import annotations

import hashlib

import pytest

from app.agent.navigation_reading_observation import (
    build_navigation_runtime_observation,
)


def _screen_reading(*texts: str) -> dict:
    return {
        "contract_version": "screen_reading_v1",
        "trace_path": "logs/traces/vision/current-screen.json",
        "texts": [
            {
                "id": f"text_{index}",
                "text": text,
                "bbox": {"x": 120, "y": 160 + index * 24, "w": 260, "h": 20},
                "confidence": 0.99,
                "source": "rapidocr_onnxruntime",
            }
            for index, text in enumerate(texts)
        ],
        "screen_inventory": {
            "cards": [
                {
                    "id": "card_document",
                    "label": "Navigation Reading Lab",
                    "role": "document",
                    "bbox": {"x": 8, "y": 80, "w": 1184, "h": 760},
                }
            ]
        },
    }


def _interface_specs() -> list[dict]:
    return [
        {
            "interface_id": "lab_feed",
            "surface_type": "content_collection",
            "identity_markers": ["Research Feed Interface"],
        },
        {
            "interface_id": "lab_atlas",
            "surface_type": "finite_detail",
            "identity_markers": ["Atlas Reliability Report Interface"],
            "read_target": {
                "content_id": "lab_atlas:report",
                "bottom_markers": ["ATLAS REPORT END"],
            },
        },
    ]


def test_builds_current_observation_from_current_screen_evidence(tmp_path) -> None:
    image_path = tmp_path / "current.png"
    image_path.write_bytes(b"current screenshot")

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading(
            "Atlas Reliability Report Interface",
            "Evidence freshness requires a current capture.",
        ),
        interface_specs=_interface_specs(),
    )

    expected_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
    assert record["observation"] == {
        "contract_version": "current_interface_observation_v1",
        "interface_id": "lab_atlas",
        "surface_type": "finite_detail",
        "capture_id": f"capture-{expected_sha[:16]}",
        "screenshot_path": str(image_path.resolve()),
        "screenshot_sha256": expected_sha,
        "trace_path": "logs/traces/vision/current-screen.json",
    }
    assert record["resolved_read_targets"]["lab_atlas:report"] == {
        "target_container_id": "lab_atlas:report",
        "bbox": {"x": 8, "y": 80, "w": 1184, "h": 760},
        "scroll_scope": "page",
        "target_pane": "page",
        "wheel_clicks": 5,
    }
    assert record["reached_bottom"] is False
    assert record["ocr_result"]["items"][0]["text"] == (
        "Atlas Reliability Report Interface"
    )


def test_marks_finite_detail_complete_only_from_current_bottom_marker(
    tmp_path,
) -> None:
    image_path = tmp_path / "bottom.png"
    image_path.write_bytes(b"bottom screenshot")

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading(
            "Atlas Reliability Report Interface",
            "ATLAS REPORT END",
        ),
        interface_specs=_interface_specs(),
    )

    assert record["reached_bottom"] is True


def test_bottom_marker_matching_tolerates_ocr_whitespace_loss(tmp_path) -> None:
    image_path = tmp_path / "bottom-without-spaces.png"
    image_path.write_bytes(b"bottom screenshot without spaces")

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading(
            "Atlas Reliability Report Interface",
            "ATLASREPORTEND",
        ),
        interface_specs=_interface_specs(),
    )

    assert record["reached_bottom"] is True


def test_canonicalizes_interface_word_only_for_identity_matching(tmp_path) -> None:
    image_path = tmp_path / "ocr-identity.png"
    image_path.write_bytes(b"ocr identity screenshot")

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading("Research Feed lnterface"),
        interface_specs=_interface_specs(),
    )

    assert record["observation"]["interface_id"] == "lab_feed"


def test_identity_marker_set_tolerates_ocr_whitespace_loss(tmp_path) -> None:
    image_path = tmp_path / "summary-without-marker-spaces.png"
    image_path.write_bytes(b"summary screenshot without marker spaces")
    specs = _interface_specs()
    specs.append(
        {
            "interface_id": "lab_summary",
            "surface_type": "summary",
            "identity_marker_sets": [
                ["Decision Summary Interface", "WORKFLOW COMPLETE SAFE STOP"],
            ],
        }
    )

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading(
            "Decision Summary Interface",
            "WORKFLOW COMPLETESAFESTOP",
        ),
        interface_specs=specs,
    )

    assert record["observation"]["interface_id"] == "lab_summary"


def test_accepts_reviewed_alternative_identity_marker_set_after_scroll(tmp_path) -> None:
    image_path = tmp_path / "scrolled-detail.png"
    image_path.write_bytes(b"scrolled detail screenshot")
    specs = _interface_specs()
    specs[1]["identity_marker_sets"] = [
        ["Atlas Reliability Report Interface"],
        ["?stage=atlas"],
    ]

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading(
            "127.0.0.1:8899/?stage=atlas",
            "Atlas section 4",
        ),
        interface_specs=specs,
    )

    assert record["observation"]["interface_id"] == "lab_atlas"


def test_preserves_expected_identity_when_scroll_hides_all_identity_markers(
    tmp_path,
) -> None:
    image_path = tmp_path / "scrolled-feed-without-title.png"
    image_path.write_bytes(b"scrolled feed screenshot without title")

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading(
            "Dynamic collection item 4",
            "Dynamic collection item 5",
        ),
        interface_specs=_interface_specs(),
        expected_interface_id="lab_feed",
    )

    assert record["observation"]["interface_id"] == "lab_feed"
    assert record["observation"]["identity_resolution"] == {
        "method": "verified_scroll_continuity",
        "expected_interface_id": "lab_feed",
    }


def test_current_identity_evidence_overrides_expected_scroll_identity(tmp_path) -> None:
    image_path = tmp_path / "different-interface-after-scroll.png"
    image_path.write_bytes(b"different interface screenshot")

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading("Atlas Reliability Report Interface"),
        interface_specs=_interface_specs(),
        expected_interface_id="lab_feed",
    )

    assert record["observation"]["interface_id"] == "lab_atlas"
    assert "identity_resolution" not in record["observation"]


def test_rejects_ambiguous_interface_identity(tmp_path) -> None:
    image_path = tmp_path / "ambiguous.png"
    image_path.write_bytes(b"ambiguous screenshot")

    with pytest.raises(ValueError, match="ambiguous current interface"):
        build_navigation_runtime_observation(
            capture={
                "image_path": str(image_path),
                "image_width": 1200,
                "image_height": 900,
            },
            screen_reading=_screen_reading(
                "Research Feed Interface",
                "Atlas Reliability Report Interface",
            ),
            interface_specs=_interface_specs(),
        )


def test_expected_target_resolves_only_when_it_is_visibly_matched(tmp_path) -> None:
    image_path = tmp_path / "background-and-target-visible.png"
    image_path.write_bytes(b"background and target visible")
    specs = [
        {
            "interface_id": "results",
            "surface_type": "content_collection",
            "identity_markers": ["Shared job title"],
        },
        {
            "interface_id": "detail",
            "surface_type": "detail",
            "identity_marker_sets": [["Shared job title", "Apply"]],
        },
    ]

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading("Shared job title", "Apply"),
        interface_specs=specs,
        expected_interface_id="detail",
    )

    assert record["observation"]["interface_id"] == "detail"
    assert record["observation"]["identity_resolution"] == {
        "method": "expected_target_among_visible_matches",
        "expected_interface_id": "detail",
    }


def test_identity_matching_ignores_browser_chrome_outside_document_bbox(
    tmp_path,
) -> None:
    image_path = tmp_path / "browser-tab-title.png"
    image_path.write_bytes(b"browser screenshot with inactive tab title")
    screen_reading = _screen_reading("Current results interface")
    screen_reading["texts"].insert(
        0,
        {
            "id": "inactive_tab_title",
            "text": "Selected detail interface",
            "bbox": {"x": 420, "y": 16, "w": 240, "h": 24},
            "confidence": 0.99,
            "source": "rapidocr_onnxruntime",
        },
    )

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=screen_reading,
        interface_specs=[
            {
                "interface_id": "results",
                "surface_type": "content_collection",
                "identity_markers": ["Current results interface"],
            },
            {
                "interface_id": "detail",
                "surface_type": "detail",
                "identity_markers": ["Selected detail interface"],
            },
        ],
    )

    assert record["observation"]["interface_id"] == "results"
    assert record["ocr_result"]["items"][0]["text"] == (
        "Selected detail interface"
    )


def test_foreground_modal_identity_takes_precedence_over_visible_background(
    tmp_path,
) -> None:
    image_path = tmp_path / "modal-over-background.png"
    image_path.write_bytes(b"modal over background screenshot")
    specs = [
        {
            "interface_id": "workspace",
            "surface_type": "navigation_hub",
            "identity_markers": ["Operations Workspace Interface"],
        },
        {
            "interface_id": "policy_modal",
            "surface_type": "modal_dialog",
            "identity_markers": ["Policy Dialog Interface"],
        },
    ]

    record = build_navigation_runtime_observation(
        capture={
            "image_path": str(image_path),
            "image_width": 1200,
            "image_height": 900,
        },
        screen_reading=_screen_reading(
            "Operations Workspace Interface",
            "Policy Dialog Interface",
        ),
        interface_specs=specs,
    )

    assert record["observation"]["interface_id"] == "policy_modal"
    assert record["observation"]["surface_type"] == "modal_dialog"


def test_multiple_foreground_overlay_matches_remain_ambiguous(tmp_path) -> None:
    image_path = tmp_path / "ambiguous-overlays.png"
    image_path.write_bytes(b"ambiguous overlay screenshot")
    specs = [
        {
            "interface_id": "dialog_a",
            "surface_type": "modal_dialog",
            "identity_markers": ["First Dialog"],
        },
        {
            "interface_id": "dialog_b",
            "surface_type": "popup",
            "identity_markers": ["Second Dialog"],
        },
    ]

    with pytest.raises(ValueError, match="ambiguous current interface"):
        build_navigation_runtime_observation(
            capture={
                "image_path": str(image_path),
                "image_width": 1200,
                "image_height": 900,
            },
            screen_reading=_screen_reading("First Dialog", "Second Dialog"),
            interface_specs=specs,
        )


def test_requires_current_document_bbox_for_read_target(tmp_path) -> None:
    image_path = tmp_path / "missing-document.png"
    image_path.write_bytes(b"missing document screenshot")
    result = _screen_reading("Atlas Reliability Report Interface")
    result["screen_inventory"]["cards"] = []

    with pytest.raises(ValueError, match="document bbox"):
        build_navigation_runtime_observation(
            capture={
                "image_path": str(image_path),
                "image_width": 1200,
                "image_height": 900,
            },
            screen_reading=result,
            interface_specs=_interface_specs(),
        )
