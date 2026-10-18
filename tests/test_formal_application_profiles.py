from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path


CANONICAL_MODULES = (
    "app.application_profiles.seek.application",
    "app.application_profiles.seek.execute_observation",
    "app.application_profiles.seek.form_inventory",
    "app.application_profiles.seek.scroll_containers",
)


def _imports(path: Path) -> set[tuple[str, tuple[str, ...]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        (node.module, tuple(alias.name for alias in node.names))
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def test_seek_profile_modules_are_canonical_and_old_namespace_is_absent() -> None:
    for module_name in CANONICAL_MODULES:
        assert importlib.import_module(module_name)
    assert importlib.util.find_spec("app.seek") is None


def test_execute_and_action_import_seek_profile_modules_directly() -> None:
    root = Path(__file__).resolve().parents[1]
    execute_imports = _imports(root / "app" / "api" / "execute.py")
    action_imports = _imports(root / "app" / "api" / "action.py")

    assert ("app.application_profiles.seek.execute_observation", ("build_seek_execute_observation",)) in execute_imports
    assert ("app.application_profiles.seek.form_inventory", ("build_seek_form_field_inventory",)) in execute_imports
    assert (
        "app.application_profiles.seek.scroll_containers",
        ("discover_seek_scroll_containers", "get_scroll_container", "seek_scroll_target_for_goal"),
    ) in action_imports
