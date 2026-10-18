"""通过真实持久化边界验证识别文字清空及精确审核的修订绑定。"""
from copy import deepcopy

import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.contracts import AgentLinkError, SemanticChange, parse, validate_candidate
from app.agent_link.artifacts import BridgeCandidateInput, expand_candidate
from app.desktop_review.workspace import NativeReviewFacade
from app.desktop_review.exact_review import ExactReviewError
from test_interface_recognition_text import batch


def _setup(tmp_path):
    store = AgentLinkStore(tmp_path / 'inbox.json')
    service = AgentLinkService(store, 'synthetic-reviewer')
    connection = service.reviewer_call('synthetic-reviewer', 'create_connection', {'task_id': 'task', 'agent_name': 'synthetic-test'})
    service.agent_call(connection['token'], 'submit_batch', batch('Original title'))
    facade = NativeReviewFacade(service, 'synthetic-reviewer', tmp_path / 'reviews')
    saved = facade.save_revision('task', 'batch', 0, facade.load_batch('task', 'batch')['batch'])
    return store, service, connection, facade, saved


@pytest.mark.parametrize('value', [None, 'Replacement title'])
def test_validated_candidate_reaches_compare_adopt_and_reopen(tmp_path, value):
    store, service, connection, facade, saved = _setup(tmp_path)
    try:
        feedback = facade.request_relearn('task', 'batch', 1, 0,
            {'interface_ids': ['screen'], 'relationship_ids': []}, 'Adjust actual title only', 'feedback')
        issue = feedback['issues'][0]
        candidate = {'contract_version': 'agent_link_v1', 'idempotency_key': 'candidate', 'batch_id': 'batch',
            'issue_id': issue['issue_id'], 'baseline_revision': 1,
            'review_baseline_sha256': issue['review_baseline_sha256'], 'scope': issue['scope'],
            'changes': [{'change_type': 'semantic', 'target_type': 'interface', 'target_id': 'screen',
                'meaning': saved['batch']['interfaces'][0]['meaning'], 'recognition_text': value}]}
        normalized = validate_candidate(candidate)
        assert 'recognition_text' in normalized['changes'][0]
        assert normalized['changes'][0]['recognition_text'] == value
        proposed = service.agent_call(connection['token'], 'submit_candidate', candidate)
        comparison = facade.compare_relearn_candidate('task', 'batch', 1, proposed['candidate_id'])
        field_diff = next(item for item in comparison['diffs'] if item['field'] == 'recognition_text')
        assert field_diff['current'] == field_diff['baseline'] == 'Original title'
        assert field_diff['proposed'] == value
        adopted = facade.adopt_relearn_candidate('task', 'batch', 1, proposed['candidate_id'],
            comparison['candidate_sha256'], comparison['review_baseline_sha256'], 'adopt')
        interface = adopted['snapshot']['batch']['interfaces'][0]
        assert interface['meaning'] == saved['batch']['interfaces'][0]['meaning']
        assert ('recognition_text' in interface) == (value is not None)
        assert interface.get('recognition_text') == value
        assert adopted['snapshot']['review_status'] == 'needs_human_review'
        assert facade.list_reviewed_assets() == []
        facade.close()
        facade = NativeReviewFacade(service, 'synthetic-reviewer', tmp_path / 'reviews')
        assert facade.load_batch('task', 'batch')['batch']['interfaces'][0] == interface
    finally:
        facade.close()
        store.close()


def test_absent_change_field_stays_absent_but_noninterface_null_is_rejected():
    old = {'change_type': 'semantic', 'target_type': 'interface', 'target_id': 'screen', 'meaning': 'same'}
    assert parse(SemanticChange, old, 'change') == old
    with pytest.raises(AgentLinkError):
        parse(SemanticChange, {**old, 'target_type': 'region', 'recognition_text': None}, 'change')


@pytest.mark.parametrize('value', [None, 'New title', 'absent'])
def test_mcp_expansion_preserves_semantic_clear_presence(value):
    change = {'change_type': 'semantic', 'target_type': 'interface', 'target_id': 'screen', 'meaning': 'same'}
    if value != 'absent':
        change['recognition_text'] = value
    candidate = {'contract_version': 'agent_link_v1', 'idempotency_key': 'bridge', 'batch_id': 'batch',
        'issue_id': 'issue', 'baseline_revision': 1, 'review_baseline_sha256': 'a' * 64,
        'scope': {'interface_ids': ['screen'], 'relationship_ids': []}, 'changes': [change]}
    expanded = expand_candidate(BridgeCandidateInput.model_validate(candidate), None)
    assert expanded['changes'][0] == change


def test_changed_recognition_text_requires_new_exact_review(tmp_path):
    store, _, _, facade, saved = _setup(tmp_path)
    identity = {'kind': 'native', 'display_name': 'Notepad', 'executable_identity': 'notepad.exe', 'product_name': 'Notepad'}
    try:
        prepared = facade.prepare_exact_review('task', 'batch', 1, identity)
        node_subject = next(item for item in prepared['subjects'] if item['kind'] == 'node')
        assert node_subject['content']['recognition_text'] == 'Original title'
        assert node_subject['content']['display_name'] == 'purpose prose'
        decisions = facade.record_review_decisions(prepared['review_ref'], 0, [s['subject_id'] for s in prepared['subjects']])
        changed = deepcopy(saved['batch'])
        changed['interfaces'][0]['recognition_text'] = 'Replacement title'
        facade.save_revision('task', 'batch', 1, changed)
        current = facade.prepare_exact_review('task', 'batch', 2, identity)
        assert current['review_ref'] != prepared['review_ref']
        assert not any(item['confirmed'] for item in current['subjects'])
        assert next(item for item in current['subjects'] if item['kind'] == 'node')['content']['recognition_text'] == 'Replacement title'
        with pytest.raises(ExactReviewError, match='saved workspace revision is required and current'):
            facade.compile_exact_review(prepared['review_ref'], decisions['approval_revision'])
    finally:
        facade.close()
        store.close()
