from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_architecture.profiles import get_app_profile, list_app_profiles


def test_list_app_profiles_includes_seek_profile() -> None:
    profiles = list_app_profiles()

    seek = next(item for item in profiles if item.get("app_id") == "seek")
    assert seek["contract_version"] == "app_profile_v1"
    assert seek["execution_model"] == "agentic_loop_first"
    assert seek["final_submit_default"] == "forbidden"
    assert seek["workflow_asset_count"] >= 1


def test_get_app_profile_loads_seek_profile() -> None:
    profile, path = get_app_profile("seek")

    assert path.as_posix().endswith("artifacts/app_profiles/seek_app_profile_v1.json")
    assert profile.app_id == "seek"
    assert "read_full_job_detail" in profile.operation_skills
    assert "bound_window_match_v1" in profile.gate_contracts
    assert "final_submit_guard_v1" in profile.gate_contracts
    assert "latest_detail_snapshot_v1" in profile.gate_contracts


def test_runtime_app_profiles_routes() -> None:
    client = TestClient(app)

    list_response = client.get("/runtime/app_profiles")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["success"] is True
    assert list_payload["data"]["contract_version"] == "runtime_app_profiles_v1"
    assert any(item["app_id"] == "seek" for item in list_payload["data"]["profiles"])

    seek_response = client.get("/runtime/app_profiles/seek")
    assert seek_response.status_code == 200
    seek_payload = seek_response.json()
    assert seek_payload["success"] is True
    assert seek_payload["data"]["contract_version"] == "runtime_app_profile_v1"
    assert seek_payload["data"]["profile"]["policy"]["final_submit_default"] == "forbidden"
    assert "ocr_contextual_normalization_v1" in seek_payload["data"]["profile"]["gate_contracts"]


def test_runtime_app_profile_missing_is_structured_error() -> None:
    client = TestClient(app)

    response = client.get("/runtime/app_profiles/not_real")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "app_profile_not_found"
