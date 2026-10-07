"""真实记忆库和目标规则的命令重编契约，不派发桌面输入。"""
from copy import deepcopy
from hashlib import sha256
import json
import pytest
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_trial import TrialService, _command, _selection_context
from app.learning_memory.workflow_execution_strategy import command_step
from app.learning_memory.workflow_target_bindings import load_workflow_target_bindings
from tests.test_workflow_image_check_journey import _fresh_learning
from tests.test_workflow_trial import click_response


@pytest.mark.parametrize('strategy', ['learned', 'steps_only'])
def test_real_recipe_prepare_target_selection_recovery_and_benchmark_compile_agree(tmp_path, strategy):
    session, root, draft, _after = _fresh_learning(tmp_path)
    workflow = draft['workflow_id']
    with MemoryWorkspace(root) as library:
        baseline = library.load_workflow_program(workflow)
        saved = library.save_workflow_program(workflow, baseline['content_sha256'], draft['definition'],
            'contract-save', target_recipes=[item['recipe'] for item in draft['proposed_target_recipes']])
        definition = deepcopy(saved['definition'])
        definition['steps'][0]['review_status'] = 'reviewed'
        saved = library.save_workflow_program(workflow, saved['content_sha256'], definition, 'contract-review')
        trials = TrialService(library, session)
        step = saved['definition']['steps'][0]
        run = trials.start(workflow, saved['program_id'], step['step_id'], {}, 'contract-start', execution_strategy=strategy)
        ticket = trials.prepare(run['run_id'], 'contract-prepare')
        command = ticket['suggested_command']
        assert ('observation_wait_ms' in command) is (strategy == 'learned')
    if strategy == 'learned':
        bindings = load_workflow_target_bindings(root, session,
            execution_request_id=ticket['execution_request_id'], command=command)
        assert bindings['step_id'] == step['step_id']
    with MemoryWorkspace(root) as library:
        trials = TrialService(library, session)
        effective = command_step(library, step, run)
        # 恢复历史使用同一有效步骤重新编译；原程序不能被策略改写。
        assert _command(effective, {}, {}) == command
        assert library.load_workflow_program(workflow, saved['program_id']) == saved
        selection = deepcopy(effective)
        selection['action']['selection_intent'] = 'ensure_selected'
        selection_command = _command(selection, {}, {})
        assert _selection_context(run, selection, selection_command, ticket['execution_request_id'])['action'] == selection['action']
        from app.learning_memory.benchmark_provenance import _command as benchmark_command
        assert benchmark_command(effective, {}, {}) == command
        if strategy == 'learned':
            from app.learning_memory.benchmark_provenance import _target
            from tests.test_benchmark_provenance import executed
            report = json.loads(executed()[3][1]['text'])['result']
            reference = step['action']['target_memory']
            report['memory_resolution']['reference'] = deepcopy(reference)
            plan = report['response']['data']['result']['recognition_plan']
            plan['goal'] = step['action']['goal']
            plan['memory_evidence']['reference'] = deepcopy(reference)
            archive = session / 'command-contract-archive.json'
            archive.write_text(json.dumps({'command': command, 'result': report}, ensure_ascii=False), encoding='utf-8')
            archived = json.loads(archive.read_text(encoding='utf-8'))
            assert _target(step, archived['command'], archived['result'], {}, {}) == 'memory_execution_hit'
            for altered in (2000, None):
                forged = deepcopy(archived['command'])
                if altered is None:
                    forged.pop('observation_wait_ms')
                else:
                    forged['observation_wait_ms'] = altered
                with pytest.raises(ValueError, match='benchmark_action_semantics_mismatch'):
                    _target(step, forged, archived['result'], {}, {})
            client_command = {**command, 'vision_capabilities': {'image_transport': 'supported'}}
            assert _target(step, client_command, archived['result'], {}, {}) == 'memory_execution_hit'
        click_response(session, ticket)
        trials.review(run['run_id'], 'contract-agent-review', ticket['execution_request_id'], 'success', {}, {})
        state = trials.status(run['run_id'])
        files = {path.relative_to(session).as_posix(): sha256(path.read_bytes()).hexdigest()
                 for path in session.rglob('*') if path.is_file()}
        from app.learning_memory.workflow_recovery_history import verify_recovery_history
        verified = verify_recovery_history(library, session, state, saved, file_hashes=files)
        assert verified
