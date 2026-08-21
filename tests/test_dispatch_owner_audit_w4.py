from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_only_desktop_backend_enters_runtime_input_scope() -> None:
    callers: list[str] = []
    marker = "_runtime_backend_input_scope"
    for root_name in ("app", "scripts"):
        for path in sorted((REPO_ROOT / root_name).rglob("*.py")):
            if path.as_posix().endswith("app/core/input_controller.py"):
                continue
            if marker in path.read_text(encoding="utf-8-sig"):
                callers.append(path.relative_to(REPO_ROOT).as_posix())

    assert callers == ["app/agent/desktop_backend.py"]


def test_all_public_input_actions_pass_the_common_authority_guard() -> None:
    path = REPO_ROOT / "app" / "core" / "input_controller.py"
    module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    controller = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "InputController"
    )
    guarded = {
        "move_mouse",
        "mouse_down",
        "mouse_up",
        "click_point",
        "type_text",
        "paste_image",
        "scroll_window",
    }
    methods = {
        node.name: node
        for node in controller.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in sorted(guarded):
        method = methods[name]
        calls = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == "_ensure_windows_input"
        ]
        assert calls, f"{name} bypasses the common LiveController authority guard"
