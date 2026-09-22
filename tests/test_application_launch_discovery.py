from copy import deepcopy

import pytest

from app.desktop_review import application_catalog as catalog
from app.instant_mcp import InstantCommand


@pytest.mark.parametrize('selector', [{'name': 'Example'}, {'path': 'C:\\Apps\\demo.exe'}, {'app_id': 'edge'}])
def test_launch_accepts_one_selector(selector):
    assert InstantCommand(kind='launch', **selector).command() == {'kind': 'launch', **selector}


@pytest.mark.parametrize('selector', [{}, {'app_id': 'edge', 'name': 'Edge'}, {'name': ''}])
def test_launch_rejects_missing_or_ambiguous_selector(selector):
    with pytest.raises(ValueError):
        InstantCommand(kind='launch', **selector).command()


def test_name_ambiguity_returns_candidates_without_resolving_executables(monkeypatch):
    records = [dict(app_id=x, name='Example', launch_command=['demo.exe']) for x in ('one', 'two')]
    monkeypatch.setattr(catalog, '_available_catalog', lambda: {'apps': records})
    with pytest.raises(ValueError) as error:
        catalog.application_launch_selection(name='Example')
    assert error.value.diagnostics['error_code'] == 'application_name_ambiguous'
    assert [x['app_id'] for x in error.value.diagnostics['candidates']] == ['one', 'two']


def test_missing_name_is_not_mcp_registration_error(monkeypatch):
    monkeypatch.setattr(catalog, '_available_catalog', lambda: {'apps': []})
    with pytest.raises(ValueError) as error:
        catalog.application_launch_selection(name='Missing')
    assert error.value.diagnostics['error_code'] == 'application_not_found'
    assert 'path' in error.value.diagnostics['next']


def test_exact_name_beats_partial_match(monkeypatch, tmp_path):
    executable = tmp_path / 'demo.exe'
    executable.write_bytes(b'demo')
    records = [dict(app_id=x, name=n, launch_command=[str(executable)])
               for x, n in [('exact', 'Example'), ('other', 'Example Tools')]]
    monkeypatch.setattr(catalog, '_available_catalog', lambda: {'apps': records})
    monkeypatch.setattr(catalog, '_resolve', lambda app, url=None: app['launch_command'])
    result = catalog.application_launch_selection(name='Example')
    assert result['app_id'] == 'exact'
    assert result['selector'] == {'name': 'Example'}


def test_reused_window_is_focused_but_not_owned(monkeypatch):
    from app.desktop_review import window_preparation as module
    from test_launched_window_close import Coordinator, Windows, IDENTITY
    coordinator = Coordinator(Windows())
    coordinator._launched_window_identities = {}
    monkeypatch.setattr(module.WindowsNativeIdentityReader, 'read_identity', lambda *_: deepcopy(IDENTITY))
    coordinator._focus_existing_application = lambda identity: {'status': 'focused', 'window': {'handle': 101, 'process_id': 202}}
    result = coordinator._reuse_application_window({'executable_path': IDENTITY['executable_path']})
    assert result['reused_existing_window'] is True
    assert result['launch_dispatched'] is False
    assert coordinator._launched_window_identities == {}


def test_existing_window_ambiguity_does_not_focus(monkeypatch):
    from app.desktop_review import window_preparation as module
    from test_launched_window_close import Coordinator, Windows, IDENTITY
    coordinator = Coordinator(Windows())
    coordinator._visible_window_handles = lambda: {101, 102}
    coordinator.windows.bind_window_by_handle = lambda handle: None
    monkeypatch.setattr(module.WindowsNativeIdentityReader, 'read_identity',
        lambda self, handle: {**IDENTITY, 'target_window_handle': handle})
    coordinator._focus_existing_application = lambda _: pytest.fail('ambiguous focus')
    with pytest.raises(RuntimeError) as error:
        coordinator._reuse_application_window({'executable_path': IDENTITY['executable_path']})
    assert error.value.diagnostics['error_code'] == 'application_window_ambiguous'
    assert len(error.value.diagnostics['candidates']) == 2


def test_preparation_keeps_actionable_selection_error(monkeypatch):
    from test_launched_window_close import Coordinator, Windows
    coordinator = Coordinator(Windows())
    monkeypatch.setattr(catalog, '_available_catalog', lambda: {'apps': []})
    with pytest.raises(RuntimeError) as error:
        coordinator._build_application_launch(name='Missing')
    assert error.value.diagnostics['error_code'] == 'application_not_found'


def test_revalidation_rejects_changed_working_directory(monkeypatch):
    from test_launched_window_close import Coordinator, Windows
    coordinator = Coordinator(Windows())
    intent = dict(source='app_catalog', app_id='example', name='Example', url=None,
        command=['example.exe'], executable_path='example.exe', catalog_entry_sha256='one',
        executable_sha256='two', working_directory='C:\\one', selector={'name': 'Example'})
    seen = []
    def rebuild(**kwargs):
        seen.append(kwargs)
        return {**intent, 'working_directory': 'C:\\two'}
    coordinator._build_application_launch = rebuild
    with pytest.raises(RuntimeError) as error:
        coordinator._revalidate_window_preparation(intent)
    assert error.value.code == 'window_preparation_application_changed'
    assert seen[0]['name'] == 'Example'


def test_builtin_and_unique_discovered_command_merge_without_false_ambiguity(monkeypatch):
    from app.desktop_review import installed_applications
    monkeypatch.setattr(catalog, '_catalog', lambda: {'apps': [
        {'app_id': 'notepad', 'name': 'Notepad', 'launch_command': ['notepad.exe']}]})
    monkeypatch.setattr(catalog, '_resolve', lambda app, url=None: ['C:\\notepad.exe'])
    monkeypatch.setattr(installed_applications, 'discover_installed_applications', lambda: [
        {'app_id': 'discovered-one', 'name': 'Notes', 'aliases': ['Editor'],
         'launch_command': ['C:\\notepad.exe']}])
    apps = catalog._available_catalog()['apps']
    assert len(apps) == 1 and apps[0]['app_id'] == 'notepad'
    assert apps[0]['aliases'] == ['Editor', 'Notes']


def test_same_command_different_working_directory_remains_distinct(monkeypatch):
    from app.desktop_review import installed_applications
    monkeypatch.setattr(catalog, '_catalog', lambda: {'apps': [
        {'app_id': 'one', 'name': 'Example', 'launch_command': ['demo.exe'], 'working_directory': 'C:\\one'}]})
    monkeypatch.setattr(catalog, '_resolve', lambda app, url=None: ['C:\\demo.exe'])
    monkeypatch.setattr(installed_applications, 'discover_installed_applications', lambda: [
        {'app_id': 'two', 'name': 'Example', 'launch_command': ['C:\\demo.exe'], 'working_directory': 'C:\\two'}])
    assert len(catalog._available_catalog()['apps']) == 2


def test_existing_identity_is_read_after_binding_each_current_handle(monkeypatch):
    from app.desktop_review import window_preparation as module
    from test_launched_window_close import Coordinator, Windows, IDENTITY
    coordinator = Coordinator(Windows())
    state = {'handle': None}
    coordinator.windows.bind_window_by_handle = lambda handle: state.update(handle=handle)
    def read(self, handle):
        assert state['handle'] == handle
        return deepcopy(IDENTITY)
    monkeypatch.setattr(module.WindowsNativeIdentityReader, 'read_identity', read)
    coordinator._focus_existing_application = lambda identity: {'status': 'focused', 'window': {'handle': 101}}
    assert coordinator._reuse_application_window({'executable_path': IDENTITY['executable_path']})['reused_existing_window']


def test_alias_can_resolve_original_shortcut_name(monkeypatch, tmp_path):
    exe = tmp_path / 'demo.exe'
    exe.write_bytes(b'demo')
    monkeypatch.setattr(catalog, '_available_catalog', lambda: {'apps': [
        {'app_id': 'one', 'name': 'Demo', 'aliases': ['Local Name'], 'launch_command': [str(exe)]}]})
    monkeypatch.setattr(catalog, '_resolve', lambda app, url=None: app['launch_command'])
    assert catalog.application_launch_selection(name='Local Name')['app_id'] == 'one'


def test_launch_preview_keeps_working_directory_visible():
    from app.desktop_review.window_preparation import _public_intent
    assert _public_intent({'working_directory': 'C:\\Demo', 'expires_at': 2})['working_directory'] == 'C:\\Demo'


def test_unbindable_unrelated_window_does_not_abort_application_search(monkeypatch):
    from app.desktop_review import window_preparation as module
    from test_launched_window_close import Coordinator, Windows, IDENTITY
    coordinator = Coordinator(Windows())
    coordinator._visible_window_handles = lambda: {100, 101}
    def bind(handle):
        if handle == 100:
            raise ValueError('native_capture_client_area_unavailable')
    coordinator.windows.bind_window_by_handle = bind
    monkeypatch.setattr(module.WindowsNativeIdentityReader, 'read_identity', lambda *_: deepcopy(IDENTITY))
    coordinator._focus_existing_application = lambda identity: {'status': 'focused', 'window': {'handle': 101}}
    assert coordinator._reuse_application_window({'executable_path': IDENTITY['executable_path']})['reused_existing_window']
