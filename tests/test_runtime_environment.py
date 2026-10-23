"""Route-scoped interpreter admission; no windows, model calls or input."""
from types import SimpleNamespace

import pytest

from app.runtime_environment import inspect_environment


def metadata(*, source="local", python=(3, 12, 10), profile="windows_runtime"):
    return inspect_environment(profile=profile, recognition_source=source,
        python_version=python, platform="win32", find_spec=lambda _: object(),
        version=lambda _: "fixture")


@pytest.mark.parametrize("source", ["agent_current", "agent_delegate", "external_api"])
@pytest.mark.parametrize("python,supported", [((3, 11, 9), True), ((3, 12, 10), True),
                                           ((3, 10, 20), False), ((3, 13, 6), False)])
def test_agent_execution_admits_only_qualified_python_minors(source, python, supported):
    report = metadata(source=source, python=python)
    assert report["python_supported"] is supported
    assert report["status"] == ("metadata_present_unverified" if supported else "blocked")
    assert report["required_python"] == ">=3.11,<3.13"
    assert report["runtime_verified"] is False and report["imports_exercised"] is False


def test_default_local_and_ui_profiles_keep_python311_boundary():
    assert metadata()["status"] == "blocked"
    assert metadata(python=(3, 11, 9))["status"] == "metadata_present_unverified"
    for profile in ("all", "desktop_review", "agent_bridge"):
        report = metadata(source="external_api", profile=profile)
        assert report["status"] == "blocked"
        assert report["required_python"] == ">=3.11,<3.12"


@pytest.mark.parametrize("source", [None, "api", "external_api ", "model_supplied", False])
def test_unknown_source_cannot_expand_python_admission(source):
    with pytest.raises(ValueError, match="recognition source"):
        metadata(source=source)


@pytest.mark.parametrize("source,accepted", [("local", False), ("external_api", True),
                                           ("agent_current", True), ("agent_delegate", True)])
def test_production_coordinator_uses_fixed_startup_source(tmp_path, monkeypatch, source, accepted):
    from app.desktop_review import single_step_coordinator as coordinator_module
    calls = []

    def inspect(**kwargs):
        calls.append(kwargs)
        return metadata(source=kwargs["recognition_source"])

    monkeypatch.setattr(coordinator_module, "inspect_environment", inspect)
    coordinator = coordinator_module.NativeSingleStepCoordinator(tmp_path,
        SimpleNamespace(list_reviewed_assets=lambda: []), SimpleNamespace(status=lambda: {}),
        recognition_source=source)
    try:
        if accepted:
            coordinator._check_runtime_environment()
        else:
            with pytest.raises(coordinator_module.NativeSingleStepCoordinatorError) as failure:
                coordinator._check_runtime_environment()
            assert failure.value.code == "runtime_dependencies_missing"
        assert calls == [{"profile": "windows_runtime", "recognition_source": source}]
        assert coordinator._owner.thread_id is None
    finally:
        coordinator._owner.close()


@pytest.mark.parametrize("source", [None, "api", "external_api ", "model_supplied", False])
def test_coordinator_rejects_unknown_source_before_creating_owners(tmp_path, source):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    with pytest.raises(ValueError, match="recognition source"):
        NativeSingleStepCoordinator(tmp_path, object(), object(), recognition_source=source)
