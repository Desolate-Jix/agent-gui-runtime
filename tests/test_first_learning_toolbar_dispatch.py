"""真实生产确认链使用合成输入后端，验证工具栏变化不造成重复输入。"""
from copy import deepcopy
import json

import pytest

from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from tests.test_fresh_navigation_stability import _NavigationUIA, _ready, _alter


def install_toolbar(monkeypatch):
    original = _NavigationUIA.snapshot_window
    state = {'name': 'Counter 24'}
    def snapshot(self, bound):
        result = original(self, bound)
        state['calls'] = state.get('calls', 0) + 1
        counter_name = ('Counter 24' if state.get('only_second') and state['calls'] == 1 else state['name'])
        target = result['controls'][0]
        def control(cid, kind, box, ancestors, runtime, name):
            bbox = dict(zip(('x','y','w','h'), box))
            return dict(provider='windows_uia', control_id=cid, control_type=kind, name=name,
                automation_id=cid, class_name='Synthetic', bbox=bbox, screen_bbox=deepcopy(bbox),
                enabled=True, visible=True, patterns=['Invoke'] if kind=='Button' else [],
                runtime_id=runtime, ancestor_control_ids=ancestors)
        box = tuple(target['bbox'][k] for k in ('x','y','w','h'))
        result['controls'] = [
            control('root','Window',(0,0,400,300),[],[42,1],'Test'),
            control('context','Group',(0,0,200,150),['root'],[42,2],'Content'),
            control(target['control_id'],'Button',box,['context','root'],target['runtime_id'],target['name']),
            control('toolbar','ToolBar',(0,210,400,40),['root'],[42,3],'Tools'),
            control('counter','Button',(290,215,40,30),['toolbar','root'],[42,4],counter_name),
        ]
        result.update(control_count=5, scan_complete=True, truncated=False, truncation_reason=None,
                      scan_budget=1000, scan_visited_count=5)
        result['window'].update(process_name='demo.exe',title='Test')
        return result
    monkeypatch.setattr(_NavigationUIA, 'snapshot_window', snapshot)
    return state


@pytest.mark.parametrize('final_only', [False, True])
def test_first_learning_toolbar_change_dispatches_once_and_reopens_with_full_proof(tmp_path, monkeypatch, final_only):
    state = install_toolbar(monkeypatch)
    with _ready(tmp_path, monkeypatch, learned=False) as (coordinator, runtime, backend, owner, view):
        state['name'] = 'Counter 25'
        state.update(only_second=final_only, calls=0)
        _alter(owner, monkeypatch, point_delta=0, pixel=(300,220), final_only=final_only)
        response = coordinator.execute(confirmation_id=view['confirmation_id'])
        assert response['kind'] == 'receipt', response
        assert len(backend.commands) == 1
        claims = runtime._intent_claim_store
        cid = view['confirmation_id']
        path = claims.root / ('navigation-visual-stability-' + cid.split('.')[-1] + '.json')
        original = path.read_bytes()
        record = json.loads(original)
        if final_only:
            assert record['proof'] is None
        else:
            assert record['proof']['uia_stability']['changes'][0]['control_id'] == 'counter'
            assert record['proof']['changed_pixels'] == 1
        assert record['visibility']['proof']['uia_stability']['changes'][0]['control_id'] == 'counter'
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root,
            receipt_store=claims._receipt_store, create_layout=False)
        assert reopened.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
        assert runtime.consume_grounded_confirmation(confirmation_id=cid).model_dump(mode='json') == response['payload']
        assert len(backend.commands) == 1
        record['visibility']['proof']['current_uia_snapshot']['controls'][-1]['name'] = 'Forged'
        path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',',':')), encoding='utf-8')
        with pytest.raises(RuntimeIntentClaimStoreError):
            reopened.get_for_grounded_confirmation(confirmation_id=cid)
        path.write_bytes(original)
        assert reopened.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
        assert len(backend.commands) == 1
