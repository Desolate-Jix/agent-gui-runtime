"""同帧完整树封存、重开与篡改拒绝，不用当前树伪装历史。"""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agent_link.contracts import AgentLinkError, canonical_hash
from tests.test_formal_learning_observation import _rig, _request


def test_content_provider_uses_sealed_original_not_current_tree(tmp_path, monkeypatch):
    import app.agent.fresh_learning_factory as factory
    from app.desktop_review.learning_content import LearningContentProvider
    from tests.test_content_uia_stability import _pair
    pair = _pair()
    provider = LearningContentProvider(SimpleNamespace(source_owner=SimpleNamespace(
        archive=SimpleNamespace(project_root=tmp_path))))
    provider.record_source_context(pair['original_packet'], pair['original_uia'])
    source = SimpleNamespace(project_root=tmp_path, packet=pair['original_packet'],
        reference=lambda: {'application_identity': {'kind': 'web', 'canonical_origin': 'https://example.test'},
                          'target_window_handle': 1, 'target_process_id': 2})
    bundle = SimpleNamespace(packet=pair['current_packet'], uia_snapshot=lambda: pair['current_uia'])
    monkeypatch.setattr(factory, 'create_fresh_learning_observation_owner', lambda **_: SimpleNamespace(
        observe_with_uia=lambda **_: bundle))
    packet, proof = provider._capture(source)
    assert packet == pair['current_packet']
    assert proof['changed_pixel_count'] == 61
    assert proof['artifact_is_authorization'] is False
    provider.root = tmp_path / 'missing-original-context'
    with pytest.raises(AgentLinkError) as caught:
        provider._capture(source)
    assert caught.value.code == 'content_source_stale'


def test_passive_observation_seals_matching_full_tree_and_reuses_on_retry(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        result = host._service.agent_call(connection['token'], 'observe_learning_screen', _request(segment))
        provider = host._service._learning_observation_provider.content
        scope = {key: value for key, value in [('connection_id', connection['connection_id']),
            ('task_id', connection['task_id']), ('segment_id', segment['segment_id'])]}
        source = provider._source(scope, result['batch_id'])
        tree = provider._source_context(source.packet)
        assert canonical_hash(tree) == source.packet.evidence()['uia']['snapshot_sha256']
        path = next((provider.root / 'source-contexts').glob('*.json'))
        before = path.read_bytes()
        assert host._service.agent_call(connection['token'], 'observe_learning_screen', _request(segment)) == result
        assert path.read_bytes() == before and len(captures) == 1
        corrupt = deepcopy(tree)
        corrupt['status'] = 'error'
        with pytest.raises(ValueError, match='differs'):
            provider.record_source_context(source.packet, corrupt)
        value = json.loads(before)
        value['uia'] = corrupt
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        with pytest.raises(AgentLinkError, match='unavailable'):
            provider._source_context(source.packet)


def test_source_context_missing_cannot_be_replaced_with_current_snapshot(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, _captures):
        result = host._service.agent_call(connection['token'], 'observe_learning_screen', _request(segment))
        provider = host._service._learning_observation_provider.content
        scope = {'connection_id': connection['connection_id'], 'task_id': connection['task_id'],
                 'segment_id': segment['segment_id']}
        source = provider._source(scope, result['batch_id'])
        # 测试独立临时根，不删除任何用户来源。
        provider.root = tmp_path / 'empty-content-root'
        with pytest.raises(AgentLinkError, match='unavailable'):
            provider._source_context(source.packet)
