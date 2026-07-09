from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


def test_support_acquisition_status_reports_validated_and_pending_support(tmp_path: Path) -> None:
    from scripts.report_learn_recognition_support_acquisition_status import report_support_acquisition_status

    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (40, 30), "white").save(screenshot)
    screenshot_sha = _sha256_file(screenshot)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "valid_case", "screenshot_path": str(screenshot)},
                    {"case_id": "missing_case", "screenshot_path": str(screenshot)},
                    {"case_id": "missing_target_case", "screenshot_path": str(screenshot)},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    valid_support = tmp_path / "valid_support.json"
    valid_support.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_same_screenshot_support_v1",
                "screenshot_sha256": screenshot_sha,
                "sources": {"uia": {"controls": []}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    missing_support = tmp_path / "missing_support.json"
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_support_acquisition_queue_v1",
                "tasks": [
                    {
                        "case_id": "valid_case",
                        "task_type": "capture_same_screenshot_support",
                        "screenshot_path": str(screenshot),
                        "screenshot_sha256": screenshot_sha,
                        "support_validation_commands": [
                            f"uv run python scripts\\bind_learn_recognition_support_to_manifest.py --manifest {manifest} --case-id valid_case --support {valid_support} --validate-only --json"
                        ],
                        "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False},
                    },
                    {
                        "case_id": "missing_case",
                        "task_type": "capture_same_screenshot_support",
                        "screenshot_path": str(screenshot),
                        "screenshot_sha256": screenshot_sha,
                        "support_validation_commands": [
                            f"uv run python scripts\\bind_learn_recognition_support_to_manifest.py --manifest {manifest} --case-id missing_case --support {missing_support} --validate-only --json"
                        ],
                        "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False},
                    },
                    {
                        "case_id": "missing_target_case",
                        "task_type": "capture_same_screenshot_support",
                        "screenshot_path": str(tmp_path / "missing-target.png"),
                        "screenshot_sha256": "c" * 64,
                        "support_validation_commands": [
                            f"uv run python scripts\\bind_learn_recognition_support_to_manifest.py --manifest {manifest} --case-id missing_target_case --support {tmp_path / 'missing_target_support.json'} --validate-only --json"
                        ],
                        "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = report_support_acquisition_status(queue_path=queue, out=tmp_path / "status.json")

    assert report["contract_version"] == "learn_recognition_support_acquisition_status_v1"
    assert report["summary"] == {
        "task_count": 3,
        "support_artifact_present_count": 1,
        "validated_count": 1,
        "pending_support_count": 2,
        "target_screenshot_ready_count": 2,
        "pending_capture_ready_count": 1,
        "pending_capture_blocked_count": 1,
        "rejected_count": 0,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    by_case = {item["case_id"]: item for item in report["case_statuses"]}
    assert by_case["valid_case"]["status"] == "validated"
    assert by_case["valid_case"]["bindable"] is True
    assert by_case["valid_case"]["validation_result"]["validity"]["status"] == "checksum_match"
    assert by_case["missing_case"]["status"] == "pending_support_capture"
    assert by_case["missing_case"]["bindable"] is False
    assert by_case["missing_case"]["support_exists"] is False
    assert by_case["missing_case"]["capture_readiness"] == {
        "ready_for_reproduction": True,
        "blockers": [],
        "target_screenshot_exists": True,
        "target_screenshot_sha256_match": True,
    }
    assert by_case["missing_target_case"]["status"] == "pending_support_capture"
    assert by_case["missing_target_case"]["capture_readiness"]["ready_for_reproduction"] is False
    assert by_case["missing_target_case"]["capture_readiness"]["blockers"] == ["target_screenshot_missing"]
    written = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert written["summary"]["validated_count"] == 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
