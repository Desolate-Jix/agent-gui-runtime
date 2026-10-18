from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_save_service_runs_fresh_save_resave_and_publish_without_legacy_panel(
    tmp_path: Path,
) -> None:
    script = r"""
import builtins
import copy
import json
from pathlib import Path
import sys

original_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    candidates = [name, *(name + "." + item for item in (fromlist or ()))]
    for candidate in candidates:
        if candidate in {"app.main", "app.api.panel", "app.web_panel"} or candidate.startswith("app.web_panel."):
            raise AssertionError("legacy import: " + candidate)
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded_import

from app.learn.interface_workflow_lock import interface_workflow_lock
from app.learn.interface_workflow_service import (
    _interface_workflow_save_lock,
    save_interface_workflow_review_transaction,
)
from tests.test_learning_new_asset_offline import fresh_selection_replay_review_asset

root = Path.cwd()
first = fresh_selection_replay_review_asset(root)
resaved = save_interface_workflow_review_transaction(
    first["review"], project_root=root, out_dir=None,
)
assert resaved["workflow_id"] == first["workflow_id"]
assert resaved["application_identity_key"] == first["application_identity_key"]
assert _interface_workflow_save_lock(first["review"]) is interface_workflow_lock(first["workflow_id"])

changed = copy.deepcopy(resaved["saved_review"])
changed["nodes"][0]["display_name"] = "Changed after human confirmation"
stale = save_interface_workflow_review_transaction(changed, project_root=root, out_dir=None)
stale_node = stale["saved_review"]["nodes"][0]
assert stale_node["review_status"] == "needs_human_review"
assert stale_node["reviewed_by_human"] is False
assert not {"app.main", "app.api.panel", "app.web_panel"} & sys.modules.keys()
print(json.dumps({
    "saved": True,
    "resaved": True,
    "published_revision": first["published"]["registry_revision"],
    "stale_confirmation_rejected": True,
    "shared_lock": True,
    "legacy_loaded": False,
}))
"""
    environment = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        QT_QPA_PLATFORM="offscreen",
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "saved": True,
        "resaved": True,
        "published_revision": 1,
        "stale_confirmation_rejected": True,
        "shared_lock": True,
        "legacy_loaded": False,
    }
