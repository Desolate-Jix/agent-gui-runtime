"""遍历完整不等于浏览器已暴露正文，诊断不得改变执行策略。"""
from copy import deepcopy

import pytest

from app.api import vision
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot


def _snapshot():
    return {
        'status': 'ok', 'scan_complete': True, 'truncated': False,
        'window': {'handle': 42, 'process_name': 'msedge.exe'},
        'controls': [
            {'control_id': 'doc', 'control_type': 'Document', 'name': None,
             'bbox': {'x': 0, 'y': 80, 'w': 800, 'h': 520}},
            {'control_id': 'button', 'control_type': 'Button', 'name': 'Close',
             'enabled': True, 'visible': True, 'patterns': ['Invoke'],
             'bbox': {'x': 760, 'y': 0, 'w': 40, 'h': 30}},
        ],
    }


@pytest.mark.parametrize('variant,expected,count', [
    ('empty', 'document_without_observed_content', 0),
    ('content', 'content_observed', 1),
    ('foreign_ancestor', 'document_without_observed_content', 0),
    ('incomplete', 'unknown_incomplete_scan', 0),
    ('no_document', 'no_document_observed', 0),
    ('unavailable', 'unavailable', 0),
    ('native', 'not_applicable', 0),
    ('chrome_scope', 'out_of_scope', 0),
])
def test_inventory_exposes_document_observation_without_inventing_page_readiness(tmp_path, variant, expected, count):
    snapshot = _snapshot()
    if variant in {'content', 'foreign_ancestor'}:
        snapshot['controls'].append({'control_id': 'link', 'control_type': 'Hyperlink',
            'name': 'Any article', 'bbox': {'x': 100, 'y': 200, 'w': 200, 'h': 30},
            'ancestor_control_ids': ['doc' if variant == 'content' else 'unrelated'],
            'enabled': True, 'visible': True, 'patterns': ['Invoke']})
    if variant == 'incomplete': snapshot.update(scan_complete=False, truncated=True)
    if variant == 'no_document': snapshot['controls'] = snapshot['controls'][1:]
    if variant == 'unavailable': snapshot['status'] = 'unavailable'
    if variant == 'native': snapshot['window']['process_name'] = 'notepad.exe'
    if variant == 'chrome_scope': snapshot['scan_scope'] = 'browser_chrome'
    original = deepcopy(snapshot)
    with pinned_uia_snapshot(snapshot):
        result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / 'frame.png',
            image_size=vision.ImageSize(width=800, height=600), app_name='Microsoft Edge',
            goal='Click the article link', metadata=None)
    observation = result.get('browser_document_observation')
    assert observation is not None
    assert observation['status'] == expected
    assert observation['content_control_count'] == count
    assert observation['page_ready_verified'] is None
    assert observation['automatic_retry_allowed'] is False
    assert result['raw_uia_snapshot'] == original
    assert result['screen_reading']['source_layers']['windows_uia']['browser_document_observation'] == observation
    assert snapshot == original
    if variant == 'empty':
        assert result['uia_scan_complete'] is True
        assert observation['next_action'] == 'inspect_current_image_or_request_fresh_observation'


def test_provider_includes_same_document_diagnostic(monkeypatch):
    import sys
    from types import SimpleNamespace
    from app.operation.screen_reading.uia_provider import WindowsUIAProvider
    from tests.test_uia_provider_pinned_snapshot import _TreeWrapper
    root = _TreeWrapper((1,), 'Window', 'browser', (0, 0, 800, 600))
    doc = _TreeWrapper((2,), 'Document', 'article', (0, 80, 800, 600), root)
    link = _TreeWrapper((3,), 'Hyperlink', 'article link', (100, 200, 300, 230), doc)
    root.iter_descendants = lambda: iter([doc, link])
    root.iter_children = lambda: iter([doc])
    monkeypatch.setitem(sys.modules, 'pywinauto', SimpleNamespace(
        Desktop=lambda **kw: SimpleNamespace(window=lambda **kw: root)))
    provider = WindowsUIAProvider()
    monkeypatch.setattr(provider, '_owned_popup_handles', lambda b: [])
    bound = SimpleNamespace(handle=42, title='browser', process_id=7, process_name='msedge.exe',
        rect=SimpleNamespace(left=0, top=0, right=800, bottom=600))
    snapshot = provider.snapshot_window(bound, max_controls=20)
    observation = snapshot.get('browser_document_observation')
    assert observation is not None
    assert observation['status'] == 'content_observed'
    assert observation['document_count'] == 1
