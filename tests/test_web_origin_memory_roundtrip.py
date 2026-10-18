"""网站精确主机名经过独立保存、读取和重开后不能丢失。"""
from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.workspace import NativeReviewFacade
from test_formal_graph_exact_review import _runtime, TASK, BATCH, TOKEN


def test_www_and_existing_apex_memories_keep_distinct_exact_identity(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    saved = []
    try:
        for external, origin in [('state-a', 'https://www.google.com'), ('state-b', 'https://google.com')]:
            first = facade.import_interface_content(TASK, BATCH, external)
            updated = facade.save_interface_content(first['interface_id'], first['revision'], first['content_sha256'],
                {'application_binding': {'kind': 'web', 'display_name': 'Google', 'canonical_origin': origin}},
                'origin-save-' + external)
            saved.append(updated)
            assert updated['content']['application_binding']['canonical_origin'] == origin
            memory = facade.get_interface_memory(TASK, updated['interface_id'], updated['version_id'])
            assert memory['content'] == updated['content']
        assert saved[0]['content']['application_binding']['identity_key'] != saved[1]['content']['application_binding']['identity_key']
    finally:
        facade.close()
        store.close()
    store = AgentLinkStore(tmp_path / 'fresh-inbox.json')
    facade = NativeReviewFacade(AgentLinkService(store, TOKEN), TOKEN, tmp_path / 'fresh-artifacts')
    try:
        for snapshot in saved:
            assert facade.load_interface_content(snapshot['interface_id'], snapshot['version_id']) == snapshot
    finally:
        facade.close()
        store.close()
