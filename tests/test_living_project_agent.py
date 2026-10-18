from pathlib import Path

from fastapi.testclient import TestClient

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.http_app import create_agent_link_app
from tests.test_formal_graph_exact_review import BATCH, TASK, TOKEN, _batch


def test_project_memory_is_exposed_over_real_loopback_app(tmp_path: Path) -> None:
    store = AgentLinkStore(tmp_path / "fresh-inbox.json")
    service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": TASK, "agent_name": "fresh-project-agent"})
    service.agent_call(grant["token"], "submit_batch", _batch())
    from app.desktop_review.workspace import NativeReviewFacade
    facade = NativeReviewFacade(service, TOKEN, tmp_path / "fresh-artifacts")
    content = facade.import_interface_content(TASK, BATCH, "state-a")
    graph = facade.create_workflow_graph("Fresh project memory", TASK)
    facade.attach_interface_to_workflow(
        graph["logical_workflow_id"], content["interface_id"], content["version_id"],
        graph["revision"], graph["content_sha256"], "project-agent-attach",
    )
    service.bind_interface_content_gateway("fresh-graph-exact-token", facade)
    app = create_agent_link_app(service)
    token = grant["token"]
    with TestClient(app, client=("127.0.0.1", 43210)) as client:
        status = client.post("/agent/status", headers={"Authorization": f"Bearer {token}"}, json={})
        assert status.status_code == 200
        assert status.json()["workflow_project_memory"]["operations"] == [
            "search_workflow_projects", "get_workflow_project_memory"
        ]
        listed = client.post("/agent/search_workflow_projects", headers={"Authorization": f"Bearer {token}"}, json={})
        assert listed.status_code == 200
        assert listed.json()[0]["title"] == "Fresh project memory"
        workflow_id = listed.json()[0]["logical_workflow_id"]
        latest = client.post(
            "/agent/get_workflow_project_memory",
            headers={"Authorization": f"Bearer {token}"},
            json={"workflow_id": workflow_id},
        )
        assert latest.status_code == 200
        assert latest.json()["logical_workflow_id"] == workflow_id
    facade.close()
    store.close()
