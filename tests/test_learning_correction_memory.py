from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from app.learn.correction_memory import record_human_review_correction
from app.learn.draft_review import save_reviewed_template_candidate
from app.learn.surface_rule_registry import (
    build_surface_rule_registry_panel_view,
    load_active_surface_rules,
    load_surface_rule_registry,
    transition_surface_rule,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _human_patch(tmp_path: Path) -> dict:
    screenshot = tmp_path / "artifacts" / "screenshots" / "screen.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    screenshot.write_bytes(b"stable screenshot evidence")
    return {
        "contract_version": "human_review_patch_v1",
        "revision": 1,
        "source_draft_path": "artifacts/learning-runs/example/trial_result.json",
        "source_draft_sha256": "draft-sha",
        "screenshot_path": "artifacts/screenshots/screen.png",
        "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
        "reason": "按钮父框没有覆盖完整图标和文字",
        "source": "human_panel_editor_v1",
        "operations": [
            {
                "op": "update_bbox",
                "target_kind": "region",
                "target_id": "region_search",
                "before_bbox": {"x": 20, "y": 20, "w": 40, "h": 20},
                "after_bbox": {"x": 16, "y": 16, "w": 92, "h": 34},
            },
            {
                "op": "update_role",
                "target_kind": "region",
                "target_id": "region_search",
                "before_value": "review_only",
                "after_value": "input",
            },
        ],
        "operation_count": 2,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
    }


def _review_context() -> tuple[dict, dict]:
    draft = {
        "page_details": {
            "surface_adapter_decision": {
                "contract_version": "learning_surface_adapter_decision_v1",
                "adapter_id": "browser",
                "status": "selected_from_visible_evidence",
                "selection_evidence": [
                    {
                        "source": "screen_inventory",
                        "value": "address_bar",
                        "strength": "visible_structure",
                    }
                ],
                "app_name_used_as_final_decision": False,
            }
        }
    }
    review = {
        "source": {
            "source_path": "artifacts/learning-runs/example/trial_result.json",
            "sha256": "draft-sha",
        }
    }
    return review, draft


def test_human_review_correction_is_recorded_as_non_active_candidate(tmp_path: Path) -> None:
    review, draft = _review_context()

    result = record_human_review_correction(
        _human_patch(tmp_path),
        review=review,
        reviewed_draft=draft,
        project_root=tmp_path,
    )

    entry_path = tmp_path / result["correction_entry_path"]
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    registry = load_surface_rule_registry(project_root=tmp_path)

    assert result["status"] == "candidate"
    assert entry["source_type"] == "human_review_patch"
    assert entry["surface"]["adapter_id"] == "browser"
    assert entry["surface"]["app_name_used_as_final_decision"] is False
    assert entry["corrections"][0]["edit_type"] == "update_bbox"
    assert entry["corrections"][0]["before"] == {"x": 20, "y": 20, "w": 40, "h": 20}
    assert entry["corrections"][0]["after"] == {"x": 16, "y": 16, "w": 92, "h": 34}
    assert entry["evidence"]["screenshot_sha256"] == _human_patch(tmp_path)["screenshot_sha256"]
    assert entry["applicability"]["app_name_only_forbidden"] is True
    assert entry["counterexamples"]["required_before_activation"] is True
    assert entry["artifact_is_authorization"] is False
    assert entry["execute_binding_enabled"] is False
    assert registry["rules"][0]["status"] == "candidate"
    assert load_active_surface_rules(project_root=tmp_path) == []


def test_surface_rule_panel_view_exposes_safe_candidate_summary_only(tmp_path: Path) -> None:
    review, draft = _review_context()
    result = record_human_review_correction(
        _human_patch(tmp_path),
        review=review,
        reviewed_draft=draft,
        project_root=tmp_path,
    )

    view = build_surface_rule_registry_panel_view(project_root=tmp_path)

    assert view["contract_version"] == "panel_surface_rule_registry_v1"
    assert view["status_counts"] == {
        "candidate": 1,
        "regression_verified": 0,
        "human_approved": 0,
        "active": 0,
        "rolled_back": 0,
    }
    assert view["candidate_rules_affect_production"] is False
    assert view["production_rule_policy"] == "active_only"
    assert view["model_activation_allowed"] is False
    assert view["no_click_authorization"] is True
    assert view["rules"] == [
        {
            "rule_id": result["rule_id"],
            "status": "candidate",
            "production_eligible": False,
            "surface": {
                "adapter_id": "browser",
                "decision_status": "selected_from_visible_evidence",
            },
            "edit_types": ["update_bbox", "update_role"],
            "correction_count": 2,
            "evidence_status": "valid",
            "created_at": view["rules"][0]["created_at"],
            "updated_at": view["rules"][0]["updated_at"],
            "transition_count": 1,
            "requires_regression_verification": True,
            "requires_human_approval": True,
            "model_activation_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    ]
    serialized = json.dumps(view, ensure_ascii=False)
    assert "按钮父框没有覆盖完整图标和文字" not in serialized
    assert "human_reason" not in serialized
    assert "before_bbox" not in serialized
    assert "after_bbox" not in serialized


def test_surface_rule_lifecycle_rejects_shortcuts_and_model_approval(tmp_path: Path) -> None:
    review, draft = _review_context()
    candidate = record_human_review_correction(
        _human_patch(tmp_path),
        review=review,
        reviewed_draft=draft,
        project_root=tmp_path,
    )

    with pytest.raises(ValueError, match="invalid surface rule transition"):
        transition_surface_rule(
            candidate["rule_id"],
            to_status="active",
            actor_type="human",
            actor_id="reviewer",
            evidence={"reason": "shortcut"},
            project_root=tmp_path,
        )

    transition_surface_rule(
        candidate["rule_id"],
        to_status="regression_verified",
        actor_type="system",
        actor_id="benchmark_runner",
        evidence={"regression_status": "passed", "manifest_paths": ["fixtures/holdout.json"], "failed": 0},
        project_root=tmp_path,
    )
    with pytest.raises(ValueError, match="human approval requires a human actor"):
        transition_surface_rule(
            candidate["rule_id"],
            to_status="human_approved",
            actor_type="model",
            actor_id="review_model",
            evidence={"decision": "approve"},
            project_root=tmp_path,
        )
    with pytest.raises(ValueError, match="human approval requires an explicit scope"):
        transition_surface_rule(
            candidate["rule_id"],
            to_status="human_approved",
            actor_type="human",
            actor_id="reviewer",
            evidence={"decision": "approve"},
            project_root=tmp_path,
        )


def test_only_fully_approved_rules_are_loaded_and_rollback_removes_them(tmp_path: Path) -> None:
    review, draft = _review_context()
    candidate = record_human_review_correction(
        _human_patch(tmp_path),
        review=review,
        reviewed_draft=draft,
        project_root=tmp_path,
    )
    rule_id = candidate["rule_id"]

    transition_surface_rule(
        rule_id,
        to_status="regression_verified",
        actor_type="system",
        actor_id="benchmark_runner",
        evidence={"regression_status": "passed", "manifest_paths": ["fixtures/holdout.json"], "failed": 0},
        project_root=tmp_path,
    )
    transition_surface_rule(
        rule_id,
        to_status="human_approved",
        actor_type="human",
        actor_id="reviewer",
        evidence={"decision": "approve", "scope": "browser_visible_structure_only"},
        project_root=tmp_path,
    )
    with pytest.raises(ValueError, match="counterexample coverage"):
        transition_surface_rule(
            rule_id,
            to_status="active",
            actor_type="human",
            actor_id="reviewer",
            evidence={"activation_reason": "holdout passed"},
            project_root=tmp_path,
        )
    transition_surface_rule(
        rule_id,
        to_status="active",
        actor_type="human",
        actor_id="reviewer",
        evidence={
            "activation_reason": "holdout passed",
            "counterexample_status": "not_applicable",
            "counterexample_reason": "该候选仅约束同类可见浏览器结构",
        },
        project_root=tmp_path,
    )

    active = load_active_surface_rules(project_root=tmp_path)
    assert [item["rule_id"] for item in active] == [rule_id]
    assert active[0]["production_eligible"] is True
    assert active[0]["correction_entry"]["artifact_is_authorization"] is False

    transition_surface_rule(
        rule_id,
        to_status="rolled_back",
        actor_type="human",
        actor_id="reviewer",
        evidence={"rollback_reason": "holdout regression"},
        project_root=tmp_path,
    )
    assert load_active_surface_rules(project_root=tmp_path) == []


def test_active_rule_rejects_tampered_correction_evidence(tmp_path: Path) -> None:
    review, draft = _review_context()
    candidate = record_human_review_correction(
        _human_patch(tmp_path),
        review=review,
        reviewed_draft=draft,
        project_root=tmp_path,
    )
    rule_id = candidate["rule_id"]

    transition_surface_rule(
        rule_id,
        to_status="regression_verified",
        actor_type="system",
        actor_id="benchmark_runner",
        evidence={"regression_status": "passed", "manifest_paths": ["fixtures/holdout.json"], "failed": 0},
        project_root=tmp_path,
    )
    transition_surface_rule(
        rule_id,
        to_status="human_approved",
        actor_type="human",
        actor_id="reviewer",
        evidence={"decision": "approve", "scope": "browser_visible_structure_only"},
        project_root=tmp_path,
    )
    transition_surface_rule(
        rule_id,
        to_status="active",
        actor_type="human",
        actor_id="reviewer",
        evidence={
            "activation_reason": "holdout passed",
            "counterexample_status": "not_applicable",
            "counterexample_reason": "该候选仅约束同类可见浏览器结构",
        },
        project_root=tmp_path,
    )

    entry_path = tmp_path / candidate["correction_entry_path"]
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    entry["evidence"]["human_reason"] = "被篡改的证据"
    _write_json(entry_path, entry)

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_active_surface_rules(project_root=tmp_path)


def test_empty_human_patch_does_not_create_correction_memory(tmp_path: Path) -> None:
    review, draft = _review_context()
    patch = _human_patch(tmp_path)
    patch["operations"] = []
    patch["operation_count"] = 0

    assert (
        record_human_review_correction(
            patch,
            review=review,
            reviewed_draft=draft,
            project_root=tmp_path,
        )
        is None
    )
    assert not (tmp_path / "artifacts" / "learning-correction-memory").exists()


def test_review_save_registers_human_bbox_edit_as_correction_candidate(tmp_path: Path) -> None:
    screenshot = tmp_path / "artifacts" / "screenshots" / "screen.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot)
    screenshot_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    source = tmp_path / "artifacts" / "learning-runs" / "example" / "trial_result.json"
    _write_json(
        source,
        {
            "contract_version": "learning_template_draft_v1",
            "screen_summary": "Browser search surface",
            "states": [{"state_id": "state_1", "label": "Search"}],
            "regions": [
                {
                    "region_id": "region_search",
                    "label": "Search",
                    "role": "review_only",
                    "bbox": {"x": 20, "y": 20, "w": 40, "h": 20},
                }
            ],
            "page_details": {
                "screen": {"image_path": "artifacts/screenshots/screen.png", "image_sha256": screenshot_sha256},
                "surface_adapter_decision": {
                    "adapter_id": "browser",
                    "status": "selected_from_visible_evidence",
                    "selection_evidence": [{"source": "screen_inventory", "value": "address_bar"}],
                    "app_name_used_as_final_decision": False,
                },
            },
        },
    )

    result = save_reviewed_template_candidate(
        source,
        {
            "contract_version": "human_review_patch_v1",
            "screenshot_path": "artifacts/screenshots/screen.png",
            "screenshot_sha256": screenshot_sha256,
            "reason": "扩展为完整输入控件",
            "source": "human_panel_editor_v1",
            "operations": [
                {
                    "op": "update_bbox",
                    "target_kind": "region",
                    "target_id": "region_search",
                    "after_bbox": {"x": 16, "y": 16, "w": 92, "h": 34},
                }
            ],
        },
        project_root=tmp_path,
    )

    memory = result["correction_memory"]
    assert memory["status"] == "candidate"
    assert memory["production_eligible"] is False
    assert (tmp_path / memory["correction_entry_path"]).is_file()
    assert load_active_surface_rules(project_root=tmp_path) == []
