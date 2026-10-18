from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("nodes", "expected_count"),
    [
        pytest.param(["tests/test_continuous_task_handoff.py"], 8, id="handoff"),
        pytest.param(
            [
                "tests/test_deterministic_root_partition.py",
                "tests/test_learning_workflow_stage_worker.py::"
                "test_worker_dispatches_managed_hybrid_fusion_without_model_acquisition",
                "tests/test_learning_workflow_stage_worker.py::"
                "test_managed_hybrid_fusion_enforces_sealed_full_producer_boundary",
            ],
            56,
            id="root-partition-and-selected-fusion",
        ),
    ],
)
def test_retained_handoff_and_partition_contracts_without_legacy_web(
    tmp_path: Path, nodes: list[str], expected_count: int,
) -> None:
    marker = tmp_path / "legacy-blocker-active.txt"
    junit = tmp_path / "retained-contracts.xml"
    (tmp_path / "sitecustomize.py").write_text(
        '''import importlib.abc
import os
import sys
from pathlib import Path

class LegacyBlocker(importlib.abc.MetaPathFinder):
    prefixes = ('app.main', 'app.api.panel', 'app.web_panel')
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in self.prefixes):
            raise ModuleNotFoundError('blocked legacy import: ' + fullname)
        return None

sys.meta_path.insert(0, LegacyBlocker())
Path(os.environ['R8V_BLOCKER_MARKER']).write_text('active', encoding='utf-8')
''', encoding="utf-8", newline="\n",
    )
    environment = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(tmp_path), str(ROOT))),
        PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
        R8V_BLOCKER_MARKER=str(marker),
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER="1",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        QT_QPA_PLATFORM="offscreen",
    )
    # 仅运行明确选定的内存测试，禁止扩大为包含真实历史/子进程的 worker 整套测试。
    args = ["-q", "-W", "error::pytest.PytestUnhandledThreadExceptionWarning",
            f"--junitxml={junit}", *nodes]
    result = subprocess.run(
        [sys.executable, "-c", "import pytest; raise SystemExit(pytest.main(" + repr(args) + "))"],
        cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "active"
    suite = ET.parse(junit)
    assert len(suite.findall(".//testcase")) == expected_count
    for outcome in ("failure", "error", "skipped"):
        assert not suite.findall(".//" + outcome)
