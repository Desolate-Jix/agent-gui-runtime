"""填写视觉证明贯通原观察、预览、消费和后端；不派发真实输入。"""
import json
from hashlib import sha256

from PIL import Image
import pytest

from app.agent.live_controller import LiveControllerDecision
from tests.test_fresh_text_dispatch import _ready_text


def _change_capture(owner, monkeypatch, *, changed_pixel=False):
    capture = owner._screenshot_service.capture_window
    def altered(**kwargs):
        result = capture(**kwargs)
        with Image.open(owner._screenshot_service.path) as source:
            image = source.convert('RGB')
        if changed_pixel:
            image.putpixel((10, 10), (0, 0, 0))
        image.save(owner._screenshot_service.path, compress_level=0)
        return result
    monkeypatch.setattr(owner._screenshot_service, 'capture_window', altered)


def test_same_pixels_with_new_png_hash_revalidate_twice_and_persist_proof(tmp_path, monkeypatch):
    with _ready_text(tmp_path) as (_host, owner, runtime, native_input, claims, _session, _scope, cid, _params):
        _change_capture(owner, monkeypatch)
        calls = []
        recognize, reader = owner._recognize, owner.read_text_field
        def recognized(**kwargs):
            calls.append('recognize')
            return recognize(**kwargs)
        def read(**kwargs):
            calls.append('focused_read' if kwargs.get('require_keyboard_focus') else 'field_read')
            return reader(**kwargs)
        monkeypatch.setattr(owner, '_recognize', recognized)
        monkeypatch.setattr(owner, 'read_text_field', read)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.effect_status == 'verified' and len(native_input.calls) == 1
        assert calls[:4] == ['recognize', 'field_read', 'recognize', 'field_read']
        record = json.loads((claims.root / ('text-visual-stability-' + cid.split('.')[-1] + '.json')).read_text(encoding='utf-8'))
        assert record['confirmation_id'] == cid and record['artifact_is_authorization'] is False
        assert record['approved_preview_sha256'] != record['fresh_preview_sha256']
        proof = record['proof']
        assert proof['before_screenshot_sha256'] != proof['after_screenshot_sha256']
        assert proof['changed_pixels'] == 0
        consume_path = claims.root / 'grounded-consume-started' / (cid.split('.')[-1] + '.json')
        assert record['consume_content_sha256'] == sha256(consume_path.read_bytes()).hexdigest()
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native_input.calls) == 1


def test_field_pixel_change_cannot_use_distant_animation_scope(tmp_path, monkeypatch):
    with _ready_text(tmp_path) as (_host, owner, runtime, native_input, claims, _session, _scope, cid, _params):
        _change_capture(owner, monkeypatch, changed_pixel=True)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert isinstance(result, LiveControllerDecision)
        assert result.reason_code == 'grounded_confirmation_stale'
        assert native_input.calls == []
        assert not (claims.root / 'grounded-consume-started' / (cid.split('.')[-1] + '.json')).exists()


@pytest.mark.parametrize('fault', ['missing', 'fresh_preview_sha256', 'confirmation_id', 'consume_content_sha256', 'proof'])
def test_reopened_consume_requires_intact_visual_proof(tmp_path, monkeypatch, fault):
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
    from app.agent.fresh_learning_action_contracts import canonical_json_bytes
    with _ready_text(tmp_path) as (_host, owner, runtime, native_input, claims, _session, _scope, cid, _params):
        _change_capture(owner, monkeypatch)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root,
            receipt_store=claims._receipt_store, create_layout=False)
        assert reopened.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
        path = claims.root / ('text-visual-stability-' + cid.split('.')[-1] + '.json')
        original = path.read_bytes()
        try:
            if fault == 'missing':
                path.unlink()
            else:
                value = json.loads(original)
                if fault == 'proof':
                    value['proof']['changed_pixels'] += 1
                else:
                    value[fault] = '0' * 64
                path.write_bytes(canonical_json_bytes(value))
            with pytest.raises(RuntimeIntentClaimStoreError):
                reopened.get_for_grounded_confirmation(confirmation_id=cid)
            assert len(native_input.calls) == 1
        finally:
            path.write_bytes(original)


def test_consume_rejects_serialized_proof_without_local_typed_validation(tmp_path, monkeypatch):
    with _ready_text(tmp_path) as (_host, owner, runtime, native_input, claims, _session, _scope, cid, _params):
        _change_capture(owner, monkeypatch)
        begin = claims.begin_fresh_confirmation_consume
        def untrusted(*args, **kwargs):
            kwargs['text_visual_proof'] = kwargs['text_visual_proof'].to_reference()
            return begin(*args, **kwargs)
        monkeypatch.setattr(claims, 'begin_fresh_confirmation_consume', untrusted)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert isinstance(result, LiveControllerDecision)
        assert result.reason_code == 'fresh_dispatch_preparation_failed'
        assert native_input.calls == []
