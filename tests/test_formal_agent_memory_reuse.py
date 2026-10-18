import hashlib
import json

import pytest

from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from test_formal_graph_publication import _runtime, _review_compile, _submit_other, _target_node_id
from test_formal_graph_exact_review import TASK, BATCH, _correct_graph, _node


def _published_pair(tmp_path):
    inbox, service, facade, _ = _runtime(tmp_path)
    x = facade.create_graph_revision(TASK, BATCH, 0, {'open-result': ['rel-open']})
    _, _, compiled = _review_compile(facade, x)
    first = facade.publish_exact_review(compiled['compile_receipt_id'])
    y = _submit_other(service, facade, 'memory-y')
    _, _, compiled = _review_compile(facade, y)
    second = facade.publish_exact_review(compiled['compile_receipt_id'])
    return inbox, facade, x, first, y, second


def _files(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and path.suffix != '.lock'}


def test_agent_selects_explicit_memory_without_mutating_registry_or_source(tmp_path):
    inbox, facade, x, first, y, second = _published_pair(tmp_path)
    try:
        scope = [x['logical_workflow_id'], y['logical_workflow_id']]
        before = _files(tmp_path)
        choices = facade.search_workflow_memory(scope, {}, '', None)
        assert choices['contract_version'] == 'agent_workflow_memory_v1'
        assert {item['workflow_id'] for item in choices['items']} == set(scope)
        picked = facade.get_workflow_memory(scope, y['logical_workflow_id'], second['version_id'])
        assert picked['workflow_id'] == y['logical_workflow_id']
        assert picked['version_id'] == second['version_id'] != first['version_id']
        assert picked['graph_sha256'] == y['content_sha256']
        assert picked['asset_is_canonical'] is False
        assert picked['artifact_is_authorization'] is False
        assert picked['execute_binding_enabled'] is False
        assert picked['requires_current_grounding'] is True
        encoded = json.dumps(picked, ensure_ascii=False)
        assert 'png_base64' not in encoded and 'source_workflow_path' not in encoded
        assert str(tmp_path) not in encoded
        assert _files(tmp_path) == before
    finally:
        facade.close(); inbox.close()


def test_agent_can_read_corrected_current_and_explicit_original_version(tmp_path):
    inbox, facade, x, first, y, second = _published_pair(tmp_path)
    try:
        graph = _correct_graph(facade, 'fresh-memory-correction')
        _, _, compiled = _review_compile(facade, graph)
        corrected = facade.publish_exact_review(compiled['compile_receipt_id'])
        scope = [x['logical_workflow_id']]
        current = facade.get_workflow_memory(scope, x['logical_workflow_id'])
        old = facade.get_workflow_memory(scope, x['logical_workflow_id'], first['version_id'])
        assert current['version_id'] == corrected['version_id']
        assert current['version_status'] == 'current' and old['version_status'] == 'superseded'
        assert _target_node_id({'asset': current['asset_view']}) == _node(graph, 'state-c')['node_id']
        assert _target_node_id({'asset': old['asset_view']}) == _node(x, 'state-b')['node_id']
        from app.desktop_review.workflow_memory import WorkflowMemoryError
        with pytest.raises(WorkflowMemoryError) as error:
            facade.get_workflow_memory(scope, y['logical_workflow_id'], second['version_id'])
        assert error.value.code == 'not_found'
    finally:
        facade.close(); inbox.close()


@pytest.mark.parametrize('damage', ['source', 'approval', 'asset'])
def test_memory_refuses_damaged_verified_source_without_repairing_files(tmp_path, damage):
    inbox, facade, x, first, _, _ = _published_pair(tmp_path)
    try:
        root = tmp_path / 'fresh-artifacts'
        if damage == 'source':
            target = root / x['source_refs']['original_batch_path']
        elif damage == 'approval':
            target = next(path for path in (root / 'desktop-review/exact-reviews').glob('*/approval-1.json')
                          if json.loads(path.read_text(encoding='utf-8'))['review_ref'] == first['review_ref'])
        else:
            target = ReviewedWorkflowAssetStore(project_root=root).objects_root / (first['asset_sha256'] + '.json')
        target.write_bytes(target.read_bytes() + b'changed')
        before = _files(tmp_path)
        from app.desktop_review.workflow_memory import WorkflowMemoryError
        with pytest.raises(WorkflowMemoryError):
            facade.get_workflow_memory([x['logical_workflow_id']], x['logical_workflow_id'])
        assert _files(tmp_path) == before
    finally:
        facade.close(); inbox.close()


def test_memory_cursor_binds_scope_query_and_registry_revision(tmp_path, monkeypatch):
    inbox, facade, x, first, y, second = _published_pair(tmp_path)
    try:
        from app.desktop_review import workflow_memory
        monkeypatch.setattr(workflow_memory, 'PAGE_SIZE', 1)
        scope = sorted([x['logical_workflow_id'], y['logical_workflow_id']])
        page = facade.search_workflow_memory(scope, {}, '')
        assert len(page['items']) == 1 and page['next_cursor']
        tail = facade.search_workflow_memory(scope, {}, '', page['next_cursor'])
        assert len(tail['items']) == 1 and tail['next_cursor'] is None
        assert tail['items'][0]['workflow_id'] != page['items'][0]['workflow_id']
        with pytest.raises(workflow_memory.WorkflowMemoryError):
            facade.search_workflow_memory(scope[:1], {}, '', page['next_cursor'])
        with pytest.raises(workflow_memory.WorkflowMemoryError):
            facade.search_workflow_memory(scope, {}, 'changed query', page['next_cursor'])
        assets = ReviewedWorkflowAssetStore(project_root=tmp_path / 'fresh-artifacts')
        assets.withdraw_version(first['logical_workflow_id'], first['version_id'],
                                expected_registry_revision=assets.registry()['registry_revision'])
        with pytest.raises(workflow_memory.WorkflowMemoryError) as error:
            facade.search_workflow_memory(scope, {}, '', page['next_cursor'])
        assert error.value.code == 'stale_revision'
    finally:
        facade.close(); inbox.close()


def test_memory_search_matches_workflow_goal_and_application_without_default_selection(tmp_path):
    inbox, facade, x, _, y, second = _published_pair(tmp_path)
    try:
        scope = [x['logical_workflow_id'], y['logical_workflow_id']]
        result = facade.search_workflow_memory(scope, {'kind': 'native'}, 'Fresh memory-y graph')
        assert [item['version_id'] for item in result['items']] == [second['version_id']]
        assert result['items'][0]['display_name'] == 'Fresh memory-y graph'
        assert facade.search_workflow_memory(scope, {'kind': 'web'}, '')['items'] == []
        assert 'selected_workflow_id' not in result
    finally:
        facade.close(); inbox.close()


def test_missing_immutable_seal_is_refused_without_writing_or_repair(tmp_path, monkeypatch):
    inbox, facade, x, first, _, _ = _published_pair(tmp_path)
    try:
        root = tmp_path / 'fresh-artifacts'
        record = next(json.loads(path.read_text(encoding='utf-8'))
                      for path in (root / 'desktop-review/exact-reviews').glob('*/approval-1.json')
                      if json.loads(path.read_text(encoding='utf-8'))['review_ref'] == first['review_ref'])
        seal = (root / record['staging_path']).parent / '.immutable-seal.json'
        seal.unlink()
        before = _files(tmp_path)
        from app.learn import review_write_guard
        from app.desktop_review.workflow_memory import WorkflowMemoryError

        def forbidden(*args, **kwargs):
            raise AssertionError('memory reads must not enter the writer or dispatch')

        monkeypatch.setattr(review_write_guard, 'review_writer_lock', forbidden)
        with pytest.raises(WorkflowMemoryError) as error:
            facade.get_workflow_memory([x['logical_workflow_id']], x['logical_workflow_id'])
        assert error.value.code == 'memory_source_unavailable'
        assert _files(tmp_path) == before and not seal.exists()
    finally:
        facade.close(); inbox.close()


def test_read_only_immutable_check_never_creates_missing_directory(tmp_path):
    from app.learn.review_write_guard import save_guarded_review
    destination = tmp_path / 'missing-root'
    before = _files(tmp_path)

    def forbidden():
        raise AssertionError('a read cannot invoke any save/publish callback')

    with pytest.raises(ValueError, match='incomplete'):
        save_guarded_review(review={}, project_root=tmp_path, destination_root=destination,
                            workflow_dir=destination / 'not-created', create_only=True,
                            save=forbidden, registry_binding=forbidden, publish=forbidden, verify_only=True)
    assert not destination.exists() and _files(tmp_path) == before


def test_memory_read_response_limit_and_withdrawn_history_are_explicit(tmp_path, monkeypatch):
    inbox, facade, x, first, _, _ = _published_pair(tmp_path)
    try:
        from app.desktop_review import workflow_memory
        scope = [x['logical_workflow_id']]
        store = ReviewedWorkflowAssetStore(project_root=tmp_path / 'fresh-artifacts')
        store.withdraw_version(x['logical_workflow_id'], first['version_id'],
                               expected_registry_revision=store.registry()['registry_revision'])
        assert facade.search_workflow_memory(scope, {})['items'] == []
        with pytest.raises(workflow_memory.WorkflowMemoryError) as error:
            facade.get_workflow_memory(scope, x['logical_workflow_id'])
        assert error.value.code == 'not_found'
        history = facade.get_workflow_memory(scope, x['logical_workflow_id'], first['version_id'])
        assert history['version_status'] == 'withdrawn' and history['execute_binding_enabled'] is False
        monkeypatch.setattr(workflow_memory, 'MAX_RESPONSE_BYTES', 80)
        with pytest.raises(workflow_memory.WorkflowMemoryError) as error:
            facade.get_workflow_memory(scope, x['logical_workflow_id'], first['version_id'])
        assert error.value.code == 'memory_too_large'
    finally:
        facade.close(); inbox.close()


def test_memory_preserves_approved_application_identity_path_not_internal_lineage(tmp_path):
    from test_formal_graph_exact_review import BINDING
    inbox, _, facade, _ = _runtime(tmp_path)
    try:
        graph = facade.create_graph_revision(TASK, BATCH, 0, {'open-result': ['rel-open']})
        target_path = r'C:\FreshEditor\fresh-editor.exe'
        _, _, compiled = _review_compile(facade, graph, {**BINDING, 'executable_identity': target_path})
        facade.publish_exact_review(compiled['compile_receipt_id'])
        result = facade.get_workflow_memory([graph['logical_workflow_id']], graph['logical_workflow_id'])
        assert result['application_scope']['executable_path'].casefold() == target_path.casefold()
        assert result['asset_view']['application']['executable_path'].casefold() == target_path.casefold()
        assert 'source_workflow_path' not in json.dumps(result)
    finally:
        facade.close(); inbox.close()
