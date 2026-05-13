from __future__ import annotations

import json

from app.evaluation.uia_smoke_eval import UIASmokeEvalCase, evaluate_cases


def test_uia_smoke_eval_scores_expected_controls(tmp_path) -> None:
    trace = tmp_path / "uia-smoke.json"
    trace.write_text(
        json.dumps(
            {
                "success": True,
                "contract_version": "uia_smoke_trace_v1",
                "result": {
                    "snapshot": {
                        "status": "ok",
                        "control_count": 4,
                        "controls": [
                            {"name": "返回", "control_type": "Button"},
                            {"name": "刷新", "control_type": "Button"},
                            {"name": "https://www.mousetester.cn", "control_type": "Edit"},
                            {"name": "点击此处测试", "control_type": "Button"},
                        ],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = evaluate_cases(
        [
            UIASmokeEvalCase(
                case_id="edge_mousetester",
                trace_path=str(trace),
                min_control_count=4,
                min_button_count=3,
                expected_name_contains=["返回", "刷新", "点击此处测试"],
            )
        ],
        root=tmp_path,
    )

    assert report["summary"]["passed_case_count"] == 1
    assert report["summary"]["pass_rate"] == 1.0
    assert report["results"][0]["facts"]["button_count"] == 3
    assert report["results"][0]["checks"]["name_contains:点击此处测试"]["passed"] is True


def test_uia_smoke_eval_reports_missing_required_name(tmp_path) -> None:
    trace = tmp_path / "uia-smoke.json"
    trace.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "snapshot": {
                        "status": "ok",
                        "control_count": 1,
                        "controls": [{"name": "返回", "control_type": "Button"}],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = evaluate_cases(
        [
            UIASmokeEvalCase(
                case_id="missing_refresh",
                trace_path=str(trace),
                min_control_count=1,
                min_button_count=1,
                expected_name_contains=["刷新"],
            )
        ],
        root=tmp_path,
    )

    assert report["summary"]["passed_case_count"] == 0
    assert report["results"][0]["checks"]["name_contains:刷新"]["passed"] is False
