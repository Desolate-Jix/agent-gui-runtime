from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _synthetic_trial(root: Path) -> str:
    image = root / "artifacts/screenshots/synthetic-review.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (320, 240), "white").save(image)
    draft = {
        "contract_version": "learning_template_draft_v1",
        "screen_summary": "Synthetic search surface.", "state_guess": "search_initial",
        "workflow_draft": {
            "states": [{"state_id": "s1", "label": "Search page", "page_type": "search_page"}],
            "action_templates": [{
                "action_template_id": "a1", "label": "Type query", "semantic_action": "fill_field",
                "target_entity": "r1", "bbox": {"x": 10, "y": 20, "w": 80, "h": 24},
                "click_point": {"x": 50, "y": 32},
            }],
            "verification_rules": [],
        },
        "interface_draft": {"regions": [{
            "region_id": "r1", "label": "测试搜索框", "role": "text_input",
            "bbox": {"x": 8, "y": 18, "w": 100, "h": 30}, "click_point": {"x": 58, "y": 33},
        }]},
        "page_details": {"screen": {
            "source_image_path": image.relative_to(root).as_posix(),
            "source_image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        }},
        "safety": {"observation_only": True, "final_submit_blocked": True},
        "learning_source": "observe_model+coordinate_calibration",
    }
    trial = root / "artifacts/learning-runs/synthetic/trial_result.json"
    trial.parent.mkdir(parents=True)
    trial.write_text(json.dumps({
        "contract_version": "learning_model_trial_v1", "app_name": "synthetic",
        "best_attempt_index": 0, "best_learning_draft": draft,
    }, ensure_ascii=False), encoding="utf-8")
    return trial.relative_to(root).as_posix()


@pytest.mark.parametrize("mode", ["roundtrip", "stale_source", "trace_write_failure"])
def test_human_correction_preserves_real_audit_and_scoped_traces_without_panel(
    tmp_path: Path, mode: str,
) -> None:
    trial = _synthetic_trial(tmp_path)
    script = r'''
import importlib.abc
import json
from pathlib import Path
import sys
from PIL import Image

class LegacyBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + ".") for p in ("app.main", "app.api.panel", "app.web_panel")):
            raise ModuleNotFoundError("blocked legacy import: " + fullname)
        return None
sys.meta_path.insert(0, LegacyBlocker())
from scripts import run_learning_human_correction_acceptance as correction
from app.core.runtime_artifacts import runtime_output_directory

root = Path.cwd()
correction.ROOT = root
mode, trial = sys.argv[1:]
output = root / "report"
if mode == "stale_source":
    Image.new("RGB", (320, 240), "black").save(root / "artifacts/screenshots/synthetic-review.png")
elif mode == "trace_write_failure":
    output.mkdir()
    (output / "logs").write_text("file blocks trace directory", encoding="utf-8")
try:
    report = correction.run_human_correction_acceptance(
        source_path=trial, out_dir=output, target_region_id="r1",
    )
except (ValueError, OSError) as error:
    if mode == "stale_source":
        assert isinstance(error, ValueError) and any(word in str(error).lower() for word in ("checksum", "stale", "sha")), str(error)
    elif mode == "trace_write_failure":
        assert isinstance(error, OSError), str(error)
    else:
        raise
    assert not (output / "learning_human_correction_acceptance_report.json").exists()
    assert not list((root / "artifacts").rglob("reviewed_template_candidate.json"))
else:
    assert mode == "roundtrip", "invalid verification produced a report"
    assert report["status"] == "passed", report["audit"]
    assert report["before_bbox"] == {"x": 8, "y": 18, "w": 100, "h": 30}
    assert report["after_bbox"] == {"x": 9, "y": 19, "w": 98, "h": 28}
    assert len(report["audit"]["checks"]) == 9
    assert all(report["audit"]["checks"].values())
    assert report["safety"] == {
        "live_clicks": 0, "live_fills": 0, "live_submits": 0,
        "execute_binding_enabled": False, "runtime_pathgraph_promotion": False,
    }
    assert json.loads(Path(report["report_path"]).read_text(encoding="utf-8")) == report
    paths = []
    for step in ("load", "save", "reload"):
        path = Path(report[step + "_trace_path"])
        assert path.is_relative_to(output / "logs/traces/human-correction")
        trace = json.loads(path.read_text(encoding="utf-8"))
        assert trace["contract_version"] == "learning_human_correction_service_trace_v1"
        assert trace["step"] == step and trace["success"] is True
        assert isinstance(trace["result"], dict)
        assert trace["request"]["source_path"]
        paths.append(path)
    assert len(set(paths)) == 3
    assert "\u6d4b\u8bd5\u641c\u7d22\u6846" in paths[0].read_text(encoding="utf-8")
    assert not (output / "artifacts").exists()
assert runtime_output_directory("logs/traces") == Path("logs/traces")
assert not (root / "logs").exists()
assert not (root / "runtime_state/learning-workflow-runs.json").exists()
assert not {"app.main", "app.api.panel", "app.web_panel"} & sys.modules.keys()
print(json.dumps({"mode": mode, "legacy_loaded": False, "real_model_or_gui_used": False}))
'''
    environment = dict(
        os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:", AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER="1",
        QT_QPA_PLATFORM="offscreen", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
    )
    result = subprocess.run(
        [sys.executable, "-c", script, mode, trial], cwd=tmp_path, env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "mode": mode, "legacy_loaded": False, "real_model_or_gui_used": False,
    }
