from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/smoke/seek_resume_fixture.html"


def test_resume_smoke_case_uses_maintained_test_fixture_without_old_web_source() -> None:
    cases = json.loads(
        (ROOT / "tests/smoke/execute_cases/seek_resume_screening_flow.json").read_text(encoding="utf-8")
    )["cases"]
    assert FIXTURE.is_file()
    assert not (ROOT / "app/web_panel/seek_resume_fixture.html").exists()
    assert cases[0]["app"]["url"] == FIXTURE.as_uri()
    assert all(case["mode"]["dry_run_default"] is True for case in cases)
    assert cases[0]["app"]["window_title_contains"] == "SEEK Resume Screening Fixture"
    html = FIXTURE.read_text(encoding="utf-8")
    assert "<title>SEEK Resume Screening Fixture</title>" in html
    assert 'id="shortlistBtn"' in html
    assert 'id="nextBtn"' in html


def test_smoke_runner_import_remains_independent_from_legacy_web(tmp_path: Path) -> None:
    probe = f"""
import importlib.abc
import sys
sys.path.insert(0, {str(ROOT)!r})
class RejectLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + '.') for prefix in ('app.main', 'app.api.panel', 'app.web_panel')):
            raise AssertionError('legacy dependency: ' + fullname)
sys.meta_path.insert(0, RejectLegacy())
from scripts import execute_smoke_runner as runner
def forbid_transport(*args, **kwargs):
    raise AssertionError('early refusal attempted HTTP transport')
runner._post_json = forbid_transport
try:
    runner.run_case({{'id': 'danger', 'goal': 'Delete item', 'mode': {{'destructive': True}}}}, base_url='http://unused.invalid', execute=True, timeout=1)
except runner.SmokeRunnerError as error:
    assert 'destructive' in str(error)
else:
    raise AssertionError('destructive input was not rejected')
print('legacy-free-import-and-early-refusal')
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "legacy-free-import-and-early-refusal"
