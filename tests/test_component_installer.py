"""真实编译的安装器只在新临时目录执行验证模式。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import shutil
import zipfile
import warnings

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/build_component_installer.py'


def builder():
    assert SCRIPT.is_file(), 'component installer build implementation is missing'
    spec = importlib.util.spec_from_file_location('component_builder', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package(tmp_path, component='learning', version='1.0', content=b'first'):
    source = tmp_path / ('payload-' + component + '-' + version)
    source.mkdir()
    entry = 'AgentLearningWorkbench.exe' if component == 'learning' else 'scripts/setup_instant.ps1'
    (source / entry).parent.mkdir(parents=True, exist_ok=True)
    (source / entry).write_bytes(content)
    (source / '\u4e2d\u6587.txt').write_bytes(b'data')
    manifest = tmp_path / (component + '-' + version + '.json')
    manifest.write_text(json.dumps({'files': [
        {'path': p.relative_to(source).as_posix(), 'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in source.rglob('*') if p.is_file()]}, ensure_ascii=False), encoding='utf-8')
    output = tmp_path / ('build-' + component + '-' + version)
    result = builder().build(component=component, version=version, payload_dir=source,
                             manifest=manifest, output_dir=output)
    return Path(result['setup_path'])


def run(exe, command, root):
    return subprocess.run([str(exe), command, str(root)], capture_output=True, text=True,
                          encoding='utf-8', timeout=30)


def test_compiled_install_upgrade_uninstall_preserves_unknown_and_modified(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'check-\u4e2d\u6587'
    result = run(setup, '--check-install', target)
    assert result.returncode == 0, result.stdout + result.stderr
    installed = target / 'AgentLearningWorkbenchPreview'
    assert (installed / '\u4e2d\u6587.txt').read_bytes() == b'data'
    (installed / 'personal.txt').write_bytes(b'keep')
    second = package(tmp_path, version='2.0', content=b'second')
    result = run(second, '--check-install', target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installed / 'AgentLearningWorkbench.exe').read_bytes() == b'second'
    (installed / '\u4e2d\u6587.txt').write_bytes(b'modified')
    result = run(second, '--check-uninstall', target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (installed / 'AgentLearningWorkbench.exe').exists()
    assert (installed / '\u4e2d\u6587.txt').read_bytes() == b'modified'
    assert (installed / 'personal.txt').read_bytes() == b'keep'


def test_unmarked_existing_check_root_is_refused(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'existing'
    target.mkdir()
    result = run(setup, '--check-install', target)
    assert result.returncode != 0
    assert list(target.iterdir()) == []


def test_two_components_are_independent(tmp_path):
    learning = package(tmp_path)
    execution = package(tmp_path, component='execution')
    target = tmp_path / 'shared-test-root'
    assert run(learning, '--check-install', target).returncode == 0
    result = run(execution, '--check-install', target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert run(learning, '--check-uninstall', target).returncode == 0
    assert (target / 'AgentGUIRuntimeExecutionPreview' / 'scripts/setup_instant.ps1').read_bytes() == b'first'


def test_execution_uses_fixed_powershell_contract_and_external_data(tmp_path):
    import os
    setup = package(tmp_path, component='execution', content=b'# synthetic packaging fixture only')
    target = tmp_path / 'check'
    result = run(setup, '--check-install', target)
    assert result.returncode == 0, result.stderr
    contract = json.loads(result.stdout)
    installed = target / 'AgentGUIRuntimeExecutionPreview'
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    data = Path(os.environ['LOCALAPPDATA']) / 'AgentGUIRuntime/data'
    assert Path(contract['shortcut_target']) == powershell
    assert powershell.is_file()
    assert contract['shortcut_arguments'] == (
        '-NoProfile -ExecutionPolicy Bypass -File "' + str(installed / 'scripts/setup_instant.ps1')
        + '" -RecognitionSource agent_current -DataDirectory "' + str(data) + '"')
    assert contract['shortcut_working_directory'] == str(installed)
    assert contract['integration_written'] is False
    assert not data.is_relative_to(installed)
    assert not (installed / 'AgentGUIRuntime.exe').exists()


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'a/../escape', 'CON', 'a:stream', 'a\\b', 'trailing.'])
def test_manifest_rejects_unsafe_windows_paths_before_output(tmp_path, path):
    source = tmp_path / 'source'
    source.mkdir()
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'files': [{'path': path, 'size': 0, 'sha256': '0' * 64}]}), encoding='utf-8')
    output = tmp_path / 'output'
    with pytest.raises(ValueError):
        builder().build(component='learning', version='1', payload_dir=source,
                        manifest=manifest, output_dir=output)
    assert not output.exists()


def test_builder_refuses_hash_mismatch_and_old_output(tmp_path):
    setup = package(tmp_path)
    with pytest.raises(FileExistsError):
        builder().build(component='learning', version='1.0', payload_dir=tmp_path / 'payload-learning-1.0',
                        manifest=tmp_path / 'learning-1.0.json', output_dir=setup.parent)
    manifest = tmp_path / 'learning-1.0.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['files'][0]['sha256'] = '0' * 64
    manifest.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        builder().build(component='learning', version='2', payload_dir=tmp_path / 'payload-learning-1.0',
                        manifest=manifest, output_dir=tmp_path / 'bad')


def test_uninstall_rejects_forged_extra_owned_file(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentLearningWorkbenchPreview'
    personal = installed / 'personal.txt'
    personal.write_bytes(b'private data')
    marker = installed / '.component-install.json'
    data = json.loads(marker.read_text(encoding='utf-8'))
    data['files'].append({'path': personal.name, 'size': personal.stat().st_size,
                          'sha256': hashlib.sha256(personal.read_bytes()).hexdigest()})
    marker.write_text(json.dumps(data), encoding='utf-8')
    result = run(setup, '--check-uninstall', target)
    assert result.returncode != 0, 'forged file ownership must not authorize deletion'
    assert personal.read_bytes() == b'private data'


def test_upgrade_refuses_modified_payload_without_partial_write(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentLearningWorkbenchPreview'
    (installed / '\u4e2d\u6587.txt').write_bytes(b'modified')
    newer = package(tmp_path, version='2.0', content=b'new')
    result = run(newer, '--check-install', target)
    assert result.returncode != 0
    assert (installed / 'AgentLearningWorkbench.exe').read_bytes() == b'first'
    assert (installed / '\u4e2d\u6587.txt').read_bytes() == b'modified'


@pytest.mark.parametrize('corruption', ['tamper', 'traversal', 'duplicate', 'missing', 'wronghash'])
def test_real_exe_preflights_embedded_payload_before_creating_target(tmp_path, corruption):
    setup = package(tmp_path)
    record = json.loads((setup.parent / 'build-result.json').read_text(encoding='utf-8'))
    bad = tmp_path / 'bad-build'
    shutil.copytree(setup.parent, bad)
    archive = bad / 'payload.zip'
    manifest = bad / 'payload-manifest.json'
    rows = json.loads(manifest.read_text(encoding='utf-8'))
    with zipfile.ZipFile(archive) as zipped:
        entries = [(i.filename, zipped.read(i)) for i in zipped.infolist()]
    if corruption == 'traversal':
        entries[0] = ('../escape', entries[0][1])
        rows['files'][0]['path'] = '../escape'
    elif corruption == 'duplicate':
        entries.append(entries[0])
    elif corruption == 'missing':
        entries.pop()
    elif corruption == 'wronghash':
        rows['files'][0]['sha256'] = '0' * 64
    with zipfile.ZipFile(archive, 'w') as zipped:
        for name, content in entries:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                zipped.writestr(name, content)
    manifest.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    identity = bad / 'ComponentIdentity.cs'
    source = identity.read_text(encoding='utf-8')
    source = source.replace(record['manifest_sha256'], hashlib.sha256(manifest.read_bytes()).hexdigest())
    if corruption != 'tamper':
        source = source.replace(record['payload_sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
    identity.write_text(source, encoding='utf-8')
    command = [argument.replace(str(setup.parent), str(bad)) for argument in record['command']]
    compiled = subprocess.run(command, capture_output=True, timeout=30)
    assert compiled.returncode == 0, compiled.stdout
    target = tmp_path / 'check'
    result = run(bad / setup.name, '--check-install', target)
    assert result.returncode != 0
    assert not target.exists(), result.stdout + result.stderr


def test_locked_file_is_refused_without_killing_process(tmp_path):
    import win32file
    import win32con
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    file = target / 'AgentLearningWorkbenchPreview' / 'AgentLearningWorkbench.exe'
    handle = win32file.CreateFile(str(file), win32con.GENERIC_READ, 0, None,
                                 win32con.OPEN_EXISTING, 0, None)
    try:
        result = run(setup, '--check-install', target)
        assert result.returncode != 0
        assert 'in use' in result.stderr
    finally:
        handle.Close()


def test_check_modes_reject_root_outside_temp_without_creation(tmp_path):
    setup = package(tmp_path)
    outside = ROOT / ('installer-forbidden-test-' + tmp_path.name)
    result = run(setup, '--check-install', outside)
    assert result.returncode != 0
    assert not outside.exists()


@pytest.mark.parametrize('change,value', [('component', 'execution'), ('product_id', 'Other'),
                                        ('version', '999'), ('user_sid', 'S-1-0-0'), ('root', 'C:/')])
def test_changed_install_identity_is_refused_before_deletion(tmp_path, change, value):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentLearningWorkbenchPreview'
    marker = installed / '.component-install.json'
    data = json.loads(marker.read_text(encoding='utf-8'))
    data[change] = value
    marker.write_text(json.dumps(data), encoding='utf-8')
    assert run(setup, '--check-uninstall', target).returncode != 0
    assert (installed / 'AgentLearningWorkbench.exe').read_bytes() == b'first'


def test_reparse_install_root_is_rejected_and_external_data_untouched(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentLearningWorkbenchPreview'
    renamed = target / 'real-install'
    installed.rename(renamed)
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(installed), str(renamed)],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout
    try:
        assert run(setup, '--check-uninstall', target).returncode != 0
        assert (renamed / 'AgentLearningWorkbench.exe').read_bytes() == b'first'
    finally:
        installed.rmdir()


def test_isolated_integration_write_failure_restores_registry_shortcut_and_payload(tmp_path):
    setup = package(tmp_path, content=b'old payload')
    target = tmp_path / 'transaction-check'
    assert run(setup, '--check-install', target).returncode == 0
    newer = package(tmp_path, version='2.0', content=b'changed payload')
    result = run(newer, '--check-integration-failure', target)
    assert result.returncode == 0, result.stdout + result.stderr
    result = json.loads(result.stdout)
    assert result['backend'] == 'isolated-files'
    assert result['integration_written'] is False
    assert result['shortcut_rollback'] and result['registry_rollback'] and result['payload_rollback']
    assert result['new_integration_removed']
    assert result['first_install_payload_removed']
    assert result['uninstall_payload_rollback']
    assert (target / 'AgentLearningWorkbenchPreview/AgentLearningWorkbench.exe').read_bytes() == b'old payload'


def test_check_uninstall_cleans_its_verified_temporary_worker(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    result = run(setup, '--check-uninstall', target)
    assert result.returncode == 0, result.stdout + result.stderr
    contract = json.loads(result.stdout)
    assert contract['worker_cleanup_complete'] is True
    assert not Path(contract['worker_path']).exists()


def test_failed_uninstall_preserves_payload_and_verifies_worker_cleanup(tmp_path):
    import win32file
    import win32con
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    payload = target / 'AgentLearningWorkbenchPreview/AgentLearningWorkbench.exe'
    handle = win32file.CreateFile(str(payload), win32con.GENERIC_READ, 0, None,
                                 win32con.OPEN_EXISTING, 0, None)
    try:
        result = run(setup, '--check-uninstall', target)
        assert result.returncode != 0
        assert 'after verified worker cleanup' in result.stderr
        assert 'in use' in result.stderr
    finally:
        handle.Close()
    assert payload.read_bytes() == b'first'
    assert (payload.parent / '.component-install.json').exists()


def test_execution_retains_verified_environment_then_reinstalls_independently(tmp_path):
    execution = package(tmp_path, component='execution')
    learning = package(tmp_path)
    target = tmp_path / 'check'
    assert run(execution, '--check-install', target).returncode == 0
    assert run(learning, '--check-install', target).returncode == 0
    installed = target / 'AgentGUIRuntimeExecutionPreview'
    marker = installed / '.component-install.json'
    other_marker = target / 'AgentLearningWorkbenchPreview/.component-install.json'
    other_before = other_marker.read_bytes()
    library = tmp_path / 'new-external-library'
    library.mkdir()
    (library / 'private.txt').write_bytes(b'external library untouched')
    for directory in ('.venv-agent', '.setup-cache'):
        (installed / directory).mkdir()
        (installed / directory / 'keep.bin').write_bytes(b'unknown data')
    import win32file
    import win32con
    handles = [win32file.CreateFile(str(installed / directory / 'keep.bin'),
               win32con.GENERIC_READ, 0, None, win32con.OPEN_EXISTING, 0, None)
               for directory in ('.venv-agent', '.setup-cache')]
    try:
        result = run(execution, '--check-uninstall', target)
    finally:
        for handle in handles:
            handle.Close()
    assert result.returncode == 0, result.stderr
    assert marker.is_file(), 'retained content needs verified ownership for reinstall'
    assert json.loads(marker.read_text(encoding='utf-8'))['state'] == 'retained'
    assert (installed / 'Uninstall.exe').is_file()
    assert not (installed / 'scripts/setup_instant.ps1').exists()
    newer = package(tmp_path, component='execution', version='2.0', content=b'new script')
    result = run(newer, '--check-install', target)
    assert result.returncode == 0, result.stderr
    assert json.loads(marker.read_text(encoding='utf-8'))['state'] == 'installed'
    assert (installed / 'scripts/setup_instant.ps1').read_bytes() == b'new script'
    assert other_marker.read_bytes() == other_before
    assert (library / 'private.txt').read_bytes() == b'external library untouched'
    assert all((installed / directory / 'keep.bin').read_bytes() == b'unknown data'
               for directory in ('.venv-agent', '.setup-cache'))


def test_retained_modified_payload_still_refuses_reinstall_collision(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentLearningWorkbenchPreview'
    (installed / 'AgentLearningWorkbench.exe').write_bytes(b'user modified')
    assert run(setup, '--check-uninstall', target).returncode == 0
    marker = installed / '.component-install.json'
    assert marker.is_file(), 'modified content needs retained verified marker'
    before = marker.read_bytes()
    assert json.loads(before)['state'] == 'retained'
    newer = package(tmp_path, version='2.0', content=b'new payload')
    result = run(newer, '--check-install', target)
    assert result.returncode != 0
    assert 'user-modified' in result.stderr
    assert marker.read_bytes() == before
    assert (installed / 'AgentLearningWorkbench.exe').read_bytes() == b'user modified'


@pytest.mark.parametrize('forgery', ['missing-uninstaller', 'extra-owned-file', 'foreign-sid'])
def test_retained_state_does_not_authorize_forged_ownership(tmp_path, forgery):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentLearningWorkbenchPreview'
    marker = installed / '.component-install.json'
    data = json.loads(marker.read_text(encoding='utf-8'))
    data['state'] = 'retained'
    (installed / 'personal.txt').write_bytes(b'keep')
    if forgery == 'missing-uninstaller':
        (installed / 'Uninstall.exe').unlink()
    elif forgery == 'extra-owned-file':
        data['files'].append({'path': 'personal.txt', 'size': 4,
                              'sha256': hashlib.sha256(b'keep').hexdigest()})
    else:
        data['user_sid'] = 'S-1-0-0'
    marker.write_text(json.dumps(data), encoding='utf-8')
    result = run(setup, '--check-install', target)
    assert result.returncode != 0
    assert (installed / 'personal.txt').read_bytes() == b'keep'


def test_unknown_reparse_directory_is_retained_without_touching_its_target(tmp_path):
    setup = package(tmp_path, component='execution')
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentGUIRuntimeExecutionPreview'
    external = tmp_path / 'external-unknown-directory'
    external.mkdir()
    (external / 'keep.bin').write_bytes(b'do not read or delete')
    junction = installed / '.venv-agent'
    created = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(external)],
                             capture_output=True, timeout=10)
    assert created.returncode == 0
    try:
        result = run(setup, '--check-uninstall', target)
        assert result.returncode == 0, result.stderr
        marker = installed / '.component-install.json'
        assert marker.is_file(), 'unknown junction must preserve retained ownership'
        assert json.loads(marker.read_text(encoding='utf-8'))['state'] == 'retained'
        assert (external / 'keep.bin').read_bytes() == b'do not read or delete'
    finally:
        junction.rmdir()


def test_no_residual_removes_root_and_legacy_marker_without_state_can_upgrade(tmp_path):
    setup = package(tmp_path)
    target = tmp_path / 'check'
    assert run(setup, '--check-install', target).returncode == 0
    installed = target / 'AgentLearningWorkbenchPreview'
    marker = installed / '.component-install.json'
    old = json.loads(marker.read_text(encoding='utf-8'))
    old.pop('state', None)
    marker.write_text(json.dumps(old), encoding='utf-8')
    newer = package(tmp_path, version='2.0', content=b'new')
    assert run(newer, '--check-install', target).returncode == 0
    result = run(newer, '--check-uninstall', target)
    assert result.returncode == 0, result.stderr
    assert not installed.exists()
