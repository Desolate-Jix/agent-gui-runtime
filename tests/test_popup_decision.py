"""弹窗判断只决定原动作能否继续，不能生成新的输入。"""
from copy import deepcopy
from types import SimpleNamespace

from PIL import Image
import pytest

from app.execution.decision_check import DecisionCheckRejected
from app.execution.popup_decision import (
    POPUP_CONTINUE_CONDITION, PopupContinuationGuard, popup_decision_scope,
    prepare_popup_continuation,
)


class Service:
    enabled = True
    adoption_mode = 'auto'
    profile = SimpleNamespace(contract_version='decision_profile.v2')

    def __init__(self, disposition='continue'):
        self.disposition, self.calls, self.during = disposition, [], None

    def auto_condition_allowed(self, condition):
        return condition == POPUP_CONTINUE_CONDITION

    def readiness(self):
        return {'ready': True}

    def evaluate(self, **request):
        self.calls.append(deepcopy(request))
        if self.during:
            self.during()
        return dict(schema_version='decision_assessment.v2', status='completed',
            verdict='success', disposition=self.disposition,
            adopted=self.disposition == 'continue', authorizes_action=False,
            request_id=request['request_id'], execution_request_id=request['execution_request_id'],
            phase='before_action')

    def validate_result(self, result, **request):
        return result['request_id'] == request['request_id']


@pytest.fixture
def popup(tmp_path):
    path = tmp_path / 'before.png'
    Image.new('RGB', (200, 150), 'white').save(path)
    bound = SimpleNamespace(handle=10, process_id=20,
        rect=SimpleNamespace(left=0, top=0, right=200, bottom=150))
    state = {'popup': 11, 'identity': {'handle': 10, 'process_id': 20, 'process_create_time': 30.0}}
    manager = SimpleNamespace(get_bound_window=lambda: bound,
        get_owned_foreground_popup_handle=lambda b: state['popup'],
        read_owned_foreground_popup=lambda b: {'handle': state['popup'], 'parent_handle': 10,
            'process_id': 20, 'rect': [140, 70, 190, 120], 'parent_enabled': True},
        validate_bound_point_visibility=lambda **kw: {'allowed': True, 'hit_window': {'root_handle': 10}})
    candidate = {'candidate_id': 'field', 'bbox': {'x': 20, 'y': 20, 'w': 100, 'h': 20}}
    args = dict(manager=manager, capture=lambda: {'image_path': str(path)},
        identity=lambda: deepcopy(state['identity']), candidate=candidate, point={'x': 50, 'y': 30},
        bbox=(20, 20, 100, 20), goal='Focus address bar', click_kind='single', click_count=1,
        image_path=str(path), expected_owned_popup_handle=None)
    return args, state, bound, path


def test_no_popup_adds_no_request_or_capture(popup, tmp_path):
    args, state, _, _ = popup
    state['popup'] = None
    args['capture'] = lambda: pytest.fail('No popup must not add a capture')
    service = Service()
    with popup_decision_scope(service, execution_request_id='e1', step_id='s1', evidence_root=tmp_path):
        assert prepare_popup_continuation(**args) == (None, None)
    assert service.calls == []


def test_success_is_bound_and_single_use(popup, tmp_path):
    args, _, bound, _ = popup
    service = Service()
    with popup_decision_scope(service, execution_request_id='e1', step_id='s1', evidence_root=tmp_path):
        guard, result = prepare_popup_continuation(**args)
        assert type(guard) is PopupContinuationGuard and result['adopted'] is True
        command = dict(bound=bound, point=(50, 30), bbox=(20, 20, 100, 20), popup_handle=11, click_count=1)
        guard.validate_command(**command)
        guard.verify_current()
        with pytest.raises(ValueError):
            guard.validate_command(**command)
    with pytest.raises(ValueError):
        guard.verify_current()
    assert len(service.calls) == 1
    assert service.calls[0]['condition'] == POPUP_CONTINUE_CONDITION
    assert service.calls[0]['action']['candidate']['click_point'] == {'x': 50, 'y': 30}


@pytest.mark.parametrize('disposition', ['review_required', 'stop', 'observe'])
def test_intervention_returns_main_without_guard(popup, tmp_path, disposition):
    service = Service(disposition)
    with popup_decision_scope(service, execution_request_id='e1', step_id='s1', evidence_root=tmp_path):
        with pytest.raises(DecisionCheckRejected, match='popup_decision_review_required'):
            prepare_popup_continuation(**popup[0])
    assert len(service.calls) == 1


@pytest.mark.parametrize('changed', ['image', 'identity', 'popup'])
def test_wait_drift_rejects_approved_decision(popup, tmp_path, changed):
    args, state, _, path = popup
    service = Service()
    def mutate():
        if changed == 'image':
            Image.new('RGB', (200, 150), 'red').save(path)
        elif changed == 'identity':
            state['identity']['process_create_time'] += 1
        else:
            state['popup'] = 12
    service.during = mutate
    with popup_decision_scope(service, execution_request_id='e1', step_id='s1', evidence_root=tmp_path):
        with pytest.raises(DecisionCheckRejected, match='popup_decision_stale'):
            prepare_popup_continuation(**args)


def test_missing_api_returns_main_without_network(popup, tmp_path):
    with popup_decision_scope(None, execution_request_id='e1', step_id='s1', evidence_root=tmp_path):
        with pytest.raises(DecisionCheckRejected, match='popup_decision_unavailable'):
            prepare_popup_continuation(**popup[0])
