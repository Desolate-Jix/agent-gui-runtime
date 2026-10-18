"""首次学习最终被动截图的小动画不要求先伪造已学习控件。"""

import json
import pytest

from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from tests.test_fresh_navigation_stability import _ready, _alter


@pytest.mark.parametrize('final_only', [False, True])
def test_first_learning_final_far_pixel_has_archived_proof_and_one_dispatch(tmp_path, monkeypatch, final_only):
    with _ready(tmp_path, monkeypatch, learned=False) as (coordinator, runtime, backend, owner, view):
        assert view['preview']['intent'].get('learned_control') is None
        _alter(owner, monkeypatch, point_delta=0, final_only=final_only)
        response = coordinator.execute(confirmation_id=view['confirmation_id'])
        assert response['kind'] == 'receipt', response
        assert len(backend.commands) == 1
        claims = runtime._intent_claim_store
        cid = view['confirmation_id']
        record = json.loads((claims.root / ('navigation-visual-stability-' + cid.split('.')[-1] + '.json')).read_text(encoding='utf-8'))
        assert (record['proof'] is None) == final_only
        assert record['visibility']['proof']['changed_pixels'] == 1
        assert record['visibility']['proof']['recognition_status'] == 'not_requested'
        assert record['artifact_is_authorization'] is False
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root,
            receipt_store=claims._receipt_store, create_layout=False)
        assert reopened.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
        assert runtime.consume_grounded_confirmation(confirmation_id=cid).model_dump(mode='json') == response['payload']
        assert len(backend.commands) == 1


@pytest.mark.parametrize('point_delta,pixel,final_only', [
    (1, None, False), (0, (60, 30), True), (0, (140, 55), True),
])
def test_first_learning_does_not_relax_recognition_or_target_visibility(tmp_path, monkeypatch, point_delta, pixel, final_only):
    with _ready(tmp_path, monkeypatch, learned=False) as (coordinator, runtime, backend, owner, view):
        _alter(owner, monkeypatch, point_delta=point_delta, pixel=pixel, final_only=final_only)
        response = coordinator.execute(confirmation_id=view['confirmation_id'])
        assert response['kind'] == 'decision'
        assert response['payload']['reason_code'] == 'grounded_confirmation_stale'
        assert backend.commands == []
