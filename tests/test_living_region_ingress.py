from copy import deepcopy
from test_formal_graph_exact_review import _batch, TASK, BATCH, TOKEN
from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.workspace import NativeReviewFacade


def test_region_recognition_round_trip_does_not_copy_whole_page_into_unread_regions(tmp_path):
    store = AgentLinkStore(tmp_path/'inbox.json')
    service = AgentLinkService(store, TOKEN)
    facade = NativeReviewFacade(service, TOKEN, tmp_path/'artifacts')
    try:
        conn = service.reviewer_call(TOKEN, 'create_connection', {'task_id':TASK, 'agent_name':'fresh'})
        batch = deepcopy(_batch())
        batch['interfaces'][0]['recognition_text'] = 'Whole page text'
        batch['interfaces'][0]['regions'][0]['recognition_text'] = 'Search'
        batch['interfaces'][1]['recognition_text'] = 'Another whole page'
        service.agent_call(conn['token'], 'submit_batch', batch)
        a = facade.import_interface_content(TASK, BATCH, 'state-a')
        b = facade.import_interface_content(TASK, BATCH, 'state-b')
        assert a['content']['regions'][0]['recognition_text'] == 'Search'
        assert b['content']['regions'][0]['recognition_text'] == ''
    finally:
        facade.close(); store.close()
