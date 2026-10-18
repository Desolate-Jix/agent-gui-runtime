"""工具栏名称变化经实际填写控制器、持久回验与输入保护；无系统输入。"""
import json

from PIL import Image
import pytest

from app.agent.fresh_learning_action_contracts import canonical_json_bytes
from app.agent.live_controller import LiveControllerDecision
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from tests.test_fresh_text_dispatch import _ready_text
from tests.test_fresh_text_preview import _native_owner
from tests.test_formal_fresh_learning_observation import _bound, _WindowManager, _OriginReader


def _control(identity, role, name, bbox, ancestors, runtime):
    x,y,w,h = bbox
    return {'provider':'windows_uia','control_id':identity,'name':name,'control_type':role,
        'automation_id':None,'class_name':None,'bbox':dict(x=x,y=y,w=w,h=h),
        'screen_bbox':dict(x=x+10,y=y+20,w=w,h=h),'enabled':True,'visible':True,
        'patterns':[],'runtime_id':runtime,'ancestor_control_ids':ancestors}


def _install_fixture(monkeypatch, kind='native'):
    class Provider:
        fault = None
        name = 'Unread 1'
        def snapshot_window(self,bound):
            controls = [
                _control('root','Window','Fixture',(0,0,360,260),[],[42,1]),
                _control('context','Document' if kind=='web' else 'Group','Content',(0,0,180,100),['root'],[42,2]),
                _control('fresh.search','Edit','Search field',(10,10,120,40),['context','root'],[42,12]),
                _control('toolbar','ToolBar','Tools',(245,160,100,50),['root'],[42,3]),
                _control('badge','Button',self.name,(260,170,20,20),['toolbar','root'],[42,4]),
            ]
            controls[2]['patterns'] = ['Value','Text']
            if self.fault == 'field_name': controls[2]['name'] = 'Different field'
            if self.fault == 'context_name': controls[1]['name'] = 'Different form'
            if self.fault == 'overlay':
                controls.append(_control('overlay','Pane','Overlay',(10,10,120,40),['root'],[42,5]))
            if self.fault == 'badge_geometry': controls[4]['bbox']['x'] += 1
            return {'provider':'windows_uia','provider_version':'windows_uia_provider_v1','status':'ok',
                'window':{'handle':4242,'process_id':9001,'process_name':'fixture.exe','title':'Fixture',
                    'bbox':{'x':0,'y':0,'w':360,'h':260}},
                'scan_budget':1000,'scan_visited_count':len(controls),'scan_complete':True,
                'truncated':False,'truncation_reason':None,'controls':controls,'control_count':len(controls)}
    provider = Provider()
    def factory(root):
        owner = _native_owner(root)
        owner._window_manager = _WindowManager(*[_bound(width=360,height=260) for _ in range(200)])
        owner._screenshot_service.width,owner._screenshot_service.height = 360,260
        owner._uia_provider = provider
        if kind == 'web':
            owner.application = {'kind':'web','canonical_origin':'https://fixture.example'}
            owner._origin_reader = _OriginReader(*['https://fixture.example']*100)
        return owner
    monkeypatch.setattr('tests.test_fresh_text_confirmation._native_owner',factory)
    return provider


@pytest.mark.parametrize('kind',['native','web'])
def test_toolbar_name_only_fill_and_reopen_preserve_original_facts(tmp_path,monkeypatch,kind):
    provider = _install_fixture(monkeypatch,kind)
    with _ready_text(tmp_path) as (_,owner,runtime,native,claims,session,scope,cid,params):
        before = runtime.get_local_grounded_confirmation(confirmation_id=cid).grounded_confirmation.preview.to_dict()
        provider.name = '\u672a\u8bfb 2'
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result,LiveControllerDecision), result
        assert result.effect_status == 'verified' and len(native.calls) == 1
        record = json.loads((claims.root / ('text-visual-stability-'+cid.split('.')[-1]+'.json')).read_text(encoding='utf-8'))
        assert record['proof']['contract_version'] == 'text_visual_stability_attestation_v3'
        assert record['proof']['changed_pixels'] == 0
        assert record['proof']['before_screenshot_sha256'] == record['proof']['after_screenshot_sha256']
        assert record['proof']['uia_stability']['changes'][0]['control_id'] == 'badge'
        assert before['uia_snapshot']['controls'][4]['name'] == 'Unread 1'
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root,receipt_store=claims._receipt_store,create_layout=False)
        assert reopened.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native.calls) == 1


@pytest.mark.parametrize('fault',['field_name','context_name','overlay','badge_geometry','protected_pixel'])
def test_target_context_and_protected_pixels_still_reject(tmp_path,monkeypatch,fault):
    provider = _install_fixture(monkeypatch)
    with _ready_text(tmp_path) as (_,owner,runtime,native,claims,session,scope,cid,params):
        provider.name = 'Unread 2'
        if fault == 'protected_pixel':
            original = owner._screenshot_service.capture_window
            def capture(**kwargs):
                result = original(**kwargs)
                with Image.open(owner._screenshot_service.path) as opened:
                    image = opened.convert('RGB')
                image.putpixel((10,20),(255,255,255))
                image.save(owner._screenshot_service.path)
                return result
            monkeypatch.setattr(owner._screenshot_service,'capture_window',capture)
        else:
            provider.fault = fault
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert isinstance(result,LiveControllerDecision) and result.reason_code == 'grounded_confirmation_stale'
        assert native.calls == []


@pytest.mark.parametrize('fault',['missing','uia_name_hash','uia_index','uia_missing','version','capture'])
def test_reopen_recomputes_uia_proof_even_when_png_is_identical(tmp_path,monkeypatch,fault):
    provider = _install_fixture(monkeypatch)
    with _ready_text(tmp_path) as (_,owner,runtime,native,claims,session,scope,cid,params):
        provider.name = 'Unread 2'
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result,LiveControllerDecision), result
        path = claims.root / ('text-visual-stability-'+cid.split('.')[-1]+'.json')
        original = path.read_bytes()
        data = json.loads(original)
        try:
            if fault == 'missing': path.unlink()
            else:
                if fault == 'uia_name_hash': data['proof']['uia_stability']['changes'][0]['after_name_sha256'] = '0'*64
                if fault == 'uia_index': data['proof']['uia_stability']['changes'][0]['index'] = 2
                if fault == 'uia_missing': data['proof'].pop('uia_stability')
                if fault == 'version': data['proof']['contract_version'] = 'text_visual_stability_attestation_v1'
                if fault == 'capture': data['proof']['after_evidence_sha256'] = '0'*64
                path.write_bytes(canonical_json_bytes(data))
            reopened = RuntimeIntentClaimStore(project_root=claims.project_root,receipt_store=claims._receipt_store,create_layout=False)
            with pytest.raises(RuntimeIntentClaimStoreError):
                reopened.get_for_grounded_confirmation(confirmation_id=cid)
            assert len(native.calls) == 1
        finally:
            path.write_bytes(original)
