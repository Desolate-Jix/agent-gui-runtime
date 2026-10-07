from pathlib import Path

import pytest

from scripts.build_component_sources import collect_module_sources, copy_component_sources


def test_relative_imports_and_package_initializers_are_closed(tmp_path):
    files = {
        'scripts/open_gui.py': 'from app.ui import launch\n',
        'app/__init__.py': 'from . import shared\n',
        'app/shared.py': 'VALUE = 1\n',
        'app/ui/__init__.py': 'from .window import launch\n',
        'app/ui/window.py': 'from ..shared import VALUE\nimport PySide6\ndef launch(): return VALUE\n',
        'app/executor.py': 'raise RuntimeError("unrelated executor")\n',
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    assert {path.relative_to(tmp_path).as_posix() for path in collect_module_sources(tmp_path, ['scripts/open_gui.py'])} == set(files) - {'app/executor.py'}


def test_real_learning_dependencies_do_not_silently_exclude_executor(tmp_path):
    (tmp_path / 'gui.py').write_text('import executor\n', encoding='utf-8')
    (tmp_path / 'executor.py').write_text('VALUE = 1\n', encoding='utf-8')
    with pytest.raises(ValueError, match='executor.py'):
        collect_module_sources(tmp_path, ['gui.py'], forbidden=('executor.py',))


def test_missing_entry_and_source_escape_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        collect_module_sources(tmp_path, ['missing.py'])
    with pytest.raises(ValueError, match='root'):
        collect_module_sources(tmp_path, ['../outside.py'])


def test_component_copy_preserves_utf8_resources_and_rejects_overwrite(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    entry = root / 'gui.py'
    entry.write_text('TITLE = "\u5b66\u4e60"\n', encoding='utf-8')
    resource = root / 'catalog.qm'
    resource.write_bytes(b'qt catalog')
    target = tmp_path / 'bundle'
    manifest = copy_component_sources(root, target, ['gui.py'], resources=['catalog.qm'])
    assert {row['path'] for row in manifest['files']} == {'gui.py', 'catalog.qm'}
    assert (target / 'gui.py').read_bytes() == entry.read_bytes()
    with pytest.raises(FileExistsError):
        copy_component_sources(root, target, ['gui.py'])


def test_learning_startup_probe_does_not_pull_execution_entrypoint():
    import ast
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'app/learning_memory/workbench_launch.py').read_text(encoding='utf-8'))
    probe = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_check_startup')
    imports = [node for node in ast.walk(probe) if isinstance(node, ast.ImportFrom)]
    assert not any(node.module == 'scripts' and any(alias.name == 'run_local_step_session' for alias in node.names) for node in imports)


def test_actual_learning_snapshot_closes_gui_without_executor(tmp_path):
    from scripts.build_learning_workbench import build_learning_source
    root = Path(__file__).resolve().parents[1]
    manifest = build_learning_source(root, tmp_path / 'source')
    paths = {row['path'] for row in manifest['files']}
    assert 'scripts/start_learning_workbench.py' in paths
    assert 'app/core/instant_attachment_transport.py' in paths
    assert 'app/learning_memory/translations/en-US.qm' in paths
    assert 'app/learning_memory/translations/zh-CN.qm' in paths
    assert 'app/instant_mcp.py' not in paths
    assert 'scripts/run_local_step_session.py' not in paths
    assert 'app/desktop_review/single_step_coordinator.py' not in paths
