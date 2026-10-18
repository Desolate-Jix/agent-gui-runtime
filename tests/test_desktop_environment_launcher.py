import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_launcher_reports_missing_dependencies_before_importing_gui_or_creating_state(tmp_path):
    state, review = tmp_path / "inbox.json", tmp_path / "review"
    environment = dict(os.environ, AGENT_LINK_REVIEWER_TOKEN="private-launcher-token")
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "app/desktop_review/application.py"),
         "--state-path", str(state), "--review-root", str(review)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 2
    report = json.loads(result.stderr)
    assert report["code"] == "desktop_dependencies_missing"
    assert report["environment"]["profile"] == "desktop_review"
    assert "PySide6" in report["environment"]["missing_modules"]
    assert report["environment"]["runtime_verified"] is False
    assert "check_desktop_environment.py" in report["next_action"]
    assert "private-launcher-token" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert not list(tmp_path.iterdir())


def test_launcher_help_is_available_without_dependencies_or_state(tmp_path):
    result = subprocess.run([sys.executable, "-S", str(ROOT / "app/desktop_review/application.py"), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0
    assert "--review-root" in result.stdout
    assert not result.stderr
    assert not list(tmp_path.iterdir())
