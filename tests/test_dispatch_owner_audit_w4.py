from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

RAW_SCRIPT_GUI_MUTATIONS = {
    "PostMessage",
    "PostMessageW",
    "SendMessage",
    "SendMessageW",
    "CloseWindow",
    "DestroyWindow",
    "SetWindowPos",
    "MoveWindow",
    "ShowWindow",
    "SetForegroundWindow",
    "SendInput",
    "mouse_event",
    "keybd_event",
    "SetCursorPos",
}
RAW_SCRIPT_GUI_MUTATION_ALLOWLIST: set[tuple[str, str, int]] = set()

RAW_APP_GUI_MUTATIONS = {
    *RAW_SCRIPT_GUI_MUTATIONS,
    "AttachThreadInput",
    "BringWindowToTop",
    "EmptyClipboard",
    "SetClipboardData",
    "SetClipboardText",
}
EXPECTED_RAW_APP_GUI_MUTATION_SINKS = {
    ("app/core/input_controller.py", "InputController", "_focus_window"): Counter(
        {"SetForegroundWindow": 1}
    ),
    ("app/core/input_controller.py", "InputController", "_send_mouse_input"): Counter(
        {"SendInput": 1}
    ),
    ("app/core/input_controller.py", "InputController", "_send_key"): Counter(
        {"SendInput": 1}
    ),
    ("app/core/input_controller.py", "InputController", "_set_clipboard_text"): Counter(
        {"EmptyClipboard": 1, "SetClipboardText": 1}
    ),
    (
        "app/core/input_controller.py",
        "InputController",
        "_set_clipboard_image_dib",
    ): Counter({"EmptyClipboard": 1, "SetClipboardData": 1}),
    ("app/core/window_manager.py", "WindowManager", "resize_bound_window"): Counter(
        {"ShowWindow": 1, "SetWindowPos": 1}
    ),
    ("app/core/window_manager.py", "WindowManager", "maximize_bound_window"): Counter(
        {"ShowWindow": 1}
    ),
    ("app/core/window_manager.py", "WindowManager", "_activate_window"): Counter(
        {
            "ShowWindow": 1,
            "AttachThreadInput": 2,
            "BringWindowToTop": 1,
            "SetWindowPos": 2,
            "SetForegroundWindow": 1,
        }
    ),
    (
        "app/core/window_manager.py",
        "WindowManager",
        "_retry_foreground_activation_with_alt_unlock",
    ): Counter({"keybd_event": 2, "SetForegroundWindow": 1}),
    (
        "app/core/window_manager.py",
        "WindowManager",
        "_cycle_past_shell_notification_foreground",
    ): Counter({"keybd_event": 4}),
}


def _scan_raw_script_gui_mutations(scripts_root: Path) -> list[tuple[str, str, int]]:
    violations: list[tuple[str, str, int]] = []
    for path in sorted(scripts_root.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        relative_path = path.relative_to(scripts_root.parent).as_posix()
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                call_name = node.func.id
            else:
                continue
            violation = (relative_path, call_name, node.lineno)
            if (
                call_name in RAW_SCRIPT_GUI_MUTATIONS
                and violation not in RAW_SCRIPT_GUI_MUTATION_ALLOWLIST
            ):
                violations.append(violation)
    return violations


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


def _scan_production_symbol_calls(
    repo_root: Path,
    symbol: str,
) -> list[tuple[str, str | None, str]]:
    callsites: list[tuple[str, str | None, str]] = []
    for root_name in ("app", "scripts"):
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            parents = {
                child: parent
                for parent in ast.walk(module)
                for child in ast.iter_child_nodes(parent)
            }
            for node in ast.walk(module):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    call_name = node.func.id
                else:
                    continue
                if call_name != symbol:
                    continue

                current: ast.AST | None = node
                function: ast.FunctionDef | ast.AsyncFunctionDef | None = None
                owner: str | None = None
                while current is not None:
                    current = parents.get(current)
                    if function is None and isinstance(
                        current, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        function = current
                    elif function is not None and isinstance(current, ast.ClassDef):
                        owner = current.name
                        break
                assert function is not None, (
                    f"{path.relative_to(repo_root).as_posix()}:{node.lineno} "
                    f"calls {symbol} at module scope"
                )
                callsites.append(
                    (path.relative_to(repo_root).as_posix(), owner, function.name)
                )
    return callsites


def _scan_raw_app_gui_mutations(
    app_root: Path,
) -> tuple[
    dict[tuple[str, str | None, str], Counter[str]],
    dict[tuple[str, str | None, str], ast.FunctionDef | ast.AsyncFunctionDef],
]:
    inventory: dict[tuple[str, str | None, str], Counter[str]] = {}
    functions: dict[
        tuple[str, str | None, str], ast.FunctionDef | ast.AsyncFunctionDef
    ] = {}
    for path in sorted(app_root.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(module):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        relative_path = path.relative_to(app_root.parent).as_posix()
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                call_name = node.func.id
            else:
                continue
            if call_name not in RAW_APP_GUI_MUTATIONS:
                continue

            current: ast.AST | None = node
            function: ast.FunctionDef | ast.AsyncFunctionDef | None = None
            owner: str | None = None
            while current is not None:
                current = parents.get(current)
                if function is None and isinstance(
                    current, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    function = current
                elif function is not None and isinstance(current, ast.ClassDef):
                    owner = current.name
                    break

            assert function is not None, (
                f"{relative_path}:{node.lineno} calls {call_name} at module scope"
            )
            key = (relative_path, owner, function.name)
            inventory.setdefault(key, Counter())[call_name] += 1
            functions[key] = function
    return inventory, functions


def _assert_leading_runtime_authority_guard(
    key: tuple[str, str | None, str],
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> None:
    statement = _first_executable_statement(function)
    path, owner, name = key
    if owner == "InputController":
        assert isinstance(statement, ast.Expr), f"{path}:{name} lacks a leading guard"
        call = statement.value
        assert (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "self"
            and call.func.attr == "_ensure_windows_input"
        ), f"{path}:{name} reaches a raw sink before InputController authority"
        return

    if owner == "WindowManager" and name in {
        "_retry_foreground_activation_with_alt_unlock",
        "_cycle_past_shell_notification_foreground",
    }:
        assert isinstance(statement, ast.If), f"{path}:{name} lacks a leading guard"
        assert (
            isinstance(statement.test, ast.UnaryOp)
            and isinstance(statement.test.op, ast.Not)
            and isinstance(statement.test.operand, ast.Call)
            and isinstance(statement.test.operand.func, ast.Name)
            and statement.test.operand.func.id == "runtime_backend_input_is_active"
        ), f"{path}:{name} reaches a raw sink before WindowManager authority"
        assert any(
            isinstance(child, ast.Return)
            and isinstance(child.value, ast.Constant)
            and child.value.value is False
            for child in statement.body
        ), f"{path}:{name} does not fail closed without authority"
        return

    assert owner == "WindowManager", f"unexpected raw mutation owner: {key}"
    assert isinstance(statement, ast.Expr), f"{path}:{name} lacks a leading guard"
    call = statement.value
    assert (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr == "_ensure_window_mutation_authority"
    ), f"{path}:{name} reaches a raw sink before WindowManager authority"


def test_only_desktop_backend_enters_runtime_input_scope() -> None:
    callers = _scan_production_symbol_calls(
        REPO_ROOT,
        "_runtime_backend_input_scope",
    )

    assert callers == [
        ("app/agent/desktop_backend.py", "ExistingWindowsBackendAdapter", "dispatch")
    ]


def test_scope_callsite_scanner_preserves_duplicate_calls(tmp_path: Path) -> None:
    module_path = tmp_path / "app" / "agent" / "desktop_backend.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        "class ExistingWindowsBackendAdapter:\n"
        "    def dispatch(self):\n"
        "        _runtime_backend_input_scope()\n"
        "        _runtime_backend_input_scope()\n",
        encoding="utf-8",
    )

    assert _scan_production_symbol_calls(
        tmp_path,
        "_runtime_backend_input_scope",
    ) == [
        ("app/agent/desktop_backend.py", "ExistingWindowsBackendAdapter", "dispatch"),
        ("app/agent/desktop_backend.py", "ExistingWindowsBackendAdapter", "dispatch"),
    ]


def test_windows_backend_consumes_authority_before_entering_input_scope() -> None:
    path = REPO_ROOT / "app" / "agent" / "desktop_backend.py"
    module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    backend = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ExistingWindowsBackendAdapter"
    )
    dispatch = next(
        node
        for node in backend.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "dispatch"
    )
    parents = {
        child: parent
        for parent in ast.walk(dispatch)
        for child in ast.iter_child_nodes(parent)
    }

    consume_calls = [
        node
        for node in ast.walk(dispatch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_consume_authority"
    ]
    scope_calls = [
        node
        for node in ast.walk(dispatch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_runtime_backend_input_scope"
    ]
    assert len(consume_calls) == 1
    assert len(scope_calls) == 1

    first = _first_executable_statement(dispatch)
    assert isinstance(first, ast.Expr) and first.value is consume_calls[0], (
        "ExistingWindowsBackendAdapter.dispatch must consume authority unconditionally first"
    )

    scope_call = scope_calls[0]
    with_item = parents.get(scope_call)
    assert isinstance(with_item, ast.withitem)
    scope_with = parents.get(with_item)
    assert isinstance(scope_with, ast.With)

    def top_level_statement(node: ast.AST) -> ast.AST:
        current = node
        while parents.get(current) is not dispatch:
            current = parents[current]
        return current

    consume_statement = top_level_statement(consume_calls[0])
    scope_statement = top_level_statement(scope_call)
    assert dispatch.body.index(consume_statement) < dispatch.body.index(scope_statement)


def test_only_live_controller_mints_execution_authority() -> None:
    assert _scan_production_symbol_calls(
        REPO_ROOT,
        "_mint_execution_authority",
    ) == [
        ("app/agent/live_controller.py", "LiveController", "_execute_accepted_intent")
    ]


def test_production_scripts_have_no_raw_gui_mutation_dispatchers() -> None:
    assert _scan_raw_script_gui_mutations(REPO_ROOT / "scripts") == []


def test_raw_gui_mutation_scanner_detects_pywin32_post_message(tmp_path: Path) -> None:
    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    (scripts_root / "unsafe.py").write_text(
        "import win32gui\nwin32gui.PostMessage(10, 0x0010, 0, 0)\n",
        encoding="utf-8",
    )

    assert _scan_raw_script_gui_mutations(scripts_root) == [
        ("scripts/unsafe.py", "PostMessage", 2)
    ]


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
        statement = _first_executable_statement(method)
        assert isinstance(statement, ast.Expr), (
            f"{name} does not check LiveController authority first"
        )
        call = statement.value
        assert (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "self"
            and call.func.attr == "_ensure_windows_input"
        ), f"{name} does not check LiveController authority first"


def test_every_app_raw_gui_mutation_sink_is_inventoried_and_leading_guarded() -> None:
    inventory, functions = _scan_raw_app_gui_mutations(REPO_ROOT / "app")

    assert inventory == EXPECTED_RAW_APP_GUI_MUTATION_SINKS
    for key, function in functions.items():
        _assert_leading_runtime_authority_guard(key, function)


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
