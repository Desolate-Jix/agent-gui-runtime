from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from app.agent.fresh_learning_observation import FreshLearningObservationPacket
from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.content_uia_stability import compare_content_uia_stability


def _control(cid, role, box, ancestors, name=None, patterns=None):
    return dict(provider='windows_uia', control_id=cid, name=name, control_type=role,
        automation_id=None, class_name=None, bbox=dict(zip(('x','y','w','h'),box)),
        screen_bbox=dict(zip(('x','y','w','h'),box)), enabled=True, visible=True,
        patterns=patterns or [], runtime_id=[42, int(cid[1:])], ancestor_control_ids=ancestors)


def _tree():
    controls = [_control('c0','Window',(0,0,320,200),[]),
        _control('c1','ToolBar',(0,20,320,40),['c0']),
        _control('c2','Button',(260,25,32,30),['c1','c0'],'Extension (28)',['Invoke']),
        _control('c3','Edit',(10,25,200,30),['c1','c0'],'https://example.test/page',['Value']),
        _control('c4','Document',(0,60,320,140),['c0'],'Example'),
        _control('c5','Text',(10,80,150,20),['c4','c0'],'Result text')]
    return dict(provider='windows_uia', provider_version='windows_uia_provider_v1', status='ok',
        scan_budget=100,scan_visited_count=6,scan_complete=True,truncated=False,truncation_reason=None,
        window=dict(handle=1,process_id=2,process_name='browser',title='Example',bbox=dict(x=0,y=0,w=320,h=200)),
        control_count=len(controls),controls=controls)


def _packet(tree, pixels=(), *, capture_id='cap-original'):
    im=Image.new('RGB',(320,200),'white')
    for point in pixels: im.putpixel(point,(0,0,0))
    out=BytesIO(); im.save(out,format='PNG'); png=out.getvalue()
    evidence=dict(target=dict(window_handle=1,process_id=2,rect=dict(x=0,y=0,width=320,height=200)),
        application=dict(kind='web',canonical_origin='https://example.test',process_create_time=1.25),
        capture=dict(capture_id=capture_id,screenshot_sha256=sha256(png).hexdigest(),viewport_size=dict(width=320,height=200)),
        uia={**{k:tree[k] for k in ('provider','provider_version','status','control_count')},'snapshot_sha256':payload_sha256(tree)})
    return FreshLearningObservationPacket(png,json.dumps(evidence).encode())


def _pair():
    old=_tree(); new=deepcopy(old);new['controls'][2]['name']='Extension (29)'
    pixels=[(261+i%20,26+i//20) for i in range(61)]
    return dict(original_packet=_packet(old),current_packet=_packet(new,pixels,capture_id='cap-current'),original_uia=old,current_uia=new)


def test_exact_proof_is_serializable_and_non_mutating():
    tree=_tree(); packet=_packet(tree); args=dict(original_packet=packet,current_packet=packet,original_uia=tree,current_uia=deepcopy(tree))
    before=deepcopy(args['original_uia']); proof=compare_content_uia_stability(**args)
    assert proof['policy']=='exact_content_surface_v1'
    assert proof['changed_pixel_count']==0
    assert args['original_uia']==before
    json.dumps(proof,allow_nan=False)


def test_61_badge_pixels_are_allowed_without_masking_toolbar():
    args=_pair(); proof=compare_content_uia_stability(**args)
    assert proof['policy']=='content_toolbar_leaf_names_v1'
    assert proof['changed_pixel_count']==61
    assert [c['control_id'] for c in proof['changes']]==['c2']


def test_unnamed_structural_overlap_is_not_a_competing_button():
    args=_pair()
    for tree in (args['original_uia'],args['current_uia']):
        tree['controls'].append(_control('c6','Group',(0,20,320,40),['c0']))
        tree['control_count']+=1;tree['scan_visited_count']+=1
    args['original_packet']=_packet(args['original_uia'])
    args['current_packet']=_packet(args['current_uia'],[(261,26)])
    assert compare_content_uia_stability(**args)['changed_pixel_count']==1


def test_nested_document_is_part_of_unique_content_root():
    tree=_tree();tree['controls'][5]['control_type']='Document'
    packet=_packet(tree)
    assert compare_content_uia_stability(original_packet=packet,current_packet=packet,
        original_uia=tree,current_uia=deepcopy(tree))['document_roots'][0]['control_id']=='c4'


@pytest.mark.parametrize('same_box',[False,True])
def test_all_parallel_document_roots_are_protected(same_box):
    args=_pair()
    for tree in (args['original_uia'],args['current_uia']):
        if not same_box:
            for key in ('bbox','screen_bbox'):tree['controls'][4][key]['w']=160
        tree['controls'].append(_control('c6','Document',(0,60,320,140) if same_box else (160,60,160,140),['c0'],None))
        tree['control_count']+=1;tree['scan_visited_count']+=1
    args['original_packet']=_packet(args['original_uia'])
    args['current_packet']=_packet(args['current_uia'],[(261,26)])
    proof=compare_content_uia_stability(**args)
    assert [d['control_id'] for d in proof['document_roots']]==['c4','c6']


@pytest.mark.parametrize('root_index',[4,6])
@pytest.mark.parametrize('change',['name','runtime','bbox','child_text','pixels'])
def test_change_in_either_document_root_is_rejected(root_index,change):
    old=_tree();old['controls'].append(_control('c6','Document',(0,60,320,140),['c0'],None))
    old['controls'].append(_control('c7','Text',(10,110,150,20),['c6','c0'],'Second content'))
    old['control_count']+=2;old['scan_visited_count']+=2
    new=deepcopy(old);pixels=[]
    if change=='name':new['controls'][root_index]['name']='Changed'
    elif change=='runtime':new['controls'][root_index]['runtime_id']=[42,99]
    elif change=='bbox':
        for k in ('bbox','screen_bbox'):new['controls'][root_index][k]['h']-=1
    elif change=='child_text':new['controls'][5 if root_index==4 else 7]['name']='Changed'
    else:pixels=[(15,85 if root_index==4 else 115)]
    with pytest.raises(ValueError):compare_content_uia_stability(original_packet=_packet(old),current_packet=_packet(new,pixels),original_uia=old,current_uia=new)


def test_run51_archived_original_packet_protects_both_real_roots():
    root=Path(__file__).resolve().parents[1]/'.superpowers/sdd/2026-09-14-continuous-map/run-51/data/reviews/runtime_state'
    sidecars=list((root/'learning-content-v1/source-contexts').glob('*.json'))
    records=list((root/'fresh-learning-v1/records').glob('*.json'))
    if len(sidecars)!=1 or len(records)!=1:
        pytest.skip('optional local run51 original evidence is unavailable')
    sidecar=json.loads(sidecars[0].read_text(encoding='utf-8'))
    record=json.loads(records[0].read_text(encoding='utf-8'))
    png=root/'fresh-learning-v1/png'/f"{record['screenshot_sha256']}.png"
    if not png.exists():pytest.skip('original run51 PNG is unavailable')
    packet=FreshLearningObservationPacket(png.read_bytes(),record['evidence_json'].encode('utf-8'))
    proof=compare_content_uia_stability(original_packet=packet,current_packet=packet,
        original_uia=sidecar['uia'],current_uia=sidecar['uia'])
    assert len(proof['document_roots'])==2
    assert proof['changed_pixel_count']==0


def test_incomplete_exact_tree_is_not_accepted():
    tree=_tree();tree['scan_complete']=False;packet=_packet(tree)
    with pytest.raises(ValueError):compare_content_uia_stability(original_packet=packet,current_packet=packet,
        original_uia=tree,current_uia=tree)


@pytest.mark.parametrize('change', ['body_pixels','outside_pixels','pixel_boundary','body_text','address','new_control','reorder','missing_ancestor','incomplete','missing_runtime','duplicate_runtime','document_duplicate','document_hidden','overlap_button','overlap_body','window_title','geometry','pattern'])
def test_rejects_changes_outside_independent_toolbar_leaf(change):
    args=_pair(); tree=args['current_uia']; pixels=[(261,26)]
    if change=='body_pixels':pixels.append((15,85))
    elif change=='outside_pixels':pixels.append((1,21))
    elif change=='pixel_boundary':pixels.append((292,30))
    elif change=='body_text':tree['controls'][5]['name']='Other result'
    elif change=='address':tree['controls'][3]['name']='https://example.test/other'
    elif change=='new_control':tree['controls'].append(_control('c6','Button',(200,80,20,20),['c4','c0'],'New',['Invoke']));tree['control_count']+=1;tree['scan_visited_count']+=1
    elif change=='reorder':tree['controls'][2:4]=tree['controls'][2:4][::-1]
    elif change=='missing_ancestor':tree['controls'][2]['ancestor_control_ids']=['missing','c0']
    elif change=='incomplete':tree['scan_complete']=False
    elif change=='missing_runtime':tree['controls'][2]['runtime_id']=None
    elif change=='duplicate_runtime':tree['controls'][2]['runtime_id']=[42,3]
    elif change=='document_duplicate':tree['controls'][5]['control_type']='Document';tree['controls'][5]['ancestor_control_ids']=['c0']
    elif change=='document_hidden':tree['controls'][4]['visible']=False
    elif change in ('overlap_button','overlap_body'):
        other=_control('c6','Button',(270,25,20,20),['c4','c0'] if change=='overlap_body' else ['c1','c0'],'Other',['Invoke'])
        for target in (args['original_uia'],tree):target['controls'].append(deepcopy(other));target['control_count']+=1;target['scan_visited_count']+=1
        args['original_packet']=_packet(args['original_uia'])
    elif change=='window_title':tree['window']['title']='Other page'
    elif change=='geometry':tree['controls'][2]['bbox']['x']+=1;tree['controls'][2]['screen_bbox']['x']+=1
    elif change=='pattern':tree['controls'][2]['patterns'].append('Value')
    args['current_packet']=_packet(tree,pixels,capture_id='cap-current')
    with pytest.raises(ValueError):compare_content_uia_stability(**args)


@pytest.mark.parametrize('change',['png','missing_png_digest','uia_digest','identity','viewport','missing_tree'])
def test_rejects_packet_binding_tampering(change):
    args=_pair(); packet=args['current_packet'];e=packet.evidence();png=packet.png_bytes
    if change=='png':png=args['original_packet'].png_bytes
    elif change=='missing_png_digest':del e['capture']['screenshot_sha256']
    elif change=='uia_digest':e['uia']['snapshot_sha256']='0'*64
    elif change=='identity':e['application']['process_create_time']=2.5
    elif change=='viewport':e['capture']['viewport_size']['width']=319
    elif change=='missing_tree':args['original_uia']=None
    args['current_packet']=FreshLearningObservationPacket(png,json.dumps(e).encode())
    with pytest.raises(ValueError):compare_content_uia_stability(**args)
