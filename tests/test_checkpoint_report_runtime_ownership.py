from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.application_profiles.seek.learn_artifacts import build_seek_learn_artifacts
from app.learn.path_graph_artifacts import build_seek_runtime_path_graph_export


ROOT = Path(__file__).resolve().parents[1]


def _synthetic_seek_graph() -> dict:
    def event(index: int) -> dict:
        return {
            "index": index,
            "job_id": f"synthetic-job-{index}",
            "card": {
                "title": f"Synthetic role {index}",
                "company": "Synthetic Co",
                "location": "Auckland",
                "card_bbox": {"x": 24, "y": 400 + index * 12, "w": 410, "h": 220},
                "click_point": {"x": 220, "y": 510 + index * 12},
            },
            "detail_read": {
                "title": f"Synthetic role {index}",
                "company": "Synthetic Co",
                "complete": True,
            },
        }

    artifact = build_seek_learn_artifacts(
        {
            "contract_version": "seek_mvp_run_report_v1",
            "jobs_seen": 5,
            "jobs_opened": 5,
            "jobs_fully_read": 5,
            "submit_clicks": 0,
            "final_submissions": 0,
            "accuracy_summary": {
                "status": "pass",
                "post_click_layout_drift_count": 0,
                "wrong_scope_scroll_count": 0,
            },
            "traversal_steps": [event(index) for index in range(5)],
        }
    )
    return build_seek_runtime_path_graph_export(artifact)["runtime_path_graph"]


def test_checkpoint_report_uses_headless_runtime_for_safe_validation(tmp_path: Path) -> None:
    graph = json.dumps(_synthetic_seek_graph())
    probe = f'''\
import json
import socket
import sys
import builtins
from pathlib import Path

root = Path({str(ROOT)!r})
sys.path.insert(0, str(root))
blocked_legacy_prefixes = ("app.main", "app.api.panel", "app.web_panel")
original_import = builtins.__import__


def reject_legacy_import(name, globals=None, locals=None, fromlist=(), level=0):
    if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked_legacy_prefixes):
        raise AssertionError("safe validation imported legacy module: " + name)
    return original_import(name, globals, locals, fromlist, level)


builtins.__import__ = reject_legacy_import
from app.api import execute as execute_api


def reject_side_effect(*args, **kwargs):
    raise AssertionError("safe validation attempted a low-level side effect")


def reject_network(*args, **kwargs):
    raise AssertionError("safe validation attempted network access")

execute_api.dispatch_recognition_plan = reject_side_effect
execute_api.dispatch_scroll = reject_side_effect
execute_api.dispatch_type_text = reject_side_effect
socket.create_connection = reject_network

from scripts.learn_execute_checkpoint_report import run_seek_safe_validation
from app.api.application import create_runtime_app

application = create_runtime_app()
assert not any(route.path.startswith("/panel") for route in application.routes)
assert not {{"app.main", "app.api.panel", "app.web_panel"}} & sys.modules.keys()
report = run_seek_safe_validation(json.loads({graph!r}))
assert report["status"] == "pass"
assert report["summary"]["write_actions_clicked"] == 0
assert report["summary"]["submit_clicks"] == 0
assert report["summary"]["final_submissions"] == 0
assert report["summary"]["input_actions_exposed"] == 0
assert all(item["status"] == "pass" for item in report["timeline"])
assert not {{"app.main", "app.api.panel", "app.web_panel"}} & sys.modules.keys()
print(json.dumps({{"headless": True, "low_level_side_effects": False}}))
'''
    environment = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert json.loads(completed.stdout.splitlines()[-1]) == {
        "headless": True,
        "low_level_side_effects": False,
    }
