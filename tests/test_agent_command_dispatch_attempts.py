"""派发返回与落盘之间中断时，原动作事实不能被提前清除。"""
from copy import deepcopy
from hashlib import sha256
import json
from threading import Event
from time import monotonic, sleep

from PIL import Image
import pytest

import app.vision.agent_command_jobs as module
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig


def _wait(jobs, command_id, statuses):
    end = monotonic() + 3
    while monotonic() < end:
        state = jobs.get(command_id)
        if state['status'] in statuses:
            return state
        sleep(.005)
    pytest.fail('worker did not reach expected persisted state: ' + str(state))


def _found(pending):
    return {'schema_version':'grounding.v1', 'request_id':pending['request_id'],
        'capture_id':pending['capture']['capture_id'], 'status':'found',
        'coordinate_space':'capture_image_pixels', 'image_size':{'width':100,'height':80},
        'candidates':[{'id':'one','label':'Open','bbox':{'x':10,'y':10,'width':40,'height':30},
            'click_point':{'x':30,'y':20},'evidence_source':'agent_visual'}], 'selected_candidate_id':'one'}


def _exercise(tmp_path, monkeypatch, route, outcomes, *, fail_write=None):
    image=tmp_path/'frame.png'
    Image.new('RGB',(100,80),'white').save(image)
    capture={'image_path':str(image),'sha256':sha256(image.read_bytes()).hexdigest(),
        'window_identity':{'handle':100,'process_id':200,'process_create_time':1.5}}
    store=GroundingHandoffStore(tmp_path,owner_id='attempt-owner')
    native_finished=Event()
    snapshots, before_calls, receipts = [], [], []
    path=tmp_path/'agent-commands/job-1.json'
    original_write=module.write_json_snapshot
    failed_write=[]
    def write(filename,value):
        attempts=value.get('dispatch_attempts',[])
        if (filename==path and fail_write and not failed_write and attempts
                and attempts[-1]['status']==fail_write):
            failed_write.append(fail_write)
            raise OSError('dispatch_snapshot_write_failed')
        original_write(filename,value)
        if filename==path:
            snapshots.append((native_finished.is_set(),json.loads(path.read_text(encoding='utf-8'))))
    monkeypatch.setattr(module,'write_json_snapshot',write)
    class Owner:
        def call(self,callback):
            return callback()
    class Coordinator:
        _owner=Owner()
        def prepare_memory_grounding(self,**kwargs):
            return object(),{'status':'matched'}
        def execute_local_step(self,**kwargs):
            native_finished.clear()
            before_calls.append(json.loads(path.read_text(encoding='utf-8')))
            value=outcomes[len(before_calls)-1]
            if isinstance(value,Exception):
                native_finished.set()
                raise value
            receipt={'phase':'returned','response':{'success':True,
                'data':{'result':{'execution_path':{'action_executed':value}}}},
                'observation':{'status':'captured','capture':{'sha256':'after-'+str(len(before_calls))}},
                'action_executed':value}
            receipts.append(deepcopy(receipt))
            native_finished.set()
            return receipt
    jobs=module.AgentCommandJobs(Coordinator(),store,lambda:capture,
        RecognitionSourceConfig(source='agent_current'))
    if route=='nonrecognition':
        def sequence(proxy,target,request,*,persist,**kwargs):
            for _ in outcomes:
                proxy.execute_local_step(target_window_handle=100,target_process_id=200,
                    operation='type_text',request={'text':'once'})
            return {'status':'completed','action_executed':any(value is True for value in outcomes)}
        monkeypatch.setattr(module,'run_input_sequence',sequence)
        command={'kind':'input_sequence','request':{'field_goal':'Open','text':'once','submit_search':False}}
    else:
        command={'kind':'step','operation':'execute_recognition_plan','request':{'goal':'Open'}}
        if route=='memory':
            command['request']['target_memory']={'recipe_id':'target-recipe-'+'a'*64,'interface_key':'desk','state_key':'home'}
    try:
        jobs.start('job-1',command,{'handle':100,'process_id':200},
            {'image_transport':'supported','current_vision':'supported'})
        if route=='vision':
            pending=_wait(jobs,'job-1',{'awaiting_grounding'})['pending_grounding']
            store.resolve(pending['request_id'],_found(pending))
            jobs.resume('job-1',pending['request_id'],'attempt-exec')
        done=_wait(jobs,'job-1',{'completed','failed','cancelled'})
        assert jobs.close(timeout=2)
        return before_calls,snapshots,receipts,done
    finally:
        jobs.close(timeout=2)


@pytest.mark.parametrize('route',['memory','vision','nonrecognition'])
@pytest.mark.parametrize('executed',[True,False])
def test_real_return_is_recorded_before_dispatch_can_be_closed(tmp_path,monkeypatch,route,executed):
    before,writes,receipts,done=_exercise(tmp_path,monkeypatch,route,[executed])
    operation='type_text' if route=='nonrecognition' else 'execute_recognition_plan'
    # 检查实际派发前磁盘，以及每次真实原子写后的磁盘；提前清标志会暴露空回执窗口。
    for native_returned,state in writes:
        if native_returned and state['dispatch_in_progress'] is False:
            assert state['action_executed'] is executed
            assert state['observation']==receipts[0]['observation']
            assert state['dispatch_attempts'][-1]['status']=='returned'
            assert state['last_execution']=={'attempt_index':1,'operation':operation,'receipt':receipts[0]}
    assert before[0]['dispatch_attempts'][-1]['status']=='started'
    assert before[0]['dispatch_attempts'][-1]['operation']==operation
    assert before[0]['dispatch_attempts'][-1]['index']==1
    assert before[0]['dispatch_in_progress'] is True
    assert done['dispatch_attempts'][-1]['action_executed'] is executed
    assert done['action_executed'] is executed


@pytest.mark.parametrize('route',['memory','vision','nonrecognition'])
def test_native_exception_keeps_unknown_attempt_and_never_proves_no_input(tmp_path,monkeypatch,route):
    before,writes,receipts,done=_exercise(tmp_path,monkeypatch,route,[RuntimeError('native_outcome_unknown')])
    assert before[0]['dispatch_attempts'][-1]['status']=='started'
    assert done['status']=='failed' and done['action_executed'] is None
    assert done['dispatch_attempts'][-1]['status']=='unknown'
    assert done['dispatch_attempts'][-1]['action_executed'] is None
    assert done['observation']=={'status':'unavailable','reason':'execution_result_unknown'}
    assert done['automatic_retry_allowed'] is False


@pytest.mark.parametrize('second',[False,RuntimeError('second_unknown')])
def test_later_attempt_does_not_erase_previous_true(tmp_path,monkeypatch,second):
    before,writes,receipts,done=_exercise(tmp_path,monkeypatch,'nonrecognition',[True,second])
    assert [row['index'] for row in done['dispatch_attempts']]==[1,2]
    assert before[1]['action_executed'] is True
    assert done['action_executed'] is True
    assert done['dispatch_attempts'][0]['status']=='returned'
    assert done['dispatch_attempts'][1]['status']==('unknown' if isinstance(second,Exception) else 'returned')


@pytest.mark.parametrize('route',['memory','vision','nonrecognition'])
def test_failed_started_write_prevents_native_call(tmp_path,monkeypatch,route):
    before,writes,receipts,done=_exercise(tmp_path,monkeypatch,route,[True],fail_write='started')
    assert before==receipts==[]
    assert done['status']=='failed' and done['action_executed'] is False
    assert done['dispatch_attempts']==[] and done['dispatch_in_progress'] is False


@pytest.mark.parametrize('route',['memory','vision','nonrecognition'])
def test_failed_return_write_leaves_durable_started_not_no_input(tmp_path,monkeypatch,route):
    before,writes,receipts,done=_exercise(tmp_path,monkeypatch,route,[True],fail_write='returned')
    assert len(before)==len(receipts)==1
    assert done['status']=='failed' and done['action_executed'] is None
    assert done['dispatch_attempts'][-1]['status']=='started'
    assert done['dispatch_in_progress'] is True and done['last_execution'] is None
    assert done['automatic_retry_allowed'] is False
