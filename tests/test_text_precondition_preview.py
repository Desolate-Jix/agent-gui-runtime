"""拥有者冻结字段预期；公开预览只绑定引用，不含旧值或预期原文。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.live_controller import LiveControllerDecision
from tests.test_text_local_publication import local_fixed


def test_publication_binds_original_field_expectation_without_serializing_raw(local_fixed):
    local = local_fixed
    claim = local.service.request_grounded_confirmation(local.request)
    assert not isinstance(claim, LiveControllerDecision), claim
    preview = claim.grounded_confirmation.preview.to_dict()
    ref = preview['text_field_expectation_ref']
    assert ref['before']['identity']['target_field_id'] == 'job_card'
    assert ref['before']['capture_id'] == preview['current_observation']['current_capture']['capture_id']
    assert ref['expected_value_sha256'] == preview['text_execution_ref']['text_sha256']
    assert '原字段内容' not in json.dumps(preview, ensure_ascii=False)
    for field, value in [('window_handle', 99), ('target_field_id', 'other')]:
        changed = deepcopy(preview)
        changed['text_field_expectation_ref']['before']['identity'][field] = value
        changed['content_sha256'] = sha256(json.dumps({k:v for k,v in changed.items() if k != 'content_sha256'},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
        with pytest.raises(ValueError, match='field'):
            GroundedActionPreview.from_dict(changed)
