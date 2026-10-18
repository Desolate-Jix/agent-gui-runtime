"""公开盘点恢复和未知候选轮询，不产生桌面效果。"""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from tests.test_launched_window_close import Coordinator, Windows, IDENTITY
from app.desktop_review import window_preparation as module


def row():
    return {'handle': 101, 'process_id': 202, 'title': 'Synthetic', 'process_name': 'demo.exe'}


def test_public_discover_acknowledges_unknown_and_next_explicit_preview(monkeypatch):
    co = Coordinator(Windows())
    original = module._launch_unavailable(202, 'launched_window_timeout')
    co._unverified_window_launch = deepcopy(original)
    co._window_preparations = {}
    monkeypatch.setattr('app.desktop_review.application_catalog.application_catalog_view', lambda: [])
    co.windows.list_visible_windows = lambda: [row()]
    co._build_application_launch = lambda **kw: {'preparation_id': 'new', 'mode': 'launch'}
    result = co.discover_applications()
    assert result['launch_recovery']['inventory_refreshed'] is True
    assert result['launch_recovery']['effect_undone'] is False
    assert result['launch_recovery']['original_launch_result'] == original
    assert co.preview_application_launch(path='c:/new.exe')['preparation_id'] == 'new'


@pytest.mark.parametrize('inventory', [None, [{'handle': 0}], [{'handle': 0, 'process_id': 202, 'title': '', 'process_name': ''}]])
def test_invalid_discover_keeps_gate(monkeypatch, inventory):
    co = Coordinator(Windows())
    original = module._launch_unavailable(202, 'launched_window_timeout')
    co._unverified_window_launch = deepcopy(original)
    monkeypatch.setattr('app.desktop_review.application_catalog.application_catalog_view', lambda: [])
    co.windows.list_visible_windows = lambda: inventory
    with pytest.raises(ValueError):
        co.discover_applications()
    assert co._unverified_window_launch == original


@pytest.mark.parametrize('mode', ['transient', 'disappeared', 'persistent', 'multi', 'child'])
def test_launch_classifies_all_new_windows_before_accepting(monkeypatch, mode):
    co = Coordinator(Windows())
    co._launched_window_identities.clear()
    co._WINDOW_PREPARATION_TTL_SECONDS = .12
    co._LAUNCH_PRESENTATION_WAIT_SECONDS = 0
    co._visible_window_handles = lambda: ({101} if mode == 'child' or (mode == 'disappeared' and reads) else {99, 101})
    co.windows.bind_window_by_handle = lambda h: SimpleNamespace(handle=h, process_id=202, title='Synthetic')
    reads = []
    def read(_, h):
        reads.append(h)
        if h == 99 and (mode in {'persistent', 'disappeared'} or (mode == 'transient' and reads.count(99) == 1)):
            return {'status': 'unavailable', 'stage': 'process_identity_read'}
        identity = {**IDENTITY, 'target_window_handle': h}
        if h == 99 and mode == 'transient':
            identity['executable_path'] = 'c:\\other.exe'
        return identity
    monkeypatch.setattr(module.WindowsNativeIdentityReader, 'read_identity', read)
    result = co._await_launched_window({'executable_path': IDENTITY['executable_path'], 'source': 'app_catalog'},
                                      SimpleNamespace(pid=303), set())
    if mode in {'transient', 'disappeared', 'child'}:
        assert result['status'] == 'launched_window_ready'
        assert result['window']['process_id'] == 202
        assert result['process_id'] == 303
    else:
        assert result['status'] == 'launched_window_unavailable'
        assert result['reason'] == ('launched_window_ambiguous' if mode == 'multi' else 'launched_window_identity_unavailable')
        if mode == 'persistent':
            assert result['diagnostics']['unresolved_windows'][0]['handle'] == 99
            assert 101 in reads
        assert not co._launched_window_identities


def test_failed_inventory_does_not_acknowledge(monkeypatch):
    co = Coordinator(Windows())
    original = module._launch_unavailable(202, 'launched_window_timeout')
    co._unverified_window_launch = deepcopy(original)
    monkeypatch.setattr('app.desktop_review.application_catalog.application_catalog_view', lambda: [])
    def unavailable():
        raise OSError('inventory failed')
    co.windows.list_visible_windows = unavailable
    with pytest.raises(OSError):
        co.discover_applications()
    assert co._unverified_window_launch == original


def test_original_inventory_shares_acknowledgement_contract():
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    co = Coordinator(Windows())
    co._unverified_window_launch = module._launch_unavailable(202, 'launched_window_timeout')
    co._check_runtime_environment = lambda: None
    co._facade = SimpleNamespace(list_reviewed_assets=lambda: [])
    co.windows.list_visible_windows = lambda: [row()]
    result = NativeSingleStepCoordinator.inventory(co)
    assert result['launch_recovery']['original_launch_result']['result_unknown'] is True
    assert result['launch_recovery']['effect_undone'] is False
    assert co._unverified_window_launch is None
