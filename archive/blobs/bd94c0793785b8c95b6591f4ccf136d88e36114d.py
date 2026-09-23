"""执行包预检必须覆盖新增惰性入口，不能派发真实操作。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import check_instant_entrypoints as preflight


ROOT = Path(__file__).resolve().parents[1]
LAZY_MODULES = (
    "app.desktop_review.desktop_command",
    "app.desktop_review.installed_applications",
    "app.desktop_review.session_cleanup",
    "app.desktop_review.application_catalog",
    "app.core.application_launch",
)


def test_isolated_preflight_covers_desktop_launch_and_cleanup_without_execution(tmp_path):
    report = tmp_path / "entrypoints.json"
    result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/check_instant_entrypoints.py"),
                             "--root", str(ROOT), "--report", str(report)],
                            cwd=tmp_path, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    evidence = json.loads(report.read_text(encoding="utf-8"))
    desktop = evidence.get("desktop_operations", [])
    assert {row["operation"] for row in desktop} == {"desktop_capture", "desktop_click"}
    assert all(row["handler_imported"] and row["request_validated"] and not row["handler_executed"]
               for row in desktop)
    launches = evidence.get("launch_selectors", [])
    assert {row["selector"] for row in launches} == {"app_id", "name", "path"}
    assert all(row["handler_imported"] and row["request_validated"] and not row["handler_executed"]
               for row in launches)
    cleanup = evidence.get("session_cleanup", {})
    assert cleanup.get("handler_imported") and cleanup.get("handler_executed") is False
    assert set(LAZY_MODULES) <= evidence["local_module_sources"].keys()
    assert not evidence["input_executed"] and not evidence["screenshots_taken"]
    assert not evidence["model_inference_tested"]


@pytest.mark.parametrize("missing", LAZY_MODULES)
def test_preflight_rejects_missing_new_lazy_dependency(monkeypatch, missing):
    original = preflight.importlib.import_module

    def checked_import(name, *args, **kwargs):
        if name == missing:
            raise ModuleNotFoundError(missing)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(preflight.importlib, "import_module", checked_import)
    with pytest.raises(ModuleNotFoundError, match=missing):
        preflight.check(ROOT)
