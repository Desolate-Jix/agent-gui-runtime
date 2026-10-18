from __future__ import annotations

import json
from pathlib import Path


def write_synthetic_agent_prompt_catalog(root: Path) -> Path:
    catalog = root / "artifacts" / "agent_prompts"
    catalog.mkdir(parents=True)
    payload = {
        "contract_version": "agent_prompt_template_v1",
        "prompt_id": "job_suitability_full_jd_v1",
        "title": "Synthetic full-detail review",
        "task": "Evaluate synthetic full job detail",
        "version": "2026-06-29.base",
        "language": "en-NZ",
        "template": "Synthetic review: {{full_job_detail_text}}",
        "variables": ["full_job_detail_text"],
        "output_contract": "job_suitability_decision_v1",
        "safety_notes": ["Synthetic test data only."],
        "app_profile_refs": ["seek"],
    }
    path = catalog / "job_suitability_full_jd_v1.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return root


def write_synthetic_app_profile_catalog(root: Path) -> Path:
    catalog = root / "artifacts" / "app_profiles"
    catalog.mkdir(parents=True)
    payload = {
        "contract_version": "app_profile_v1",
        "app_id": "seek",
        "display_name": "Synthetic SEEK profile",
        "execution_model": "agentic_loop_first",
        "profile_role": "Synthetic test-only application profile.",
        "operation_skills": ["read_full_job_detail"],
        "gate_contracts": [
            "bound_window_match_v1",
            "final_submit_guard_v1",
            "latest_detail_snapshot_v1",
            "ocr_contextual_normalization_v1",
        ],
        "workflow_assets": [{"asset_id": "synthetic-workflow"}],
        "learned_patterns": [
            {"pattern_id": "list_detail_page"},
            {"pattern_id": "long_detail_reading"},
            {"pattern_id": "agent_full_content_review"},
            {"pattern_id": "entry_boundary"},
            {"pattern_id": "multi_step_form"},
            {"pattern_id": "danger_zone_final_submit"},
        ],
        "policy": {"final_submit_default": "forbidden"},
    }
    path = catalog / "seek_app_profile_v1.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return root
