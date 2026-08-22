from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _first_executable_statement(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.stmt:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    assert body, f"{function.name} has no executable statements"
    return body[0]


def test_only_desktop_backend_enters_runtime_input_scope() -> None:
    callers: list[str] = []
    marker = "_runtime_backend_input_scope"
    for root_name in ("app", "scripts"):
        for path in sorted((REPO_ROOT / root_name).rglob("*.py")):
            if path.as_posix().endswith(
                ("app/core/input_controller.py", "app/core/runtime_input_authority.py")
            ):
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


def test_raw_keyboard_fallbacks_check_the_same_authority_context() -> None:
    path = REPO_ROOT / "app" / "core" / "window_manager.py"
    module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    keyboard_functions = []
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_raw_keyboard_call = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "keybd_event"
            for child in ast.walk(node)
        )
        if has_raw_keyboard_call:
            keyboard_functions.append(node)

    assert keyboard_functions
    for function in keyboard_functions:
        has_authority_check = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "runtime_backend_input_is_active"
            for child in ast.walk(function)
        )
        assert has_authority_check, (
            f"{function.name} dispatches raw keyboard input without LiveController authority"
        )


def test_window_manager_mutation_entrypoints_use_the_common_authority_guard() -> None:
    path = REPO_ROOT / "app" / "core" / "window_manager.py"
    module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    manager = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "WindowManager"
    )
    methods = {
        node.name: node
        for node in manager.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in (
        "focus_bound_window",
        "resize_bound_window",
        "maximize_bound_window",
        "_activate_window",
    ):
        statement = _first_executable_statement(methods[name])
        assert isinstance(statement, ast.Expr), (
            f"{name} does not check LiveController authority first"
        )
        call = statement.value
        assert (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "self"
            and call.func.attr == "_ensure_window_mutation_authority"
        ), f"{name} does not check LiveController authority first"


def test_foreground_fallbacks_start_with_fail_closed_authority_branch() -> None:
    path = REPO_ROOT / "app" / "core" / "window_manager.py"
    module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    manager = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "WindowManager"
    )
    methods = {
        node.name: node
        for node in manager.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in (
        "_retry_foreground_activation_with_alt_unlock",
        "_cycle_past_shell_notification_foreground",
    ):
        statement = _first_executable_statement(methods[name])
        assert isinstance(statement, ast.If), f"{name} lacks a leading authority branch"
        assert (
            isinstance(statement.test, ast.UnaryOp)
            and isinstance(statement.test.op, ast.Not)
            and isinstance(statement.test.operand, ast.Call)
            and isinstance(statement.test.operand.func, ast.Name)
            and statement.test.operand.func.id == "runtime_backend_input_is_active"
        ), f"{name} does not test runtime authority before its raw sink"
        assert any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and node.value.value is False
            for node in statement.body
        ), f"{name} does not fail closed without runtime authority"


def test_every_window_manager_raw_mutation_sink_checks_runtime_authority() -> None:
    path = REPO_ROOT / "app" / "core" / "window_manager.py"
    module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    manager = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "WindowManager"
    )
    raw_mutations = {
        "ShowWindow",
        "BringWindowToTop",
        "SetWindowPos",
        "SetForegroundWindow",
        "AttachThreadInput",
        "keybd_event",
    }
    mutation_methods = []
    for method in manager.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_raw_mutation = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in raw_mutations
            for node in ast.walk(method)
        )
        if has_raw_mutation:
            mutation_methods.append(method)

    assert mutation_methods
    for method in mutation_methods:
        has_authority_check = any(
            isinstance(node, ast.Call)
            and (
                (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr == "_ensure_window_mutation_authority"
                )
                or (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "runtime_backend_input_is_active"
                )
            )
            for node in ast.walk(method)
        )
        assert has_authority_check, (
            f"{method.name} contains a raw window mutation sink without runtime authority"
        )
