"""从项目已固定的图来源投影动作记忆；不读取最新图或导出原始事件。"""
from copy import deepcopy
import re

from .workspace import DesktopReviewError


_RECEIPT_FIELDS = {'receipt_id','receipt_content_sha256','intent_id','outcome','reason_code',
    'attempt_count','gate_status','dispatch_status','effect_status','destination_status','next_observation_id'}
_TARGET_FIELDS = {'contract_version','capture_id','screenshot_sha256','candidate_id','element_id','label','text','role'}
_SEQUENCE_FIELDS = {'sequence_index','event_id','previous_event_id','continuity_status'}
_TEXT_FIELDS = {'contract_version','parameters_sha256','target_field_id','source_kind','variable_name',
    'clear_existing','sensitive','submit','clipboard_policy'}
_SCROLL_FIELDS = {'contract_version','target_container_id','axis','direction','wheel_clicks','unit'}


def _fields(value, allowed):
    if not isinstance(value,dict):
        raise DesktopReviewError('workflow_action_memory_invalid_source')
    result={k:deepcopy(v) for k,v in value.items() if k in allowed}
    if any(type(v) not in (str,int,bool,type(None)) for v in result.values()):
        raise DesktopReviewError('workflow_action_memory_invalid_scalar')
    return result


def _declaration(before, terminal, name, allowed):
    sources=[before.get(name),before.get('action',{}).get(name),terminal.get('action',{}).get(name),
             terminal.get('evidence',{}).get(name)]
    values=[_fields(v,allowed) for v in sources if v is not None]
    if values and any(v!=values[0] for v in values):
        raise DesktopReviewError('workflow_action_memory_parameter_conflict')
    return values[0] if values else None


def project_recorded_action_memory(snapshot):
    """仅白名单导出已封存事实；缺失信息明确保留未知，不推导授权或成功。"""
    graph=snapshot.get('graph',{})
    sources=snapshot.get('source_refs',{}).get('action_sources')
    result=dict(contract_version='workflow_project_action_memory_v1',
        source_status='unavailable' if sources is None else 'available',sequence_status='unavailable',
        action_sequence=[],recorded_actions=[],artifact_is_authorization=False,
        execute_binding_enabled=False,action_executed=False)
    if sources is None:
        result['missing_fields']=['recorded_action_sources']
        return result
    if not isinstance(sources,list):
        raise DesktopReviewError('workflow_action_memory_invalid_sources')
    ids=[]
    for source in sources:
        if (not isinstance(source,dict) or not isinstance(source.get('source_sha256'),str)
                or re.fullmatch(r'[0-9a-f]{64}',source['source_sha256']) is None
                or not isinstance(source.get('event'),dict)):
            raise DesktopReviewError('workflow_action_memory_invalid_source')
        event=source.get('event',{});before=event.get('before',{});terminal=event.get('terminal',{})
        event_id=source.get('event_id')
        if not isinstance(event_id,str) or not event_id or event_id in ids or event.get('event_id')!=event_id:
            raise DesktopReviewError('workflow_action_memory_invalid_event_identity')
        ids.append(event_id)
        record=dict(event_id=event_id,source_sha256=source.get('source_sha256'),
            action=_fields(before.get('action'),{'action_id','semantic_action'}),
            receipt=_fields(terminal,_RECEIPT_FIELDS))
        if record['action']!=_fields(terminal.get('action'),{'action_id','semantic_action'}):
            raise DesktopReviewError('workflow_action_memory_action_conflict')
        target=before.get('target_observation')
        record['target_observation_status']='unavailable' if target is None else 'recorded'
        if target is not None:
            record['target_observation']=_fields(target,_TARGET_FIELDS)
        semantic=record['action'].get('semantic_action')
        if semantic=='fill_field':
            declaration=_declaration(before,terminal,'text_parameters_ref',_TEXT_FIELDS)
            if declaration is None:
                # 旧 reviewed 事件若保留原声明，仅派生无原文引用，不导出填写值。
                from app.agent.text_parameters import ReviewedTextParameters,text_parameter_reference
                raw=before.get('action',{}).get('text_parameters')
                if raw is not None:
                    declaration=text_parameter_reference(ReviewedTextParameters.from_payload(raw))
            record['text_parameters_status']='unavailable' if declaration is None else 'recorded'
            if declaration is not None:
                from app.agent.text_parameters import validate_text_parameter_reference
                record['text_parameters_ref']=validate_text_parameter_reference(declaration)
                if declaration['sensitive'] and 'target_observation' in record:
                    record['target_observation'].update(label='',text='',content_redacted=True)
        if semantic=='scroll_region':
            declaration=_declaration(before,terminal,'scroll_parameters',_SCROLL_FIELDS)
            record['scroll_parameters_status']='unavailable' if declaration is None else 'recorded'
            if declaration is not None:
                from app.agent.scroll_parameters import ReviewedScrollParameters
                record['scroll_parameters']=ReviewedScrollParameters.from_payload(declaration).to_payload()
        result['recorded_actions'].append(record)
    sequence=graph.get('action_sequence')
    if sequence is None:
        result['missing_fields']=['action_sequence']
    else:
        if not isinstance(sequence,list):
            raise DesktopReviewError('workflow_action_memory_invalid_sequence')
        projected=[_fields(item,_SEQUENCE_FIELDS) for item in sequence]
        if (len(projected)!=len(ids) or [item.get('event_id') for item in projected]!=ids
                or any(set(item)!=_SEQUENCE_FIELDS for item in projected)):
            raise DesktopReviewError('workflow_action_memory_sequence_source_mismatch')
        result['sequence_status']='recorded'
        result['action_sequence']=projected
    return result
