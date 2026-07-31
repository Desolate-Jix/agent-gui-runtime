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
