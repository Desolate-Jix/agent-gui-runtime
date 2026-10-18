from copy import deepcopy

import pytest

from app.desktop_review.connection_dialog import ConnectionManagerDialog


def _execution_view():
    return {
        "host": {
            "contract_version": "native_review_host_v2", "host_id": "host-execution-test",
            "phase": "ready", "base_url": "http://127.0.0.1:49123", "staging_only": False,
            "agent_link_staging_only": True, "reviewed_single_step_enabled": True,
            "automatic_execution_enabled": False,
        },
        "connections": [],
    }


def test_native_connection_consumer_accepts_strict_execution_host_status():
    assert ConnectionManagerDialog._valid_view(_execution_view()) is True


@pytest.mark.parametrize("field,value", [
    ("contract_version", "native_review_host_v1"),
    ("staging_only", True), ("staging_only", 0),
    ("agent_link_staging_only", False), ("agent_link_staging_only", 1),
    ("reviewed_single_step_enabled", False), ("automatic_execution_enabled", True),
    ("automatic_execution_enabled", 0), ("base_url", "http://example.com:49123"),
])
def test_execution_status_cannot_relax_learning_role_or_execution_boundary(field, value):
    view = _execution_view()
    view["host"][field] = value
    assert ConnectionManagerDialog._valid_view(view) is False


def test_execution_status_rejects_unknown_fields_and_missing_boundary_flags():
    valid = _execution_view()
    extra = deepcopy(valid)
    extra["host"]["execution_token"] = "must-not-be-published"
    assert ConnectionManagerDialog._valid_view(extra) is False
    for field in valid["host"]:
        missing = deepcopy(valid)
        del missing["host"][field]
        assert ConnectionManagerDialog._valid_view(missing) is False


def test_learning_only_host_retains_existing_strict_version():
    view = _execution_view()
    view["host"] = {key: value for key, value in view["host"].items() if key in {
        "contract_version", "host_id", "phase", "base_url", "staging_only",
    }}
    view["host"].update(contract_version="native_review_host_v1", staging_only=True)
    assert ConnectionManagerDialog._valid_view(view) is True
