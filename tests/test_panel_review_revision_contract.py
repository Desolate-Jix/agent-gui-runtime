from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.learn.interface_workflow_review import build_interface_node_review_revision


def test_panel_confirmation_revision_matches_server_for_region_action_edit() -> None:
    review = {
        "contract_version": "single_application_workflow_review_v1",
        "workflow": {"workflow_id": "workflow_test", "entry_node_id": "node_home"},
        "nodes": [
            {
                "node_id": "node_home",
                "display_name": "SEEK homepage",
                "surface_type": "list",
                "state_signature": "home-state",
                "source_paths": [
                    "artifacts/interface-workflow-reviews/workflow_test/node-review-sources/node_home.json",
                    "artifacts/source.json",
                ],
                "evidence": {
                    "source_screenshot_path": "artifacts/interface-workflow-reviews/workflow_test/node-evidence/node_home/source_screenshot_path.png",
                    "review_revision_source_screenshot_path": "artifacts/home.png",
                    "source_screenshot_sha256": "sha-home",
                },
                "regions": [
                    {
                        "region_id": "review_region_review_box_37",
                        "label": "Graduate job card",
                        "role": "card",
                        "bbox": {"x": 54, "y": 507, "w": 552, "h": 276},
                        "semantic_action": "open_detail",
                        "action_type": "open_detail",
                        "human_review": {
                            "bbox_edited": True,
                            "updated_click_point": {"x": 330, "y": 645},
                        },
                    },
                ],
                "controls": [],
                "action_candidates": [],
                "states": [],
                "blockers": [],
                "verification_rules": [],
                "page_details": {"screen": {"summary": "SEEK homepage"}},
            },
        ],
        "edges": [],
    }
    server_revision = build_interface_node_review_revision(review, node_id="node_home")
    node_script = """
const review = JSON.parse(process.argv[1]);
const api = require('./app/web_panel/learning_workflow_review.js');
const state = api.createInterfaceWorkflowReviewState(review);
state.confirmNodeHumanReview('node_home');
process.stdout.write(JSON.stringify(state.snapshot().nodes[0].human_review_confirmation.revision));
"""
    completed = subprocess.run(
        ["node", "-e", node_script, json.dumps(review, ensure_ascii=False)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    panel_revision = json.loads(completed.stdout)
    assert panel_revision == server_revision
