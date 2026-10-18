"""正式入口必须直接使用维护中的实现，不依赖退役脚本。"""
import importlib
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_application_owns_the_gui_entrypoint(monkeypatch):
    from app.desktop_review import entrypoint

    application = importlib.import_module("app.desktop_review.application")
    assert Path(application.__file__).resolve() == ROOT / "app/desktop_review/application.py"
    assert not (ROOT / "scripts/start_desktop_review.py").exists()
    calls = []
    monkeypatch.setattr(application, "main", lambda argv: calls.append(argv) or 19)
    assert entrypoint._launch_gui(["--help"]) == 19
    assert calls == [["--help"]]


def test_formal_modules_do_not_import_development_script_implementations():
    for package in ("desktop_review", "agent_link", "vision"):
        for source in (ROOT / "app" / package).rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            names = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
                elif isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
            assert not any(name == "scripts" or name.startswith("scripts.") for name in names), source


def test_formal_worker_is_the_current_source_and_entrypoint(monkeypatch):
    from app.desktop_review import entrypoint
    from app.learn.hybrid.vista_current_source import VISTA_SERVER_PATH

    worker = importlib.import_module("app.vision.model_workers.vista_openai_server")
    expected = ROOT / "app/vision/model_workers/vista_openai_server.py"
    assert Path(worker.__file__).resolve() == expected
    assert (ROOT / VISTA_SERVER_PATH).resolve() == expected
    assert not (ROOT / "scripts/model_servers/vista_openai_server.py").exists()
    calls = []
    monkeypatch.setattr(worker, "main", lambda argv: calls.append(argv) or 23)
    assert entrypoint.main(["--model-worker", "vista", "--help"]) == 23
    assert calls == [["--help"]]
