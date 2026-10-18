from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.agent.live_runtime_composition import (
    ExistingWindowsCurrentEvidenceAdapter,
    ExistingWindowsCurrentEvidenceVisibilityChecker,
)
from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1
from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2
from app.agent.reviewed_workflow_asset import content_sha256
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.learn.application_identity import normalize_application_identity
from app.learn.interface_workflow_review import (
    INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT,
    build_interface_node_review_revision,
    save_interface_workflow_review_candidate,
)
from tests.test_agent_observation_adapter_v1 import _server_asset
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_live_runtime_composition_w3b import (
    _RecognitionRunner,
    _ScreenshotService,
    _UIAProvider,
    _entry_payloads,
)


def test_native_identity_retains_absolute_executable_path_and_canonical_key() -> None:
    from app.agent.native_identity import asset_application_identity_key

    identity = normalize_application_identity(
        {
            "kind": "native",
            "executable": r"D:\Lonlife\lonlife_acc.exe",
            "product": "Lonlife",
        }
    )

    assert identity["identity_key"] == "native:lonlife_acc.exe:lonlife"
    assert identity["executable_identity"] == "lonlife_acc.exe"
    assert identity["executable_path"] == r"d:\lonlife\lonlife_acc.exe"
    assert asset_application_identity_key(
        {
            "kind": "native",
            "executable": r"D:\Lonlife\lonlife_acc.exe",
            "product_identity": "Lonlife",
        }
    ) == "native:lonlife_acc.exe:lonlife"


def test_native_runtime_identity_reader_rejects_product_only_review_identity() -> None:
    from app.agent.native_identity import WindowsNativeIdentityReader

    reader = WindowsNativeIdentityReader(window_manager=object(), process_factory=lambda _pid: None)

    with pytest.raises(ValueError, match="absolute executable path"):
        reader.require_reviewed_executable_path(
            {"kind": "native", "product_identity": "lonlife"}
        )


def test_native_v2_current_observation_requires_reviewed_absolute_process_identity() -> None:
    asset = _native_asset()
    observation = _native_observation(asset)

    resolved = resolve_current_state(asset, observation)

    assert resolved["status"] == "resolved"
    assert resolved["state_id"] == "homepage"

    missing_identity = deepcopy(observation)
    missing_identity.pop("native_identity")
    missing_identity["contract_version"] = "reviewed_workflow_current_observation_v1"
    assert resolve_current_state(asset, missing_identity)["status"] == "blocked"


def test_native_capture_uses_exact_identity_before_and_after_recognition(tmp_path) -> None:
    asset = _native_asset()
    manager = _StableWindowManager()
    reader = _NativeIdentityReader()
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key="native:lonlife_acc.exe:lonlife",
        screenshot_service=_ScreenshotService(tmp_path),
        window_manager=manager,
        native_identity_reader=reader,
        recognition_runner=_RecognitionRunner(_entry_payloads(asset)),
        uia_provider=_UIAProvider(),
    )

    current = adapter.capture_current(
        session_id="native-session",
        asset=asset,
        target_window_handle=4242,
    )

    assert current["contract_version"] == "reviewed_workflow_current_observation_v2"
    assert current["native_identity"]["executable_path"] == r"d:\lonlife\lonlife_acc.exe"
    assert reader.calls == [4242, 4242, 4242]
    assert resolve_current_state(asset, current)["status"] == "resolved"


@pytest.mark.parametrize(
    ("reader_kwargs", "error"),
    [
        ({"executable_path": r"d:\other\lonlife_acc.exe"}, "unavailable or mismatched"),
        ({"process_id": 9002}, "unavailable or mismatched"),
        ({"replace_after": 1}, "drift"),
    ],
)
def test_native_capture_rejects_wrong_path_pid_or_creation_time(
    tmp_path,
    reader_kwargs: dict[str, object],
    error: str,
) -> None:
    asset = _native_asset()
    reader = _NativeIdentityReader(**reader_kwargs)
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key="native:lonlife_acc.exe:lonlife",
        screenshot_service=_ScreenshotService(tmp_path),
        window_manager=_StableWindowManager(),
        native_identity_reader=reader,
        recognition_runner=_RecognitionRunner(_entry_payloads(asset)),
        uia_provider=_UIAProvider(),
    )

    with pytest.raises(ValueError, match=error):
        adapter.capture_current(
            session_id="native-session",
            asset=asset,
            target_window_handle=4242,
        )


def test_compiled_native_asset_capture_resolve_and_project(tmp_path) -> None:
    _, source = _server_asset(tmp_path)
    review = json.loads(source.read_text(encoding="utf-8"))
    review["workflow"]["application_identity"] = {
        "kind": "native",
        "executable": r"D:\Lonlife\lonlife_acc.exe",
        "product": "Lonlife",
    }
    for node in review["nodes"]:
        node["human_review_confirmation"] = {
            "contract_version": INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT,
            "revision": build_interface_node_review_revision(
                review,
                node_id=node["node_id"],
            ),
        }
    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    source = type(source)(saved["path"])
    compiled = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=sha256(source.read_bytes()).hexdigest(),
    )
    assert compiled["status"] == "compiled", compiled
    asset = compiled["asset"]
    assert asset["application"]["executable_path"] == r"d:\lonlife\lonlife_acc.exe"

    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key="native:lonlife_acc.exe:lonlife",
        screenshot_service=_ScreenshotService(tmp_path),
        window_manager=_StableWindowManager(),
        native_identity_reader=_NativeIdentityReader(),
        recognition_runner=_RecognitionRunner(_entry_payloads(asset)),
        uia_provider=_UIAProvider(),
    )
    current = adapter.capture_current(
        session_id="native-session",
        asset=asset,
        target_window_handle=4242,
    )
    resolution = resolve_current_state(asset, current)

    projected = adapt_reviewed_context_to_agent_observation_v1(
        observation_id="native-observation",
        session_id="native-session",
        workflow_id=asset["source_review_lineage"]["source_workflow_id"],
        reviewed_asset=asset,
        current_observation=current,
        state_resolution=resolution,
        project_root=tmp_path,
        application_identity_key="native:lonlife_acc.exe:lonlife",
    )

    assert resolution["status"] == "resolved"
    assert projected.state.status == "matched"


def test_native_pre_dispatch_blocks_replaced_process_identity(tmp_path) -> None:
    asset = _native_asset()
    manager = _StableWindowManager()
    reader = _NativeIdentityReader(replace_after=3)
    screenshot = _ScreenshotService(tmp_path)
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key="native:lonlife_acc.exe:lonlife",
        screenshot_service=screenshot,
        window_manager=manager,
        native_identity_reader=reader,
        recognition_runner=_RecognitionRunner(_entry_payloads(asset)),
        uia_provider=_UIAProvider(),
    )
    current = adapter.capture_current(
        session_id="native-session",
        asset=asset,
        target_window_handle=4242,
    )
    checker = ExistingWindowsCurrentEvidenceVisibilityChecker(
        evidence_adapter=adapter,
        delegate=_AllowedVisibility(),
    )

    result = checker.check(
        session_id="native-session",
        capture_lineage={
            "capture_id": current["capture_id"],
            "screenshot_sha256": current["screenshot_sha256"],
            "viewport_size": current["viewport_size"],
        },
        target_window_handle=4242,
        click_point=(50.0, 100.0),
        target_bbox=(40.0, 90.0, 30.0, 30.0),
    )

    assert result["freshness"] == {"status": "blocked", "reason": "native_identity_changed"}
    assert len(screenshot.calls) == 1


@pytest.mark.parametrize("handle", [0, -1])
def test_native_identity_rejects_nonpositive_window_handle(handle):
    from app.agent.native_identity import validate_native_identity_fact
    fact = _NativeIdentityReader().read_identity(handle)
    assert validate_native_identity_fact(fact, target_window_handle=handle) is None


def test_native_identity_read_failure_keeps_actionable_reason():
    from app.agent.native_identity import WindowsNativeIdentityReader

    def denied(_pid):
        raise PermissionError("test process query denied")

    reader = WindowsNativeIdentityReader(window_manager=_StableWindowManager(), process_factory=denied)
    result = reader.read_identity(4242)
    assert result["status"] == "unavailable"
    assert result["reason"] == "process_identity_read_failed"
    assert result["error_type"] == "PermissionError"


def test_native_session_rejects_process_replacement_between_captures(tmp_path):
    asset = _native_asset()
    screenshots = _ScreenshotService(tmp_path)
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path, application_identity_key="native:lonlife_acc.exe:lonlife",
        screenshot_service=screenshots, window_manager=_StableWindowManager(),
        native_identity_reader=_NativeIdentityReader(replace_after=3),
        recognition_runner=_RecognitionRunner(_entry_payloads(asset)), uia_provider=_UIAProvider(),
    )
    adapter.capture_current(session_id="same-session", asset=asset, target_window_handle=4242)
    with pytest.raises(ValueError, match="native.*session.*identity"):
        adapter.capture_current(session_id="same-session", asset=asset, target_window_handle=4242)
    assert len(screenshots.calls) == 1


def test_web_v1_capture_reference_remains_byte_compatible():
    from app.agent.agent_observation_adapter import _capture_bound_refs
    current = {"capture_id": "capture-web", "screenshot_sha256": "a" * 64,
               "viewport_size": {"width": 320, "height": 200}}
    viewport_json = json.dumps(current["viewport_size"], sort_keys=True, separators=(",", ":"))
    old_binding = ":".join(("capture", current["capture_id"], current["screenshot_sha256"], viewport_json))
    expected = "content-sha256:" + "b" * 64 + ":" + sha256(old_binding.encode("utf-8")).hexdigest()
    _, capture_ref, _ = _capture_bound_refs("b" * 64, current, {})
    assert capture_ref == expected


class _StableWindowManager:
    def get_bound_window(self):
        return SimpleNamespace(
            handle=4242,
            process_id=9001,
            rect=SimpleNamespace(left=10, top=20, right=330, bottom=220),
        )


class _NativeIdentityReader:
    def __init__(
        self,
        *,
        replace_after: int | None = None,
        process_id: int = 9001,
        executable_path: str = r"d:\lonlife\lonlife_acc.exe",
    ) -> None:
        self.calls: list[int] = []
        self.replace_after = replace_after
        self.process_id = process_id
        self.executable_path = executable_path

    def read_identity(self, target_window_handle: int) -> dict:
        self.calls.append(target_window_handle)
        replaced = self.replace_after is not None and len(self.calls) > self.replace_after
        return {
            "contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity",
            "status": "observed",
            "target_window_handle": target_window_handle,
            "process_id": self.process_id,
            "process_create_time": 2000.5 if replaced else 1000.5,
            "executable_path": self.executable_path,
        }


class _AllowedVisibility:
    def check(self, **_kwargs: object) -> dict:
        return {"bound_window_handle": 4242, "point_visibility": {"allowed": True}}


def _native_asset() -> dict:
    asset = _asset()
    asset["application"] = {
        "identity_status": "resolved",
        "kind": "native",
        "allow_external_sites": False,
        "executable": "lonlife_acc.exe",
        "product_identity": "lonlife",
        "executable_path": r"d:\lonlife\lonlife_acc.exe",
    }
    return asset


def _native_observation(asset: dict) -> dict:
    screenshot_sha = sha256(b"native-current-capture").hexdigest()
    return {
        "contract_version": "reviewed_workflow_current_observation_v2",
        "asset_id": asset["asset_id"],
        "expected_asset_content_sha256": content_sha256(asset),
        "capture_id": "runtime-capture.native",
        "screenshot_sha256": screenshot_sha,
        "viewport_size": {"width": 320, "height": 200},
        "origin": "",
        "native_identity": {
            "contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity",
            "status": "observed",
            "target_window_handle": 4242,
            "process_id": 9001,
            "process_create_time": 1000.5,
            "executable_path": r"d:\lonlife\lonlife_acc.exe",
        },
        "observed_anchor_evidence": [
            {
                "anchor_id": "anchor_homepage",
                "matched": True,
                "confidence": 0.99,
                "evidence_ref": "current-recognition:native:anchor_homepage",
            }
        ],
    }
