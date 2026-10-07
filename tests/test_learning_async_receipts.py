from copy import deepcopy

import pytest

from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.receipt_adapter import content_hash


def async_record(tmp_path):
    session = tmp_path / 'session'
    (session / 'responses').mkdir(parents=True)
    (session / 'agent-commands').mkdir()
    store = LearningEventStore(session)
    store.control('learning_start', {'scope': 'interface', 'title': 'Async'}, 'start')
    command = {'kind': 'input_sequence', 'request': {'field_goal': 'Search', 'text': 'new value', 'submit_search': False}}
    ticket = store.prepare('step-1', command, {'handle': 1, 'process_id': 2})
    response = {'command': command, 'learning_binding': ticket, 'status': 'returned',
                'result': {'contract_version': 'agent_command.v1', 'command_id': 'step-1', 'status': 'running'}}
    write_json_snapshot(session / 'responses/step-1.json', response)
    write_json_snapshot(session / 'agent-commands/step-1.json', deepcopy(response['result']))
    return store, ticket, response


def test_async_submission_waits_for_terminal_and_recovers_without_input(tmp_path):
    store, ticket, original = async_record(tmp_path)
    pending = store.record('step-1', ticket)
    assert pending['status'] == 'awaiting_execution_result'
    assert store.status()['event_count'] == 0
    final = {'contract_version': 'agent_command.v1', 'command_id': 'step-1', 'status': 'completed',
             'result': {'status': 'completed', 'action_executed': True, 'steps': []}, 'action_executed': True}
    write_json_snapshot(store.session / 'agent-commands/step-1.json', final)
    result = store.recover(ticket['learning_id'])
    assert result['recovered_count'] == 1 and result['input_replayed'] is False
    event = store.control('learning_event', {'event_id': 'step-1'}, 'read')['event']
    assert event['action_executed'] is True
    assert event['terminal_receipt']['sha256'] == content_hash(final)
    assert read_json_snapshot(store.session / 'responses/step-1.json') == original
    assert store.recover(ticket['learning_id'])['recovered_count'] == 0
    final['result']['action_executed'] = False
    write_json_snapshot(store.session / 'agent-commands/step-1.json', final)
    with pytest.raises(ValueError, match='original receipt'):
        store.control('learning_event', {'event_id': 'step-1'}, 'changed')


def test_async_mismatched_command_never_records(tmp_path):
    store, ticket, _ = async_record(tmp_path)
    write_json_snapshot(store.session / 'agent-commands/step-1.json',
                        {'contract_version': 'agent_command.v1', 'command_id': 'other', 'status': 'completed'})
    with pytest.raises(ValueError, match='identity'):
        store.record('step-1', ticket)
