from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from app.api.application import create_runtime_app


def test_runtime_factory_has_headless_routes_and_health_without_panel() -> None:
    application = create_runtime_app()
    paths = {route.path for route in application.routes}

    assert {
        "/health",
        "/apps",
        "/apps/open",
        "/runtime/architecture",
        "/session/windows",
        "/state",
        "/action/execute_recognition_plan",
        "/runtime/agent/session/start",
        "/execute/observe",
        "/memory/reviewed_interfaces/registry",
        "/vision/ocr_region",
    }.issubset(paths)
    assert "/panel" not in paths
    assert "/panel/assets" not in paths

    response = TestClient(application).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Service is healthy",
        "data": {"status": "ok", "service": "agent-gui-runtime"},
        "error": None,
    }


def test_runtime_factory_creates_independent_headless_instances() -> None:
    first = create_runtime_app()
    second = create_runtime_app()

    assert first is not second
    assert all(not route.path.startswith("/panel") for route in first.routes)
    assert all(not route.path.startswith("/panel") for route in second.routes)


def test_runtime_factory_import_isolated_from_legacy_panel_and_cwd_side_effects(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    probe = tmp_path / "probe.py"
    probe.write_text(
        """from __future__ import annotations
import builtins
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
blocked = {"app.main", "app.api.panel", "app.web_panel"}
original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in blocked or any(name.startswith(value + ".") for value in blocked):
        raise AssertionError(f"legacy import attempted: {name}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
from loguru import logger
calls = []
logger.add = lambda *args, **kwargs: calls.append("add")
logger.remove = lambda *args, **kwargs: calls.append("remove")
before = sorted(item.name for item in Path.cwd().iterdir())
from app.api.application import create_runtime_app
after_import = sorted(item.name for item in Path.cwd().iterdir())
assert calls == []
assert before == after_import
application = create_runtime_app()
paths = {route.path for route in application.routes}
assert {
    "/health",
    "/apps",
    "/runtime/architecture",
    "/session/windows",
    "/state",
    "/action/execute_recognition_plan",
    "/runtime/agent/session/start",
    "/execute/observe",
    "/memory/reviewed_interfaces/registry",
    "/vision/ocr_region",
}.issubset(paths)
assert not any(route.path.startswith("/panel") for route in application.routes)
assert calls == []
print(json.dumps({"factory": create_runtime_app.__name__, "routes": len(paths), "cwd_entries_after_import": after_import}))
""",
        encoding="utf-8",
        newline="\n",
    )

    completed = subprocess.run(
        [sys.executable, str(probe), str(root)],
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        env={
            **__import__("os").environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH": ":memory:",
            "QT_QPA_PLATFORM": "offscreen",
        },
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["factory"] == "create_runtime_app"
    assert payload["routes"] >= 10
