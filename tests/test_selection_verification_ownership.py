from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["load_only", "simulate_review", "replay_rejected"])
def test_selection_verification_uses_maintained_transactions_without_legacy(
    tmp_path: Path, mode: str,
) -> None:
    guard = tmp_path / "import-guard"
    guard.mkdir()
    markers = tmp_path / "guard-markers"
    markers.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import importlib.abc, os, sys\nfrom pathlib import Path\n"
        "class LegacyBlocker(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if any(fullname == p or fullname.startswith(p + '.') for p in ('app.main', 'app.api.panel', 'app.web_panel')):\n"
        "            raise ModuleNotFoundError('blocked legacy import: ' + fullname)\n"
        "        return None\n"
        "sys.meta_path.insert(0, LegacyBlocker())\n"
        "Path(os.environ['SELECTION_VERIFY_GUARD_MARKERS'], str(os.getpid()) + '.txt').write_text('active', encoding='utf-8')\n",
        encoding="utf-8",
    )
    script = r'''
import json
from pathlib import Path
import sys
from pytest import MonkeyPatch
from scripts import verify_learning_selection_review as verification

root = Path.cwd()
mode = sys.argv[1]
if mode == "replay_rejected":
    from tests.test_learning_selection_roundtrip import _payload
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    _, payload = _payload(root)
    trial = persist_selection_review_trial(
        project_root=root, payload=payload, response=run_hybrid_selection_task(payload),
    )
else:
    # 仅替换模型提供者；真实协调、来源保存和审核事务继续执行。
    from tests.test_learning_selection_actual_flow import _fixture, _run
    with MonkeyPatch.context() as patch:
        _, original, order = _fixture(root, patch)
        generated = _run(root, original)
        assert generated["outcome"] == "completed"
        assert order == ["omni", "actor"]
        trial = generated["trial_path"]

verification.ROOT = root
sys.argv = ["verify_learning_selection_review", "--trial", trial, "--out", "verification"]
if mode == "simulate_review":
    sys.argv += ["--simulate-review", "--label", "\u6d4b\u8bd5\u6309\u94ae"]
output = root / "verification"
if mode == "replay_rejected":
    try:
        verification.main()
    except AssertionError:
        assert not (output / "verification.json").exists()
    else:
        raise AssertionError("replay was accepted as actual-model evidence")
else:
    verification.main()
    report = json.loads((output / "verification.json").read_text(encoding="utf-8"))
    assert report["model_origin"] == "actual_model"
    assert report["user_confirmed"] is False
    assert report["artifact_is_authorization"] is False
    assert report["execute_binding_enabled"] is False
    assert report["evidence_schema"] == "learning_selection_verification_service_v1"
    loaded = json.loads((output / "loaded.json").read_text(encoding="utf-8"))
    assert "hybrid_review_projection" in loaded
    assert "success" not in loaded and "data" not in loaded
    if mode == "simulate_review":
        assert report["fresh_process_equal"] is True
        assert report["original_model_proposal_unchanged"] is True
        assert report["learning_regions_consumed"] is True
        assert report["missing_semantics_negative"] == "blocked_missing_semantics"
        saved = json.loads((output / "reviewed-save.json").read_text(encoding="utf-8"))
        graph = json.loads((root / saved["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
        assert graph["states"] == [] and graph["action_templates"] == []
        assert graph["execute_binding_enabled"] is False
    else:
        assert not (output / "reviewed-save.json").exists()
        assert "reviewed_template_candidate_path" not in report
assert not {"app.main", "app.api.panel", "app.web_panel"} & sys.modules.keys()
assert not (root / "runtime_state/learning-workflow-runs.json").exists()
print(json.dumps({"mode": mode, "legacy_loaded": False, "real_provider_used": False}))
'''
    environment = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(guard), str(ROOT))),
        PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER="1",
        QT_QPA_PLATFORM="offscreen", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        SELECTION_VERIFY_GUARD_MARKERS=str(markers),
    )
    result = subprocess.run(
        [sys.executable, "-c", script, mode], cwd=tmp_path, env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "mode": mode, "legacy_loaded": False, "real_provider_used": False,
    }
    assert len(list(markers.glob("*.txt"))) == (2 if mode == "simulate_review" else 1)
