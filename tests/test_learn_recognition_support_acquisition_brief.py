from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


def test_next_support_acquisition_brief_selects_first_pending_capture(tmp_path: Path) -> None:
    from scripts.build_learn_recognition_support_acquisition_brief import build_support_acquisition_brief

    queue = tmp_path / "queue.json"
    status = tmp_path / "status.json"
    screenshot = tmp_path / "artifacts" / "screenshots" / "pending.png"
    screenshot.parent.mkdir(parents=True)
    Image.new("RGB", (320, 180), "white").save(screenshot)
    screenshot_sha = _sha256_file(screenshot)
    queue.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_support_acquisition_queue_v1",
                "tasks": [
                    {
                        "case_id": "ready_case",
                        "priority": 2,
                        "task_type": "repair_bbox_alignment",
                        "screenshot_path": "artifacts/screenshots/ready.png",
                        "screenshot_sha256": "a" * 64,
                        "recommended_commands": ["repair", "bind-ready"],
                        "support_validation_commands": ["validate-ready"],
                        "preflight": {"manual_window_reproduction_required": False},
                        "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False},
                    },
                    {
                        "case_id": "pending_case",
                        "priority": 1,
                        "task_type": "capture_same_screenshot_support",
                        "screenshot_path": "artifacts/screenshots/pending.png",
                        "screenshot_sha256": screenshot_sha,
                        "recommended_commands": ["capture-pending", "bind-pending"],
                        "support_validation_commands": ["validate-pending"],
                        "preflight": {
                            "manual_window_reproduction_required": True,
                            "capture_script_accepts_saved_screenshot": False,
                            "target_screenshot_sha256": screenshot_sha,
                        },
                        "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    status.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_support_acquisition_status_v1",
                "case_statuses": [
                    {"case_id": "ready_case", "status": "validated", "bindable": True},
                    {
                        "case_id": "pending_case",
                        "status": "pending_support_capture",
                        "bindable": False,
                        "support_exists": False,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    brief = build_support_acquisition_brief(queue_path=queue, status_path=status, out=tmp_path / "brief.json")

    assert brief["contract_version"] == "learn_recognition_support_acquisition_brief_v1"
    assert brief["status"] == "target_selected"
    assert brief["selected_case"]["case_id"] == "pending_case"
    assert brief["selected_case"]["task_type"] == "capture_same_screenshot_support"
    assert brief["target_screenshot"] == {
        "path": "artifacts/screenshots/pending.png",
        "sha256": screenshot_sha,
        "actual_sha256": screenshot_sha,
        "sha256_match": True,
        "exists": True,
        "width": 320,
        "height": 180,
        "ready_for_reproduction": True,
        "blockers": [],
    }
    assert brief["operator_steps"] == [
        {
            "step": "reproduce_target_window",
            "manual_window_reproduction_required": True,
            "target_screenshot_path": "artifacts/screenshots/pending.png",
            "target_screenshot_sha256": screenshot_sha,
        },
        {"step": "capture_same_screenshot_support", "command": "capture-pending"},
        {"step": "validate_support_only", "command": "validate-pending", "writes_manifest": False},
        {"step": "bind_per_case_manifest", "command": "bind-pending", "requires_bindable_true": True},
    ]
    assert brief["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_clicks_performed": 0,
        "final_submit_forbidden": True,
    }
    written = json.loads((tmp_path / "brief.json").read_text(encoding="utf-8"))
    assert written["selected_case"]["case_id"] == "pending_case"


def test_next_support_acquisition_brief_blocks_stale_or_missing_target_screenshot(tmp_path: Path) -> None:
    from scripts.build_learn_recognition_support_acquisition_brief import build_support_acquisition_brief

    queue = tmp_path / "queue.json"
    status = tmp_path / "status.json"
    screenshot = tmp_path / "artifacts" / "screenshots" / "stale.png"
    screenshot.parent.mkdir(parents=True)
    Image.new("RGB", (120, 80), "white").save(screenshot)
    actual_sha = _sha256_file(screenshot)
    expected_sha = "b" * 64
    queue.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_support_acquisition_queue_v1",
                "tasks": [
                    {
                        "case_id": "stale_case",
                        "priority": 1,
                        "task_type": "capture_same_screenshot_support",
                        "screenshot_path": "artifacts/screenshots/stale.png",
                        "screenshot_sha256": expected_sha,
                        "recommended_commands": ["capture-stale", "bind-stale"],
                        "support_validation_commands": ["validate-stale"],
                        "preflight": {"manual_window_reproduction_required": True},
                        "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False},
                    },
                    {
                        "case_id": "missing_case",
                        "priority": 2,
                        "task_type": "capture_same_screenshot_support",
                        "screenshot_path": "artifacts/screenshots/missing.png",
                        "screenshot_sha256": expected_sha,
                        "recommended_commands": ["capture-missing", "bind-missing"],
                        "support_validation_commands": ["validate-missing"],
                        "preflight": {"manual_window_reproduction_required": True},
                        "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    status.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_support_acquisition_status_v1",
                "case_statuses": [
                    {"case_id": "stale_case", "status": "pending_support_capture", "bindable": False},
                    {"case_id": "missing_case", "status": "pending_support_capture", "bindable": False},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    stale_brief = build_support_acquisition_brief(queue_path=queue, status_path=status)

    assert stale_brief["selected_case"]["case_id"] == "stale_case"
    assert stale_brief["target_screenshot"]["exists"] is True
    assert stale_brief["target_screenshot"]["actual_sha256"] == actual_sha
    assert stale_brief["target_screenshot"]["sha256_match"] is False
    assert stale_brief["target_screenshot"]["ready_for_reproduction"] is False
    assert stale_brief["target_screenshot"]["blockers"] == ["target_screenshot_sha256_mismatch"]

    status.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_support_acquisition_status_v1",
                "case_statuses": [
                    {"case_id": "stale_case", "status": "validated", "bindable": True},
                    {"case_id": "missing_case", "status": "pending_support_capture", "bindable": False},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    missing_brief = build_support_acquisition_brief(queue_path=queue, status_path=status)

    assert missing_brief["selected_case"]["case_id"] == "missing_case"
    assert missing_brief["target_screenshot"]["exists"] is False
    assert missing_brief["target_screenshot"]["ready_for_reproduction"] is False
    assert missing_brief["target_screenshot"]["blockers"] == ["target_screenshot_missing"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
