"""只读正文的同帧 UIA 与逐像素上下文证明；不产生动作授权。"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import re

from PIL import Image

from app.agent.control_uia_stability import (
    ControlContextIdentity, _CONTROL_KEYS, _SNAPSHOT_KEYS, _WINDOW_KEYS,
    _box, _contains, _overlaps, _snapshot,
)
from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.fresh_learning_observation import FreshLearningObservationPacket


def _reject(reason):
    raise ValueError('content UIA stability: ' + reason)


def _tree(uia):
    if (not isinstance(uia, dict) or set(uia) != _SNAPSHOT_KEYS
            or not isinstance(uia.get('window'), dict) or set(uia['window']) != _WINDOW_KEYS
            or not isinstance(uia.get('controls'), list)
            or uia['scan_complete'] is not True or uia['truncated'] is not False
            or uia['truncation_reason'] is not None
            or type(uia['scan_budget']) is not int or type(uia['scan_visited_count']) is not int
            or not len(uia['controls']) <= uia['scan_visited_count'] < uia['scan_budget']):
        _reject('complete original and current trees are required')
    indexed, runtimes = {}, set()
    for control in uia['controls']:
        if not isinstance(control, dict) or set(control) != _CONTROL_KEYS:
            _reject('unknown control schema')
        cid, runtime = control['control_id'], control['runtime_id']
        if (not isinstance(cid, str) or not cid or cid in indexed
                or type(runtime) is not list or not 1 <= len(runtime) <= 64
                or any(type(value) is not int for value in runtime) or tuple(runtime) in runtimes
                or control['provider'] != 'windows_uia'
                or not isinstance(control['control_type'], str) or not control['control_type']
                or any(control[k] is not None and not isinstance(control[k], str)
                       for k in ('name','automation_id','class_name'))
                or any(control[k] is not None and type(control[k]) is not bool for k in ('enabled','visible'))
                or type(control['patterns']) is not list
                or any(not isinstance(p, str) for p in control['patterns'])
                or len(control['patterns']) != len(set(control['patterns']))):
            _reject('control identity is incomplete or duplicated')
        _box(control['bbox']); _box(control['screen_bbox'])
        indexed[cid] = control
        runtimes.add(tuple(runtime))
    for cid, control in indexed.items():
        chain = control['ancestor_control_ids']
        if (type(chain) is not list or any(not isinstance(a,str) or a not in indexed for a in chain)
                or cid in chain or len(chain) != len(set(chain))):
            _reject('ancestor references are missing or invalid')
        if any(indexed[a]['ancestor_control_ids'] != chain[i+1:] for i,a in enumerate(chain)):
            _reject('ancestor chain is inconsistent')
    roots = [c for c in indexed.values() if not c['ancestor_control_ids']]
    if len(roots) != 1 or roots[0]['control_type'] != 'Window':
        _reject('one complete window root is required')
    documents = [c for c in indexed.values() if c['control_type'] == 'Document' and c['visible'] is True
        and not any(indexed[a]['control_type'] == 'Document' and indexed[a]['visible'] is True
                    for a in c['ancestor_control_ids'])]
    if not documents:
        _reject('at least one visible document content root is required')
    return indexed, documents


def _image(packet, evidence):
    digest = evidence.get('capture', {}).get('screenshot_sha256')
    if (type(packet.png_bytes) is not bytes or not isinstance(digest,str)
            or sha256(packet.png_bytes).hexdigest() != digest):
        _reject('PNG digest differs from capture')
    try:
        with Image.open(BytesIO(packet.png_bytes)) as source:
            if source.format != 'PNG':
                _reject('capture must be PNG')
            viewport = evidence['capture']['viewport_size']
            if source.size != (viewport['width'], viewport['height']):
                _reject('PNG viewport differs from capture')
            return source.convert('RGBA')
    except (OSError, KeyError, TypeError) as error:
        raise ValueError('content UIA stability: invalid PNG capture') from error


def compare_content_context(*, original_packet, current_packet, original_uia, current_uia):
    """冷重算正文不变证明；只允许正文之外工具栏叶名称及其框内像素变化。"""
    if type(original_packet) is not FreshLearningObservationPacket or type(current_packet) is not FreshLearningObservationPacket:
        _reject('typed observation packets are required')
    before, documents = _tree(original_uia)
    after, current_documents = _tree(current_uia)
    old, new = original_packet.evidence(), current_packet.evidence()
    if any(old.get(k) != new.get(k) for k in ('target','application')):
        _reject('target or application identity changed')
    try:
        target = old['target']; rect = target['rect']; app = old['application']
        # 并列包装层或多正文窗格全部验证，不能选择其中一个忽略其余。
        for document in documents:
            identity = ControlContextIdentity(window_handle=target['window_handle'],process_id=target['process_id'],
                process_create_time=app['process_create_time'],runtime_id=tuple(document['runtime_id']),
                window_rect=tuple(rect[k] for k in ('x','y','width','height')),control_bbox=_box(document['bbox']))
            digests = [_snapshot(e,t,identity) for e,t in ((old,original_uia),(new,current_uia))]
    except (KeyError, TypeError) as error:
        raise ValueError('content UIA stability: invalid packet identity') from error
    for indexed in (before,after):
        for c in indexed.values():
            box = _box(c['bbox'])
            if _box(c['screen_bbox']) != (box[0]+rect['x'],box[1]+rect['y'],box[2],box[3]):
                _reject('screen geometry differs from window binding')
    if documents != current_documents:
        _reject('document identity or content root changed')
    if ({k:v for k,v in original_uia.items() if k != 'controls'}
            != {k:v for k,v in current_uia.items() if k != 'controls'}):
        _reject('tree structure or window URL/title changed')
    document_ids = {d['control_id'] for d in documents}
    content_ids = {cid for cid,c in before.items() if cid in document_ids
                   or document_ids.intersection(c['ancestor_control_ids'])}
    protected = content_ids | {a for d in documents for a in d['ancestor_control_ids']}
    viewport = (0,0,rect['width'],rect['height'])
    changes = []
    for index,(a,b) in enumerate(zip(original_uia['controls'],current_uia['controls'])):
        if a == b:
            continue
        cid=a['control_id']; box=_box(a['bbox'])
        if (cid in protected or {k:v for k,v in a.items() if k != 'name'} != {k:v for k,v in b.items() if k != 'name'}
                or any(cid in c['ancestor_control_ids'] for c in before.values())
                or any(not isinstance(c['name'],str) or not c['name'].strip() for c in (a,b))
                or a['visible'] is not True
                or a['control_type'] not in {'Button','Text','Image'}
                or set(a['patterns']) - {'Invoke','InvokePattern'}
                or any(re.search(r'(?i)(?:https?|file|ftp)://',c['name']) for c in (a,b))):
            _reject('change is not an independent non-editable leaf name')
        toolbars=[before[x] for x in a['ancestor_control_ids'] if before[x]['control_type']=='ToolBar']
        if (not toolbars or toolbars[0]['control_id'] in protected
                or not _contains(viewport,box) or not _contains(_box(toolbars[0]['bbox']),box)
                or any(_overlaps(box,_box(before[x]['bbox'])) for x in content_ids)):
            _reject('changed toolbar leaf overlaps content')
        # 容器背景不等于另一个命中控件；真实按钮、字段等竞争控件仍保留。
        for other in before.values():
            if other['control_id']==cid or other['control_id'] in a['ancestor_control_ids']:
                continue
            structural=other['control_type'] in {'Group','Pane','Window','ToolBar'} and not other['name'] and not set(other['patterns'])-{'Invoke','InvokePattern'}
            if not structural and other['visible'] is not False and _overlaps(box,_box(other['bbox'])):
                _reject('changed leaf overlaps another visible control')
        changes.append(dict(index=index,control_id=cid,bbox=dict(a['bbox']),
            before_name_sha256=sha256(a['name'].encode('utf-8')).hexdigest(),
            after_name_sha256=sha256(b['name'].encode('utf-8')).hexdigest()))
    original_image,current_image = _image(original_packet,old),_image(current_packet,new)
    # 按完整 RGBA 像素检查；不掩盖工具栏或正文的任何其他区域。
    import numpy as np
    changed=np.any(np.asarray(original_image)!=np.asarray(current_image),axis=2)
    count=int(np.count_nonzero(changed))
    remaining=changed.copy()
    for item in changes:
        x,y,w,h=_box(item['bbox']);remaining[y:y+h,x:x+w]=False
    if remaining.any():
        _reject('pixels changed outside proven toolbar leaf boxes')
    return dict(contract_version='content_uia_stability_v1',
        policy='content_toolbar_leaf_names_v1' if changes else 'exact_content_surface_v1',
        original_capture_sha256=payload_sha256(old['capture']),current_capture_sha256=payload_sha256(new['capture']),
        before_png_sha256=old['capture']['screenshot_sha256'],after_png_sha256=new['capture']['screenshot_sha256'],
        before_uia_sha256=digests[0],after_uia_sha256=digests[1],
        document_roots=[{'control_id':d['control_id'],'runtime_id':list(d['runtime_id']),'bbox':dict(d['bbox'])}
                        for d in documents],
        identity_sha256=payload_sha256({'target':old['target'],'application':old['application']}),
        content_sha256=payload_sha256({'controls':[c for c in original_uia['controls'] if c['control_id'] in content_ids]}),
        changes=changes,changed_pixel_count=count,artifact_is_authorization=False,execute_binding_enabled=False,action_executed=False)


compare_content_uia_stability = compare_content_context
