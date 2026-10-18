"""网页链接类型必须贯通学习、修正、持久化和当前定位，不降级为其他类型。"""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agent_link.contracts import ObservedRegionInput, InterfaceRelearningRegionChange
from app.desktop_review.interface_content import SUPPORTED_REGION_KINDS
from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.workspace import NativeReviewFacade
from test_formal_graph_exact_review import BATCH, TASK, TOKEN, _runtime


@pytest.mark.parametrize('model', [ObservedRegionInput, InterfaceRelearningRegionChange])
def test_learning_and_relearning_expose_link_without_accepting_arbitrary_kinds(model):
    payload = ({'bbox': [4.0, 5.0, 20.0, 12.0], 'name': 'OpenStreetMap',
                'meaning': 'Open the public map', 'recognition_text': 'OpenStreetMap'}
               if model is ObservedRegionInput else {'region_id': 'region-map'})
    assert model.model_validate({**payload, 'kind': 'link'}).kind == 'link'
    with pytest.raises(ValidationError):
        model.model_validate({**payload, 'kind': 'unrecognized_action'})


def test_link_survives_save_memory_and_reopen_without_content_finalization(tmp_path):
    assert 'link' in SUPPORTED_REGION_KINDS
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, 'state-a')
        regions = deepcopy(first['content']['regions'])
        regions[0]['kind'] = 'link'
        regions[0]['recognition_text'] = 'OpenStreetMap'
        saved = facade.save_interface_content(first['interface_id'], first['revision'],
            first['content_sha256'], {'regions': regions}, 'save-link')
        assert facade.get_interface_memory(TASK, saved['interface_id'], saved['version_id'])['content']['regions'][0]['kind'] == 'link'
        assert facade.load_interface_content(first['interface_id'], first['version_id']) == first
    finally:
        facade.close()
        store.close()
    reopened_store = AgentLinkStore(tmp_path / 'fresh-inbox.json')
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, TOKEN), TOKEN, tmp_path / 'fresh-artifacts')
    try:
        assert reopened.load_interface_content(saved['interface_id']) == saved
        assert saved['content']['regions'][0]['kind'] == 'link'
    finally:
        reopened.close()
        reopened_store.close()
