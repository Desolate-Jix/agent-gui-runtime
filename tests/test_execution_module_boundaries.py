import ast
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("name", ["input_sequence", "form_fill", "conditional_observation", "local_direct_step", "post_action_recovery"])
def test_legacy_and_canonical_are_one_module(name):
    old = importlib.import_module("app.desktop_review." + name)
    new = importlib.import_module("app.execution." + name)
    assert old is new
    assert Path(new.__file__).parent.name == "execution"


@pytest.mark.parametrize("path", ["app.desktop_review.form_fill", "app.execution.form_fill"])
def test_patch_via_either_form_import_reaches_real_orchestration(monkeypatch, path):
    form = importlib.import_module(path)
    canonical = importlib.import_module("app.execution.form_fill")
    seen = []

    def interrupted(*args, **kwargs):
        seen.append(args[2])
        raise canonical.FormFillInterrupted("boundary_probe")

    monkeypatch.setattr(form, "run_input_sequence", interrupted)
    result = canonical.run_form_fill(object(), {"handle": 1, "process_id": 2},
        {"fields": [{"kind": "text", "field_goal": "Name", "text": "Ada"}]})
    assert seen[0]["text"] == "Ada"
    assert result["status"] == "interrupted"
    assert result["error"] == {"code": "boundary_probe", "type": "FormFillInterrupted"}


@pytest.mark.parametrize("first", ["app.desktop_review", "app.execution"])
def test_fresh_process_import_identity_without_review_ui(first):
    code = '''
import importlib, sys
first = sys.argv[1]
other = 'app.execution' if first == 'app.desktop_review' else 'app.desktop_review'
for name in ('input_sequence', 'form_fill', 'conditional_observation', 'local_direct_step', 'post_action_recovery'):
    left = importlib.import_module(first + '.' + name)
    assert not any(name.startswith(('PySide', 'PyQt')) for name in sys.modules)
    assert not any('workflow_editor' in name or 'review_editor' in name for name in sys.modules)
    right = importlib.import_module(other + '.' + name)
    assert left is right
    assert left.__name__ == 'app.execution.' + name
assert not any(name.startswith(('PySide', 'PyQt')) for name in sys.modules)
assert not any('workflow_editor' in name or 'review_editor' in name for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", code, first], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_maintained_entrypoints_use_canonical_modules():
    root = Path(__file__).resolve().parents[1]
    consumers = ["app/instant_mcp.py", "app/vision/agent_command_jobs.py",
        "scripts/run_local_step_session.py", "scripts/check_instant_entrypoints.py",
        "app/execution/local_direct_step.py", "app/desktop_review/single_step_coordinator.py"]
    for path in consumers:
        tree = ast.parse((root / path).read_text(encoding="utf-8-sig"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                    and isinstance(node.value, str) and node.value.startswith("app.")]
        assert any(value and value.startswith("app.execution.") for value in imports), path
        assert not any(value in {"app.desktop_review." + name for name in
            ("input_sequence", "form_fill", "conditional_observation", "local_direct_step", "post_action_recovery")} for value in imports), path
        assert not any(isinstance(node, ast.ImportFrom) and node.level and
            node.module in {"conditional_observation", "local_direct_step"} for node in ast.walk(tree)), path


def test_preflight_records_both_alias_and_canonical_entrypoints(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / "entrypoints.json"
    result = subprocess.run([sys.executable, "-I", str(root / "scripts/check_instant_entrypoints.py"),
        "--root", str(root), "--report", str(report)], cwd=tmp_path,
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    evidence = json.loads(report.read_text(encoding="utf-8"))
    for name in ("input_sequence", "form_fill", "conditional_observation", "local_action_contract", "local_keyboard_action", "single_step_runtime_owner", "local_direct_step", "post_action_recovery"):
        source = "app/execution/" + name + ".py"
        assert evidence["local_module_sources"]["app.execution." + name] == source
        assert evidence["local_module_sources"]["app.desktop_review." + name] == source
    assert evidence["local_module_sources"]["app.core.outcome_judgment"] == "app/core/outcome_judgment.py"
    assert evidence["optional_judgment"] == {"contract_imported": True,
        "judgment_evaluated": False, "provider_called": False, "request_factory_called": False}
    assert evidence["input_executed"] is False


def test_local_contract_and_keyboard_share_unique_model_and_error():
    canonical = importlib.import_module("app.execution.local_action_contract")
    legacy = importlib.import_module("app.desktop_review.local_action_contract")
    keyboard = importlib.import_module("app.desktop_review.local_keyboard_action")
    assert canonical is legacy
    assert canonical.LocalKeyRequest is keyboard.LocalKeyRequest
    assert canonical.LocalActionFieldsError is legacy.LocalActionFieldsError
    assert canonical.LocalKeyRequest.__module__ == "app.execution.local_action_contract"
    assert keyboard.press_local_key.__module__ == "app.execution.local_keyboard_action"


def test_canonical_key_validation_does_not_load_input_backend():
    code = '''
import sys
from app.execution.local_action_contract import _validated_request
value = _validated_request('press_key', {'key': 'Shift+Home', 'x': 1, 'y': 2})
assert value == {'key': 'Shift+Home', 'x': 1, 'y': 2, 'capture_roi': None}
assert 'app.core.input_controller' not in sys.modules
assert 'app.desktop_review.local_keyboard_action' not in sys.modules
assert not any(name.startswith(('PySide', 'PyQt')) for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_preflight_refuses_missing_canonical_local_contract(monkeypatch):
    from scripts import check_instant_entrypoints as preflight
    original = preflight.importlib.import_module
    missing = "app.execution.local_action_contract"

    def checked(name, *args, **kwargs):
        if name == missing:
            raise ModuleNotFoundError(missing)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(preflight.importlib, "import_module", checked)
    with pytest.raises(ModuleNotFoundError, match=missing):
        preflight.check(Path(__file__).resolve().parents[1])


@pytest.mark.parametrize("path", ["app.desktop_review.local_keyboard_action", "app.execution.local_keyboard_action"])
def test_keyboard_alias_patch_reaches_existing_local_dispatch(monkeypatch, path):
    keyboard = importlib.import_module(path)
    canonical = importlib.import_module("app.execution.local_keyboard_action")
    assert keyboard is canonical
    from app.desktop_review import local_direct_step
    from app.api import action
    from app.api.models.response import APIResponse
    manager = object()
    monkeypatch.setattr(action, "window_manager", manager)
    calls = []

    def handler(request):
        calls.append(request)
        return APIResponse(success=True, message="boundary probe", data={"pressed": False})

    monkeypatch.setattr(keyboard, "press_local_key", handler)
    result = local_direct_step._post_action("press_key", {"key": "Home", "x": 1, "y": 2}, manager)
    assert len(calls) == 1
    assert type(calls[0]) is canonical.LocalKeyRequest
    assert result["success"] is True


def test_preflight_refuses_missing_canonical_keyboard(monkeypatch):
    from scripts import check_instant_entrypoints as preflight
    original = preflight.importlib.import_module
    missing = "app.execution.local_keyboard_action"

    def checked(name, *args, **kwargs):
        if name == missing:
            raise ModuleNotFoundError(missing)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(preflight.importlib, "import_module", checked)
    with pytest.raises(ModuleNotFoundError, match=missing):
        preflight.check(Path(__file__).resolve().parents[1])


def test_coordinator_uses_canonical_owner():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app/desktop_review/single_step_coordinator.py").read_text(encoding="utf-8-sig"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert any(node.module == "app.execution.single_step_runtime_owner" and node.level == 0 for node in imports)
    assert not any(node.module == "single_step_runtime_owner" and node.level for node in imports)


def test_preflight_refuses_missing_canonical_owner(monkeypatch):
    from scripts import check_instant_entrypoints as preflight
    original = preflight.importlib.import_module
    missing = "app.execution.single_step_runtime_owner"

    def checked(name, *args, **kwargs):
        if name == missing:
            raise ModuleNotFoundError(missing)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(preflight.importlib, "import_module", checked)
    with pytest.raises(ModuleNotFoundError, match=missing):
        preflight.check(Path(__file__).resolve().parents[1])


@pytest.mark.parametrize("missing", ["app.execution.local_direct_step", "app.execution.post_action_recovery", "app.core.outcome_judgment"])
def test_preflight_refuses_missing_execution_extension_contract(monkeypatch, missing):
    from scripts import check_instant_entrypoints as preflight
    original = preflight.importlib.import_module

    def checked(name, *args, **kwargs):
        if name == missing:
            raise ModuleNotFoundError(missing)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(preflight.importlib, "import_module", checked)
    with pytest.raises(ModuleNotFoundError, match=missing):
        preflight.check(Path(__file__).resolve().parents[1])


@pytest.mark.parametrize("path", ["app.desktop_review.local_direct_step", "app.execution.local_direct_step"])
def test_local_alias_validation_patch_reaches_original_method(monkeypatch, path, tmp_path):
    local = importlib.import_module(path)
    canonical = importlib.import_module("app.execution.local_direct_step")
    assert local is canonical
    calls = []

    def reject(operation, request):
        calls.append((operation, request))
        raise ValueError("boundary_validation_probe")

    monkeypatch.setattr(local, "_validated_request", reject)
    coordinator = canonical.LocalDirectStepMixin()
    coordinator._runtime_output_root = tmp_path
    with pytest.raises(ValueError, match="boundary_validation_probe"):
        coordinator.execute_local_step(target_window_handle=1, target_process_id=2,
            operation="press_key", request={"key": "Home", "x": 1, "y": 2})
    assert calls == [("press_key", {"key": "Home", "x": 1, "y": 2})]


@pytest.mark.parametrize("path", ["app.desktop_review.local_direct_step", "app.execution.local_direct_step"])
def test_local_alias_patch_reaches_original_dispatch(monkeypatch, path):
    local = importlib.import_module(path)
    canonical = importlib.import_module("app.execution.local_direct_step")
    from app.api import action
    from app.api.models.response import APIResponse
    manager = object()
    monkeypatch.setattr(action, "window_manager", manager)
    calls = []

    def handler(request):
        calls.append(request.text)
        return APIResponse(success=True, message="boundary probe", data={"typed": False})

    original_run = canonical.asyncio.run
    dispatches = []

    def run(coroutine):
        dispatches.append(True)
        return original_run(coroutine)

    from types import SimpleNamespace
    monkeypatch.setattr(local, "asyncio", SimpleNamespace(run=run))
    monkeypatch.setattr(action, "type_text", handler)
    result = canonical._post_action("type_text", {"text": "boundary", "x": 1, "y": 2}, manager)
    assert calls == ["boundary"]
    assert dispatches == [True]
    assert result["data"] == {"typed": False}
