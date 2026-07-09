from __future__ import annotations

import json
from pathlib import Path

from scripts.smoke_assisted_template_audit_preview_chain import run_audit_preview_chain_smoke


def test_audit_preview_chain_smoke_uses_copy_and_leaves_source_review_record_unchanged(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts" / "case"
    review_dir = artifacts / "assisted_template_review"
    review_dir.mkdir(parents=True)
    graph_path = artifacts / "runtime_path_graph_candidate.json"
    interface_path = artifacts / "interface_map_candidate.json"
    validation_path = artifacts / "validation_report.json"
    package_path = review_dir / "assisted_template_review_package.json"
    suggestions_path = review_dir / "assisted_template_acceptance_suggestions.json"
    simulation_path = review_dir / "assisted_template_acceptance_simulation.json"

    graph_path.write_text(
        json.dumps(
            {
                "contract_version": "runtime_path_graph_candidate_v1",
                "states": [
                    {"state_id": "results", "label": "Results"},
                    {"state_id": "detail", "label": "Detail"},
                ],
                "action_templates": [
                    {
                        "action_template_id": "open_card",
                        "label": "Open card",
                        "semantic_action": "open_detail",
                        "target_entity": "card_region",
                    }
                ],
                "transitions": [
                    {
                        "transition_id": "open_card_transition",
                        "from_state_id": "results",
                        "to_state_id": "detail",
                        "action_template_id": "open_card",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    interface_path.write_text(
        json.dumps(
            {
                "contract_version": "interface_map_candidate_v1",
                "regions": [{"region_id": "card_region", "label": "Card region"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    validation_path.write_text(
        json.dumps({"contract_version": "validation_report_v1", "validation_status": "passed_candidate"}),
        encoding="utf-8",
    )
    package_path.write_text(
        json.dumps(
            {
                "contract_version": "assisted_template_review_package_v1",
                "package_status": "ready_for_human_assisted_template_review",
                "review_decision": "approved_for_assisted_template_asset",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "ready_for_runtime_pathgraph_promotion": False,
                "final_submit_forbidden": True,
                "runtime_path_graph_candidate_path": "artifacts/case/runtime_path_graph_candidate.json",
                "interface_map_candidate_path": "artifacts/case/interface_map_candidate.json",
                "validation_report_path": "artifacts/case/validation_report.json",
                "checklist_items": [
                    {"item_type": "state", "item_id": "results", "label": "Results"},
                    {"item_type": "state", "item_id": "detail", "label": "Detail"},
                    {"item_type": "region", "item_id": "card_region", "label": "Card region"},
                    {"item_type": "action", "item_id": "open_card", "label": "Open card"},
                    {"item_type": "transition", "item_id": "open_card_transition", "label": "Open card transition"},
                ],
                "summary": {"ready_for_runtime_pathgraph_promotion": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    suggestions_path.write_text(
        json.dumps(
            {
                "contract_version": "assisted_template_acceptance_suggestions_v1",
                "suggestions": [
                    {
                        "suggestion_id": "linked_acceptance:open_card",
                        "label": "Open card",
                        "recommended_decision": "accepted",
                        "recommended_note": "smoke linked suggestion",
                        "overrides": {
                            "label": "Open card",
                            "semantic_action": "open_detail",
                            "target_entity": "card_region",
                        },
                        "items": [
                            {"item_type": "region", "item_id": "card_region"},
                            {"item_type": "action", "item_id": "open_card"},
                            {"item_type": "state", "item_id": "results"},
                            {"item_type": "state", "item_id": "detail"},
                            {"item_type": "transition", "item_id": "open_card_transition"},
                        ],
                    }
                ],
                "summary": {"suggestion_count": 1},
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "ready_for_runtime_pathgraph_promotion": False,
                "final_submit_forbidden": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    simulation_path.write_text(
        json.dumps(
            {
                "contract_version": "assisted_template_acceptance_simulation_v1",
                "simulation_status": "would_make_preflight_ready_for_audit_request_preview",
                "selected_suggestion_ids": ["linked_acceptance:open_card"],
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "ready_for_runtime_pathgraph_promotion": False,
                "final_submit_forbidden": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_audit_preview_chain_smoke(
        package_path="artifacts/case/assisted_template_review/assisted_template_review_package.json",
        out_dir="logs/audit-chain-smoke",
        project_root=tmp_path,
    )

    assert result["contract_version"] == "assisted_template_audit_preview_chain_smoke_v1"
    assert result["smoke_status"] == "passed"
    assert result["source_package_unchanged"] is True
    assert result["source_artifact_writes"] == []
    assert result["copied_artifact_writes"]
    assert "assisted_template_review_record.json" in result["copied_artifact_changes"]
    assert result["review_record"]["decision_summary"]["accepted"] == 5
    assert result["preflight"]["preflight_status"] == "ready_for_audited_runtime_promotion_review"
    assert result["audited_request"]["request_status"] == "ready_for_external_audited_promotion_design"
    assert result["ready_for_runtime_pathgraph_promotion"] is False
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False
    assert not (review_dir / "assisted_template_review_record.json").exists()
