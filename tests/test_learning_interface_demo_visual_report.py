from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.render_learning_interface_demo_visual_report import render_learning_interface_demo_visual_report


def test_visual_report_renders_page_detail_and_readonly_pathgraph(tmp_path: Path) -> None:
    page_detail = tmp_path / "case" / "learn_page_detail_candidate.json"
    scaffold = tmp_path / "case" / "learn_mode_demo_scaffold.json"
    screenshot = tmp_path / "case" / "source.png"
    page_detail.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 200), "white").save(screenshot)
    candidate = {
        "contract_version": "learn_page_detail_candidate_v1",
        "screen_summary": "Sample screen",
        "screenshot_path": str(screenshot),
        "layout": {
            "bounds": {"x": 0, "y": 0, "w": 320, "h": 200},
            "sections": [{"section_id": "main", "label": "Main", "bbox": {"x": 0, "y": 0, "w": 320, "h": 200}}],
            "display_groups": [],
            "regions": [
                {
                    "region_id": "card_1",
                    "region_no": 1,
                    "label": "Card",
                    "role": "card",
                    "bbox": {"x": 20, "y": 30, "w": 100, "h": 90},
                    "possible_operation": {"kind": "read_only"},
                }
            ],
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    page_detail.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    scaffold.write_text(
        json.dumps(
            {
                "contract_version": "learn_mode_demo_scaffold_v1",
                "page_detail_readonly_pathgraph_preview": {
                    "contract_version": "page_detail_readonly_pathgraph_preview_v1",
                    "preview_status": "page_detail_readonly_preview_ready",
                    "page_detail_preview": candidate,
                    "readonly_path_graph_preview": {
                        "contract_version": "readonly_path_graph_preview_v1",
                        "states": [
                            {
                                "state_id": "main",
                                "label": "Main",
                                "bbox": {"x": 0, "y": 0, "w": 320, "h": 200},
                                "region_refs": ["card_1"],
                                "display_only": True,
                            }
                        ],
                        "action_templates": [
                            {
                                "action_template_id": "readonly_card",
                                "target_region_id": "card_1",
                                "semantic_action": "read_only",
                                "display_only": True,
                            }
                        ],
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                        "runtime_pathgraph_promotion": False,
                    },
                },
                "safety": {"display_only": True, "execute_binding_enabled": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chain_report = tmp_path / "chain.json"
    chain_report.write_text(
        json.dumps(
            {
                "contract_version": "learning_interface_chain_smoke_report_v1",
                "cases": [
                    {
                        "case_id": "sample_app",
                        "page_detail": {"report_path": str(page_detail)},
                        "scaffold": {"report_path": str(scaffold)},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = render_learning_interface_demo_visual_report(
        chain_report_path=chain_report,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["case_count"] == 1
    assert report["display_review_ready_count"] == 1
    assert report["summary"]["case_count"] == 1
    assert report["summary"]["display_review_ready_count"] == 1
    assert report["summary"]["runtime_pathgraph_ready_count"] == 0
    assert "not recognition accuracy" in report["summary"]["interpretation"]
    case = report["cases"][0]
    assert case["quality_status"] == "display_review_ready"
    assert case["page_detail_summary"]["spatial_region_count"] == 1
    assert case["page_detail_summary"]["screenshot_backed"] is True
    assert case["readonly_pathgraph_summary"]["state_count"] == 1
    assert case["readonly_pathgraph_summary"]["action_template_count"] == 1
    assert case["readonly_pathgraph_summary"]["screenshot_backed"] is True
    assert case["readonly_pathgraph_diagram_summary"]["state_count"] == 1
    assert case["readonly_pathgraph_diagram_summary"]["action_template_count"] == 1
    assert (tmp_path / case["page_detail_preview_path"]).exists()
    assert (tmp_path / case["readonly_pathgraph_preview_path"]).exists()
    assert (tmp_path / case["readonly_pathgraph_diagram_path"]).exists()
    assert (tmp_path / report["contact_sheet_path"]).exists()
    assert report["safety"]["execute_binding_enabled"] is False
