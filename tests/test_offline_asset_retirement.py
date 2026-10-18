from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ElementTree


ROOT = Path(__file__).resolve().parents[1]
SELECTED_TESTS = (
    "tests/test_learning_new_asset_offline.py",
    "tests/test_reviewed_workflow_seek_e2e_v2.py",
)
EXPECTED_TEST_COUNT = 8


def test_offline_asset_contracts_never_import_legacy_web_modules(tmp_path: Path) -> None:
    marker = tmp_path / "legacy-blocker-active.txt"
    junit = tmp_path / "offline-assets.xml"
    (tmp_path / "sitecustomize.py").write_text(
        '''import importlib.abc
import os
import sys
from pathlib import Path


class LegacyBlocker(importlib.abc.MetaPathFinder):
    prefixes = ("app.main", "app.api.panel", "app.web_panel")

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in self.prefixes):
            raise ModuleNotFoundError("blocked legacy import: " + fullname)
        return None


sys.meta_path.insert(0, LegacyBlocker())
Path(os.environ["R8U_LEGACY_BLOCKER_MARKER"]).write_text("active", encoding="utf-8")
''',
        encoding="utf-8",
        newline="\n",
    )
    environment = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(tmp_path), str(ROOT))),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        R8U_LEGACY_BLOCKER_MARKER=str(marker),
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        QT_QPA_PLATFORM="offscreen",
    )
    pytest_args = [
        "-q",
        "-W",
        "error::pytest.PytestUnhandledThreadExceptionWarning",
        f"--junitxml={junit}",
        *SELECTED_TESTS,
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pytest; raise SystemExit(pytest.main(" + repr(pytest_args) + "))",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "active"
    suite = ElementTree.parse(junit).getroot()
    assert len(suite.findall(".//testcase")) == EXPECTED_TEST_COUNT
    assert not suite.findall(".//skipped")
    assert not suite.findall(".//failure")
    assert not suite.findall(".//error")
