import hashlib
import json

import pytest

from scripts.build_learning_workbench import clean_environment, install_source_payload, require_new_output


def source_fixture(root):
    root.mkdir()
    rows = []
    for relative in ('app/learning_memory/workflow_run_client.py', 'scripts/run_local_step_session.py'):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# 中文源文件\n', encoding='utf-8')
        rows.append({'path': relative, 'bytes': path.stat().st_size,
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (root / 'MANIFEST.json').write_text(json.dumps({'files': rows}), encoding='utf-8')
    return root


def test_shared_runtime_root_keeps_exact_host_and_client_sources(tmp_path):
    source = source_fixture(tmp_path / 'source')
    runtime = tmp_path / 'portable' / 'runtime'
    install_source_payload(source, runtime)
    client = runtime / 'app/learning_memory/workflow_run_client.py'
    assert client.parents[2] / 'scripts/run_local_step_session.py' == runtime / 'scripts/run_local_step_session.py'
    assert (runtime / 'MANIFEST.json').read_bytes() == (source / 'MANIFEST.json').read_bytes()
    assert client.read_text(encoding='utf-8') == '# 中文源文件\n'


def test_tampered_snapshot_is_rejected_before_any_copy(tmp_path):
    source = source_fixture(tmp_path / 'source')
    (source / 'scripts/run_local_step_session.py').write_text('changed', encoding='utf-8')
    runtime = tmp_path / 'runtime'
    with pytest.raises(ValueError, match='manifest'):
        install_source_payload(source, runtime)
    assert not runtime.exists()


def test_conflicting_frozen_payload_is_not_overwritten(tmp_path):
    source = source_fixture(tmp_path / 'source')
    runtime = tmp_path / 'runtime'
    target = runtime / 'scripts/run_local_step_session.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        install_source_payload(source, runtime)
    assert target.read_bytes() == b'existing'
    assert not (runtime / 'app').exists()


def test_manifest_cannot_escape_runtime_root(tmp_path):
    source = source_fixture(tmp_path / 'source')
    manifest = source / 'MANIFEST.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['files'][0]['path'] = '../outside.py'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='path'):
        install_source_payload(source, tmp_path / 'runtime')


def test_build_output_must_be_new_child_of_explicit_parent(tmp_path):
    assert require_new_output(tmp_path / 'candidate', tmp_path) == tmp_path / 'candidate'
    for invalid in (tmp_path, tmp_path.parent / 'outside'):
        with pytest.raises(ValueError):
            require_new_output(invalid, tmp_path)
    existing = tmp_path / 'existing'
    existing.mkdir()
    with pytest.raises(FileExistsError):
        require_new_output(existing, tmp_path)


def test_windows_environment_keys_are_case_insensitive(tmp_path, monkeypatch):
    import os
    (tmp_path / 'System32').mkdir()
    monkeypatch.setattr(os, 'environ', {'SYSTEMROOT': str(tmp_path), 'PYTHONPATH': 'private'})
    environment = clean_environment(tmp_path / 'python.exe')
    assert 'private' not in environment.get('PYTHONPATH', '')
    assert str(tmp_path / 'System32') in environment['PATH']
