"""公共观察发现同帧容器：不可变来源、轴能力及最小隐私投影。"""

from copy import deepcopy
import asyncio
import json

import pytest

from app.desktop_review.scroll_container_discovery import discover_scroll_containers
from tests.test_content_uia_stability import _tree, _packet
from tests.test_formal_learning_observation import _rig, _request
from tests.test_formal_fresh_learning_observation import _UIAProvider, _owner


def _scroll(ident="uia_338_group", **changes):
    return {"control_id": ident, "control_type": "Group", "name": "Details",
            "bbox": {"x": 10, "y": 10, "w": 60, "h": 70},
            "enabled": True, "visible": True, "patterns": ["Scroll"],
            "scroll_axes": {"current_vertical": True, "current_horizontal": False},
            "value": "PRIVATE_VALUE", "native_process": "C:/private/app.exe", **changes}


def _full_tree(*controls):
    tree = _tree()
    tree["controls"] = list(controls)
    tree["control_count"] = len(controls)
    return tree


def _discover(*controls):
    tree = _full_tree(*controls)
    return discover_scroll_containers(_packet(tree), lambda _: tree)


def test_whitelist_multiple_containers_no_read_region_conversion_or_values():
    result = _discover(_scroll(), _scroll("uia_339_list", control_type="List"))
    assert result["status"] == "available"
    assert [item["control_id"] for item in result["containers"]] == ["uia_338_group", "uia_339_list"]
    assert all(set(item) == {"control_id", "role", "name", "bbox", "scroll_axes"} for item in result["containers"])
    assert result["containers"][0]["scroll_axes"] == ["vertical"]
    assert "PRIVATE_VALUE" not in json.dumps(result) and "C:/" not in json.dumps(result)
    assert result["action_executed"] is False and result["artifact_is_authorization"] is False


@pytest.mark.parametrize("axes", [None, {}, {"current_vertical": None, "current_horizontal": False},
    {"current_vertical": 1, "current_horizontal": False}, {"current_vertical": "true", "current_horizontal": False}])
def test_unknown_or_self_asserted_axis_not_discovered(axes):
    result = _discover(_scroll(scroll_axes=axes))
    assert result["status"] == "unavailable" and result["reason"] == "scroll_axes_unavailable"
    assert result["containers"] == []


@pytest.mark.parametrize("changes", [{"control_type": "Button"}, {"enabled": False}, {"visible": False},
    {"patterns": ["Invoke"]}, {"bbox": {"x": -1, "y": 1, "w": 20, "h": 30}},
    {"scroll_axes": {"current_vertical": False, "current_horizontal": False}}])
def test_non_container_disabled_or_non_scroll_not_projected(changes):
    assert _discover(_scroll(**changes))["containers"] == []


@pytest.mark.parametrize("name", ["C:/private/profile", r"C:\private\profile", "token=PRIVATE", "secret: PRIVATE"])
def test_private_name_is_redacted(name):
    assert _discover(_scroll(name=name))["containers"][0]["name"] == ""


def test_snapshot_hash_mismatch_and_duplicate_ids_are_unavailable():
    tree = _full_tree(_scroll()); packet = _packet(tree)
    changed = deepcopy(tree); changed["controls"][0]["scroll_axes"]["current_horizontal"] = True
    assert discover_scroll_containers(packet, lambda _: changed)["reason"] == "source_context_binding_invalid"
    assert _discover(_scroll(), _scroll())["reason"] == "source_context_invalid"


def test_read_region_identifier_metadata_is_not_converted_into_control_id():
    control = _scroll()
    control.update(region_id="uia_" + "a" * 24, reference={"control_id": "untrusted-reader-id"})
    result = _discover(control)
    assert result["containers"][0]["control_id"] == "uia_338_group"
    assert "untrusted-reader-id" not in json.dumps(result)
    assert "uia_" + "a" * 24 not in json.dumps(result)


def _install_tree(monkeypatch, state):
    original = _UIAProvider.snapshot_window
    def snapshot(self, bound):
        tree = original(self, bound)
        tree.update(scan_complete=True, truncated=False, controls=deepcopy(state["controls"]),
                    control_count=len(state["controls"]))
        return tree
    monkeypatch.setattr(_UIAProvider, "snapshot_window", snapshot)


def test_public_api_new_frame_and_retry_use_only_original_sealed_tree(tmp_path, monkeypatch):
    state = {"controls": [_scroll(), _scroll("uia_339_list", control_type="List")]}
    _install_tree(monkeypatch, state)
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        call = lambda args: host._service.agent_call(connection["token"], "observe_learning_screen", args)
        first = call(_request(segment))
        discovery = first["scroll_containers"]
        assert discovery["status"] == "available" and len(discovery["containers"]) == 2
        assert discovery["capture_id"] == first["observation"]["capture"]["capture_id"]
        assert discovery["uia_snapshot_sha256"] == first["observation"]["uia"]["snapshot_sha256"]
        state["controls"] = [_scroll("uia_410_group", name="Next frame")]
        assert call(_request(segment)) == first and len(captures) == 1
        second = call({**_request(segment), "idempotency_key": "next-frame"})
        assert second["scroll_containers"]["containers"][0]["control_id"] == "uia_410_group"
        assert second["scroll_containers"]["capture_id"] != discovery["capture_id"]
        replay = call(_request(segment))
        assert replay["scroll_containers"] == discovery and replay["observation"] == first["observation"]
        assert len(captures) == 2


def test_public_api_missing_or_tampered_sidecar_never_recaptures(tmp_path, monkeypatch):
    _install_tree(monkeypatch, {"controls": [_scroll()]})
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        call = lambda: host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        first = call(); content = host._service._learning_observation_provider.content
        path = next((content.root / "source-contexts").glob("*.json"))
        record = json.loads(path.read_text(encoding="utf-8"))
        record["uia"]["controls"][0]["name"] = "Tampered"
        path.write_text(json.dumps(record), encoding="utf-8")
        assert call()["scroll_containers"]["status"] == "unavailable"
        content.root = tmp_path / "empty-source-context"
        missing = call()
        assert missing["scroll_containers"]["reason"] == "source_context_unavailable"
        assert missing["observation"] == first["observation"] and len(captures) == 1


def test_targeted_public_observer_without_sidecar_is_explicitly_unavailable(tmp_path, monkeypatch):
    _install_tree(monkeypatch, {"controls": [_scroll()]})
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        provider = host._service._learning_observation_provider
        owner = _owner(provider.source_owner.archive.project_root)
        packet = owner.observe(target_window_handle=4242, target_process_id=9001, goal="Read details")
        provider.bind_managed_observer(lambda **_: packet)
        result = host._service.agent_call(connection["token"], "observe_learning_screen",
                    {**_request(segment), "goal": "Read details"})
        assert result["scroll_containers"]["status"] == "unavailable" and captures == []


def test_real_public_mcp_returns_scroll_discovery_and_original_binding(tmp_path, monkeypatch):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from tests.test_formal_learning_runtime_controls import _mcp_server

    _install_tree(monkeypatch, {"controls": [_scroll()]})
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        host.start()
        async def read():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=30) as client:
                    await client.initialize()
                    response = await client.call_tool("observe_learning_screen", _request(segment))
                    assert not response.is_error
                    return response.structured_content
        result = asyncio.run(read())
        discovery = result["scroll_containers"]
        assert discovery["status"] == "available"
        assert discovery["containers"][0]["control_id"] == "uia_338_group"
        assert discovery["screenshot_sha256"] == result["screenshot"]["sha256"]
        assert discovery["uia_snapshot_sha256"] == result["observation"]["uia"]["snapshot_sha256"]
        assert len(captures) == 1
