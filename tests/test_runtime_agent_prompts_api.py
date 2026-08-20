from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_runtime_agent_prompts_routes_list_and_load() -> None:
    client = TestClient(app)

    list_response = client.get("/runtime/agent_prompts")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["success"] is True
    assert list_payload["data"]["contract_version"] == "runtime_agent_prompts_v1"
    assert any(item["prompt_id"] == "job_suitability_full_jd_v1" for item in list_payload["data"]["prompts"])

    prompt_response = client.get("/runtime/agent_prompts/job_suitability_full_jd_v1")
    assert prompt_response.status_code == 200
    prompt_payload = prompt_response.json()
    assert prompt_payload["success"] is True
    assert prompt_payload["data"]["contract_version"] == "runtime_agent_prompt_v1"
    assert prompt_payload["data"]["prompt"]["output_contract"] == "job_suitability_decision_v1"
    assert "full_job_detail_text" in prompt_payload["data"]["prompt"]["variables"]

    versions_response = client.get("/runtime/agent_prompts/job_suitability_full_jd_v1/versions")
    assert versions_response.status_code == 200
    versions_payload = versions_response.json()
    assert versions_payload["success"] is True
    assert versions_payload["data"]["contract_version"] == "runtime_agent_prompt_versions_v1"
    assert any(item["version"] == "2026-06-29.base" for item in versions_payload["data"]["versions"])

    base_response = client.get("/runtime/agent_prompts/job_suitability_full_jd_v1/versions/2026-06-29.base")
    assert base_response.status_code == 200
    base_payload = base_response.json()
    assert base_payload["success"] is True
    assert base_payload["data"]["contract_version"] == "runtime_agent_prompt_version_v1"
    assert base_payload["data"]["prompt"]["version"] == "2026-06-29.base"

    diff_response = client.get(
        "/runtime/agent_prompts/job_suitability_full_jd_v1/diff",
        params={"from_version": "2026-06-29.base", "to_version": "2026-06-29.base"},
    )
    assert diff_response.status_code == 200
    diff_payload = diff_response.json()
    assert diff_payload["success"] is True
    assert diff_payload["data"]["contract_version"] == "agent_prompt_diff_v1"
    assert diff_payload["data"]["changed"] is False


def test_runtime_agent_prompt_missing_is_structured_error() -> None:
    client = TestClient(app)

    response = client.get("/runtime/agent_prompts/not_real")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "agent_prompt_not_found"
