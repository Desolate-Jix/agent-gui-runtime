from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_model_artifact_loading_and_dry_run_do_not_import_legacy_web(tmp_path: Path) -> None:
    marker = tmp_path / 'legacy-blocker-active.txt'
    junit = tmp_path / 'model-artifact.xml'
    (tmp_path / 'sitecustomize.py').write_text(
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
Path(os.environ['R8U_BLOCKER_MARKER']).write_text('active', encoding='utf-8')
''', encoding='utf-8', newline='\n',
    )
    environment = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join((str(tmp_path), str(ROOT))),
        PYTHONUTF8='1',
        PYTHONIOENCODING='utf-8',
        R8U_BLOCKER_MARKER=str(marker),
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=':memory:',
        AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER='1',
        HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1',
        QT_QPA_PLATFORM='offscreen',
    )
    args = ['-q', '-W', 'error::pytest.PytestUnhandledThreadExceptionWarning',
            f'--junitxml={junit}', 'tests/test_model_artifact_loader.py']
    result = subprocess.run(
        [sys.executable, '-c', 'import pytest; raise SystemExit(pytest.main(' + repr(args) + '))'],
        cwd=ROOT, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding='utf-8') == 'active'
    suite = ET.parse(junit)
    assert len(suite.findall('.//testcase')) == 3
    for outcome in ('failure', 'error', 'skipped'):
        assert not suite.findall('.//' + outcome)
