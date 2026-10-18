"""动作记忆只读投影及固定项目版本回归。"""
from copy import deepcopy
import json

import pytest

from app.desktop_review.workflow_action_memory import project_recorded_action_memory
from app.desktop_review.workspace import DesktopReviewError
from tests.test_reviewed_action_only_graph import _rig, _scope
from tests.test_recorded_action_workflow_project import _changes
from tests.test_formal_learning_segments import _perform_action


def _source():
    target=dict(contract_version='action_learning_target_observation_v1',capture_id='capture.1',
        screenshot_sha256='a'*64,candidate_id='candidate.1',element_id='element.1',label='Search',text='',role='button')
    terminal=dict(receipt_id='receipt.1',receipt_content_sha256='c'*64,intent_id='intent.1',
        action={'action_id':'search','semantic_action':'open_detail'},outcome='ACTION_RECORDED',
        reason_code='backend_dispatched',attempt_count=1,gate_status='manual_confirmed',
        dispatch_status='dispatched',effect_status='not_verified',destination_status='not_evaluated',
        evidence={'token':'TOP-SECRET','path':r'C:\private\data.txt'},next_observation_id='observation.2',
        backend_receipt={'token':'TOP-SECRET'})
    return dict(event_id='event.1',source_sha256='b'*64,event=dict(event_id='event.1',
        before=dict(action=deepcopy(terminal['action']),target_observation=target),terminal=terminal),
        screenshots=[{'path':r'C:\private\data.txt'}],token='TOP-SECRET')


def _snapshot(source=None):
    return dict(source_refs={'action_sources':[source or _source()]},graph={'action_sequence':[
        dict(sequence_index=1,event_id='event.1',previous_event_id=None,continuity_status='recorded_sequence')]})


def test_whitelist_preserves_factual_status_and_empty_ocr_not_raw_event():
    source=_source(); original=deepcopy(source)
    result=project_recorded_action_memory(_snapshot(source))
    record=result['recorded_actions'][0]
    assert record['action']['semantic_action']=='open_detail'
    assert record['target_observation']['text']==''
    assert record['target_observation']['label']=='Search'
    assert record['receipt']['effect_status']=='not_verified'
    assert record['receipt']['destination_status']=='not_evaluated'
    assert result['action_sequence'][0]['continuity_status']=='recorded_sequence'
    assert result['artifact_is_authorization'] is False
    text=json.dumps(result)
    assert 'TOP-SECRET' not in text and 'private' not in text and 'backend_receipt' not in text
    assert source==original


def test_preserves_variable_declaration_without_resolved_text():
    from app.agent.text_parameters import ReviewedTextParameters,ReviewedTextSource,text_parameter_reference
    s=_source();s['event']['before']['action']={'action_id':'fill','semantic_action':'fill_field'}
    s['event']['terminal']['action']=deepcopy(s['event']['before']['action'])
    ref=text_parameter_reference(ReviewedTextParameters('search',ReviewedTextSource('variable','place'),True,False,False,'restore_previous'))
    s['event']['before']['text_parameters_ref']=ref
    s['event']['before']['text_values']={'place':'TOP-SECRET'}
    out=project_recorded_action_memory(_snapshot(s))['recorded_actions'][0]
    assert out['text_parameters_ref']==ref
    assert 'TOP-SECRET' not in json.dumps(out)


def test_sensitive_literal_never_exports_literal_or_target_text():
    from app.agent.text_parameters import ReviewedTextParameters,ReviewedTextSource,text_parameter_reference
    s=_source();before=s['event']['before'];terminal=s['event']['terminal']
    before['action']={'action_id':'fill','semantic_action':'fill_field'};terminal['action']=deepcopy(before['action'])
    before['action']['text_parameters']=ReviewedTextParameters('field',ReviewedTextSource('literal','TOP-SECRET'),True,True,False,'restore_previous').to_payload()
    before['target_observation'].update(label='TOP-SECRET',text='TOP-SECRET',path=r'C:\private\data.txt')
    out=project_recorded_action_memory(_snapshot(s))['recorded_actions'][0]
    assert out['text_parameters_ref']['source_kind']=='literal'
    assert out['text_parameters_ref']['variable_name'] is None
    assert out['target_observation']['content_redacted'] is True
    assert 'TOP-SECRET' not in json.dumps(out) and 'private' not in json.dumps(out)


def test_conflicting_parameter_declaration_is_not_silently_chosen():
    from app.agent.text_parameters import ReviewedTextParameters,ReviewedTextSource,text_parameter_reference
    s=_source();before=s['event']['before'];terminal=s['event']['terminal']
    before['action']={'action_id':'fill','semantic_action':'fill_field'};terminal['action']=deepcopy(before['action'])
    ref=text_parameter_reference(ReviewedTextParameters('field',ReviewedTextSource('variable','place'),True,False,False,'restore_previous'))
    before['text_parameters_ref']=ref;terminal['evidence']['text_parameters_ref']={**ref,'variable_name':'other'}
    with pytest.raises(DesktopReviewError,match='parameter_conflict'):project_recorded_action_memory(_snapshot(s))


def test_preserves_scroll_parameters_without_spatial_raw_capture():
    s=_source();s['event']['before']['action']['semantic_action']='scroll_region'
    s['event']['terminal']['action']=deepcopy(s['event']['before']['action'])
    params=dict(contract_version='reviewed_scroll_parameters_v1',target_container_id='results',axis='vertical',direction='down',wheel_clicks=3,unit='wheel_detent')
    s['event']['before']['scroll_parameters']=params
    assert project_recorded_action_memory(_snapshot(s))['recorded_actions'][0]['scroll_parameters']==params


def test_missing_legacy_sources_and_sequence_are_explicit():
    result=project_recorded_action_memory({'source_refs':{},'graph':{}})
    assert result['source_status']=='unavailable' and result['sequence_status']=='unavailable'
    assert result['recorded_actions']==[] and result['action_sequence']==[]
    s=_snapshot();del s['graph']['action_sequence']
    assert project_recorded_action_memory(s)['sequence_status']=='unavailable'


def test_unknown_gap_is_not_upgraded_and_unknown_sequence_fields_are_not_exposed():
    snapshot=_snapshot();second=deepcopy(snapshot['source_refs']['action_sources'][0]);second['event_id']='event.2';second['event']['event_id']='event.2'
    snapshot['source_refs']['action_sources'].append(second)
    snapshot['graph']['action_sequence'].append(dict(sequence_index=2,event_id='event.2',previous_event_id='event.1',continuity_status='unknown_gap',token='TOP-SECRET'))
    result=project_recorded_action_memory(snapshot)
    assert result['action_sequence'][1]['continuity_status']=='unknown_gap'
    assert 'TOP-SECRET' not in json.dumps(result)


def test_production_memory_preserves_recorded_facts_after_editorial_save(tmp_path):
    with _rig(tmp_path) as (host,connection,segment):
        synced=host.fresh_learning.sync_actions(**_scope(connection,segment));wid=synced['logical_workflow_id']
        project=host.facade.load_workflow_project(wid)
        saved=host.facade.save_workflow_project(wid,project['content_sha256'],_changes(project),'action-memory-save')
        result=host._service.agent_call(connection['token'],'get_workflow_project_memory',{'workflow_id':wid,'snapshot_id':saved['snapshot_id']})
        memory=result['graph']['action_memory']
        assert memory['source_status']=='available' and len(memory['recorded_actions'])==1
        assert result['graph']['edges'][0]['editorial'] is True
        assert memory['recorded_actions'][0]['receipt']['dispatch_status']=='dispatched'
        assert 'token' not in json.dumps(memory) and str(tmp_path) not in json.dumps(memory)


def test_old_snapshot_does_not_read_new_action_graph(tmp_path,monkeypatch):
    with _rig(tmp_path) as (host,connection,segment):
        synced=host.fresh_learning.sync_actions(**_scope(connection,segment));wid=synced['logical_workflow_id']
        old=host.facade.get_workflow_project_memory(connection['task_id'],wid)
        _perform_action(tmp_path/'review',host.learning_segments,host.learning_segments.recorder,
            host.learning_segments.capture_archive,connection,segment['segment_id'],sequence=2)
        host.fresh_learning.sync_actions(**_scope(connection,segment))
        newest=host.facade.get_workflow_project_memory(connection['task_id'],wid)
        assert len(newest['graph']['action_memory']['recorded_actions'])==2
        assert newest['graph']['action_memory']['action_sequence'][1]['continuity_status']=='unknown_gap'
        load=host.facade.load_graph_revision;calls=[]
        def pinned(workflow_id,revision=None):
            calls.append(revision)
            assert revision is not None
            return load(workflow_id,revision)
        monkeypatch.setattr(host.facade,'load_graph_revision',pinned)
        assert host.facade.get_workflow_project_memory(connection['task_id'],wid,old['snapshot_id'])==old
        assert calls and all(r==old['source_revision'] for r in calls)


def test_production_memory_reopens_same_pinned_facts(tmp_path):
    from tests.test_formal_fresh_graph_source import REVIEWER
    with _rig(tmp_path) as (host,connection,segment):
        synced=host.fresh_learning.sync_actions(**_scope(connection,segment));wid=synced['logical_workflow_id']
        original=host.facade.get_workflow_project_memory(connection['task_id'],wid)
    reopened=host.__class__(tmp_path/'inbox.json',tmp_path/'review',REVIEWER)
    try:
        assert reopened.facade.get_workflow_project_memory(connection['task_id'],wid,original['snapshot_id'])==original
    finally:reopened.close()
