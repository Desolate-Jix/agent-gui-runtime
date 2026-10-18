from __future__ import annotations

import base64
import hashlib

import pytest

from app.desktop_review.workspace import DesktopReviewError
from test_formal_graph_source_ownership import _facade, _duplicate_png_batch, _node


def test_batch_graph_lookup_is_read_only_and_does_not_implicitly_import(tmp_path):
    facade, store, _, root = _facade(tmp_path)
    try:
        with pytest.raises(DesktopReviewError):
            facade.load_batch_graph_revision('graph-source-ownership-task', 'graph-source-ownership-batch')
        assert not (root / 'desktop-review/graph-revisions').exists()
        graph = facade.create_graph_revision('graph-source-ownership-task', 'graph-source-ownership-batch', 0)
        assert facade.load_batch_graph_revision('graph-source-ownership-task', 'graph-source-ownership-batch') == graph
    finally:
        facade.close()
        store.close()


def test_node_evidence_is_original_image_bound_to_exact_graph_node(tmp_path):
    batch = _duplicate_png_batch()
    facade, store, _, root = _facade(tmp_path, batch)
    try:
        snapshot = facade.create_graph_revision('graph-source-ownership-task', batch['batch_id'], 0)
        node = _node(snapshot, 'interface-b')
        result = facade.load_graph_node_evidence(snapshot['logical_workflow_id'], 1,
                                                snapshot['content_sha256'], node['node_id'])
        assert result['contract_version'] == 'formal_graph_node_evidence_v1'
        assert result['graph_revision'] == 1 and result['graph_sha256'] == snapshot['content_sha256']
        assert result['node'] == node
        shot = result['screenshot']
        assert shot['screenshot_id'] == 'capture-b'
        assert (shot['width'], shot['height']) == (96, 64)
        assert shot['png_bytes'] == base64.b64decode(batch['screenshots'][1]['png_base64'])
        assert hashlib.sha256(shot['png_bytes']).hexdigest() == shot['sha256']
        assert result['artifact_is_authorization'] is False and result['execute_binding_enabled'] is False
        result['node']['display_name'] = 'local display change'
        assert facade.load_graph_revision(snapshot['logical_workflow_id']) == snapshot
    finally:
        facade.close()
        store.close()


@pytest.mark.parametrize('invalid', ['revision', 'hash', 'node', 'image'])
def test_node_evidence_rejects_stale_foreign_or_damaged_source(tmp_path, invalid):
    facade, store, _, root = _facade(tmp_path)
    try:
        snapshot = facade.create_graph_revision('graph-source-ownership-task', 'graph-source-ownership-batch', 0)
        node = _node(snapshot, 'interface-a')
        revision, digest, node_id = 1, snapshot['content_sha256'], node['node_id']
        if invalid == 'revision':
            revision = 2
        elif invalid == 'hash':
            digest = '0' * 64
        elif invalid == 'node':
            node_id = 'unrelated-node'
        else:
            (root / snapshot['source_refs']['screenshots'][0]['path']).write_bytes(b'damaged image')
        before = {p: p.read_bytes() for p in (root / 'desktop-review/graph-revisions').rglob('*.json')}
        with pytest.raises(DesktopReviewError):
            facade.load_graph_node_evidence(snapshot['logical_workflow_id'], revision, digest, node_id)
        assert {p: p.read_bytes() for p in before} == before
    finally:
        facade.close()
        store.close()
