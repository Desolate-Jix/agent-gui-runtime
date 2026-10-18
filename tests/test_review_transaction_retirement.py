from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTED_TESTS = (
    'tests/test_reviewed_workflow_v2_api.py',
    'tests/test_reviewed_workflow_publication_ownership.py',
)


def test_review_transaction_core_never_imports_legacy_panel_modules(tmp_path: Path) -> None:
    marker = tmp_path / 'legacy-blocker-active.txt'
    junit = tmp_path / 'selected-tests.xml'
    (tmp_path / 'sitecustomize.py').write_text(
        '''import importlib.abc\nimport os\nimport sys\nfrom pathlib import Path\n\n\nclass LegacyBlocker(importlib.abc.MetaPathFinder):\n    prefixes = (\"app.main\", \"app.api.panel\", \"app.web_panel\")\n\n    def find_spec(self, fullname, path=None, target=None):\n        if any(fullname == prefix or fullname.startswith(prefix + \".\") for prefix in self.prefixes):\n            raise ModuleNotFoundError(\"blocked legacy import: \" + fullname)\n        return None\n\n\nsys.meta_path.insert(0, LegacyBlocker())\nPath(os.environ[\"R8S_LEGACY_BLOCKER_MARKER\"]).write_text(\"active\", encoding=\"utf-8\")\n''',
        encoding='utf-8',
        newline='\n',
    )
    environment = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(tmp_path), str(ROOT))),
        PYTHONUTF8='1',
        PYTHONIOENCODING='utf-8',
        R8S_LEGACY_BLOCKER_MARKER=str(marker),
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=':memory:',
        HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1',
        QT_QPA_PLATFORM='offscreen',
    )
    pytest_args = [
        '-q',
        '-W', 'error::pytest.PytestUnhandledThreadExceptionWarning',
        f'--junitxml={junit}',
        *SELECTED_TESTS,
    ]
    result = subprocess.run(
        [
            sys.executable, '-c',
            'import pytest; raise SystemExit(pytest.main(' + repr(pytest_args) + '))',
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding='utf-8') == 'active'
    suite = ElementTree.parse(junit).getroot()
    assert len(suite.findall('.//testcase')) == 20
    assert not suite.findall('.//skipped')
    assert not suite.findall('.//failure')
    assert not suite.findall('.//error')
