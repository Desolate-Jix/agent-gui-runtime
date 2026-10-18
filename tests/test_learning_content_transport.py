from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.agent_link.contracts import AgentLinkError


TOKEN = "reviewer-secret-value-123"


class Content:
    def inspect(self, **kwargs):
        assert kwargs["connection_id"]
        return {
            "contract_version": "agent_learning_content_v1",
            "inspection_id": "inspection-1",
            "regions": [{"region_id": "region-1", "complete": True}],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_executed": False,
        }

    def read(self, **kwargs):
        return {
            "contract_version": "agent_learning_content_v1",
            "inspection_id": kwargs["inspection_id"],
            "region_id": kwargs["region_id"],
            "text": "complete content",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_executed": False,
        }


def _service(tmp_path):
    service = AgentLinkService(AgentLinkStore(tmp_path / "inbox.json"), TOKEN)
    connection = service.reviewer_call(TOKEN, "create_connection", {"task_id": "task-1", "agent_name": "agent"})
    service._learning_observation_provider = SimpleNamespace(content=Content())
    return service, connection["token"]


def test_content_transport_calls_scoped_provider(tmp_path):
    service, token = _service(tmp_path)
    inspected = service.agent_call(token, "inspect_learning_content", {"segment_id": "segment-1", "batch_id": "batch-1"})
    assert inspected["inspection_id"] == "inspection-1"
    read = service.agent_call(token, "read_learning_content", {
        "segment_id": "segment-1", "inspection_id": "inspection-1", "region_id": "region-1",
        "idempotency_key": "read-1",
    })
    assert read["text"] == "complete content"


def test_content_transport_rejects_extra_or_invalid_arguments(tmp_path):
    service, token = _service(tmp_path)
    with pytest.raises(AgentLinkError) as error:
        service.agent_call(token, "inspect_learning_content", {"segment_id": "s", "batch_id": "b", "scroll": True})
    assert error.value.code == "invalid_arguments"
    with pytest.raises(AgentLinkError) as error:
        service.agent_call(token, "read_learning_content", {
            "segment_id": "s", "inspection_id": "i", "region_id": "r", "idempotency_key": "k", "max_chars": 0,
        })
    assert error.value.code == "content_invalid_arguments"


def test_content_transport_rejects_provider_authorization_flags(tmp_path):
    service, token = _service(tmp_path)
    service._learning_observation_provider.content = SimpleNamespace(
        inspect=lambda **_: {
            "contract_version": "agent_learning_content_v1", "artifact_is_authorization": True,
            "execute_binding_enabled": False, "action_executed": False,
        }
    )
    with pytest.raises(AgentLinkError) as error:
        service.agent_call(token, "inspect_learning_content", {"segment_id": "s", "batch_id": "b"})
    assert error.value.code == "learning_source_unavailable"
