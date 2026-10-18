from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.agent.fresh_learning_observation import (
    FreshLearningObservationError,
    FreshLearningObservationOwner,
    FreshLearningObservationPacket,
)


def _bound(*, handle=4242, pid=9001, left=10, top=20, width=160, height=100):
    return SimpleNamespace(
        handle=handle,
        process_id=pid,
        rect=SimpleNamespace(
            left=left, top=top, right=left + width, bottom=top + height,
        ),
    )


class _WindowManager:
    def __init__(self, *items) -> None:
        self.items = list(items)
        self.calls = 0

    def get_bound_window(self):
        self.calls += 1
        return self.items.pop(0) if self.items else None


class _ScreenshotService:
    def __init__(
        self,
        root: Path,
        *,
        width=160,
        height=100,
        missing=False,
        image_format="PNG",
    ) -> None:
        self.root = root
        self.width = width
        self.height = height
        self.missing = missing
        self.image_format = image_format
        self.calls: list[dict] = []
        self.path = root / "fresh-current.png"

    def capture_window(self, **kwargs):
        self.calls.append(dict(kwargs))
        if not self.missing:
            self.root.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (self.width, self.height), (7, 8, 9)).save(
                self.path, format=self.image_format,
            )
        return {
            "image_path": str(self.path),
            "image_width": self.width,
            "image_height": self.height,
            "roi": None,
            "window_size": {"width": self.width, "height": self.height},
        }


class _OriginReader:
    def __init__(self, *origins: str) -> None:
        self.origins = list(origins or ("https://fresh.example",) * 3)
        self.calls: list[int] = []

    def read_origin(self, handle: int):
        self.calls.append(handle)
        origin = self.origins.pop(0)
        return {
            "status": "observed",
            "origin": origin,
            "target_window_handle": handle,
            "bound_process_id": 9001,
        }


class _NativeReader:
    def __init__(self, *create_times: float, path=r"c:\fresh\app.exe") -> None:
        self.create_times = list(create_times or (100.5,) * 3)
        self.path = path
        self.calls: list[int] = []

    def read_identity(self, handle: int):
        self.calls.append(handle)
        return {
            "contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity",
            "status": "observed",
            "target_window_handle": handle,
            "process_id": 9001,
            "process_create_time": self.create_times.pop(0),
            "executable_path": self.path,
        }


class _UIAProvider:
    def __init__(self, *, handle=4242, pid=9001, left=0, top=0, width=160, height=100):
        self.identity = (handle, pid, left, top, width, height)
        self.calls: list[object] = []

    def snapshot_window(self, bound):
        self.calls.append(bound)
        handle, pid, left, top, width, height = self.identity
        return {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "window": {
                "handle": handle,
                "process_id": pid,
                "bbox": {"x": left, "y": top, "w": width, "h": height},
            },
            "control_count": 1,
            "controls": [{"control_id": "fresh-control", "name": "Fresh"}],
        }


class _RecognitionRunner:
    def __init__(
        self,
        *,
        returned_path: str | None = None,
        mutate_path: Path | None = None,
        malformed: str | None = None,
        nested_capture_reference: bool = False,
        capture_path_as_key: bool = False,
        include_internal_metadata: bool = False,
    ):
        self.returned_path = returned_path
        self.mutate_path = mutate_path
        self.malformed = malformed
        self.nested_capture_reference = nested_capture_reference
        self.capture_path_as_key = capture_path_as_key
        self.include_internal_metadata = include_internal_metadata
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.mutate_path is not None:
            Image.new("RGB", (160, 100), (90, 80, 70)).save(self.mutate_path)
        image_path = self.returned_path or kwargs["image_path"]
        result = {
            "contract_version": (
                "unrelated_error_v1"
                if self.malformed == "contract"
                else "recognition_plan_v1"
            ),
            "image_path": image_path,
            "goal": kwargs["goal"],
            "candidate_result": {
                "contract_version": "candidate_rank_v1",
                "goal": (
                    "different goal"
                    if self.malformed == "goal"
                    else kwargs["goal"]
                ),
                "top_k": 5,
                "candidates": [],
                "rejected": [],
                "recommended_candidate_id": None,
                "margin_to_second": None,
                "summary": {"source": "fresh_test"},
            },
            "narrow_search_result": {
                "contract_version": "narrow_search_v1",
                "goal": kwargs["goal"],
                "results": [],
                "recommended_candidate_id": None,
                "summary": {"status": "completed"},
            },
            "summary": {"text": "Fresh result", "caller_path": "C:/secret"},
            "artifact_is_authorization": True,
            "execute_binding_enabled": True,
            "action_executed": True,
        }
        if self.malformed == "missing_results":
            result.pop("candidate_result")
            result.pop("narrow_search_result")
        if self.nested_capture_reference:
            result["summary"]["reference"] = f"captured from {image_path}"
        if self.capture_path_as_key:
            result["summary"][image_path] = "capture"
        if self.include_internal_metadata:
            result.update({
                "operation_context": {
                    "capture_id": image_path,
                    "evidence_refs": [image_path],
                },
                "operation_trace_link": {
                    "result_status": "success",
                    "evidence_refs": [image_path],
                },
                "model_io": {"request_image": image_path},
                "model_io_failovers": [{"request_image": image_path}],
                "path_graph_recall": {"status": "disabled"},
            })
        return result


def _owner(
    root: Path,
    *,
    application=None,
    manager=None,
    screenshot=None,
    native=None,
    origin=None,
    uia=None,
    runner=None,
):
    return FreshLearningObservationOwner(
        project_root=root,
        application_identity=(
            application
            if application is not None
            else {"kind": "web", "canonical_origin": "https://fresh.example"}
        ),
        screenshot_service=screenshot or _ScreenshotService(root),
        window_manager=manager or _WindowManager(*[_bound() for _ in range(3)]),
        native_identity_reader=native or _NativeReader(*[100.5] * 100),
        origin_reader=origin or _OriginReader(),
        uia_provider=uia or _UIAProvider(),
        recognition_runner=runner or _RecognitionRunner(),
    )


def test_web_facts_only_packet_is_frozen_asset_independent_and_single_capture(tmp_path: Path) -> None:
    screenshot = _ScreenshotService(tmp_path)
    origin = _OriginReader()
    uia = _UIAProvider()
    runner = _RecognitionRunner()
    owner = _owner(
        tmp_path, screenshot=screenshot, origin=origin, uia=uia, runner=runner,
    )
    assert not (tmp_path / "runtime_state/reviewed-workflow-assets-v2").exists()

    packet = owner.observe(
        target_window_handle=4242, target_process_id=9001, goal=None,
    )

    assert isinstance(packet, FreshLearningObservationPacket)
    assert packet.png_bytes == screenshot.path.read_bytes()
    evidence = packet.evidence()
    assert evidence["contract_version"] == "fresh_learning_observation_v1"
    assert evidence["application"] == {
        "kind": "web", "canonical_origin": "https://fresh.example",
        "executable_path": r"c:\fresh\app.exe", "process_create_time": 100.5,
    }
    assert evidence["target"] == {
        "window_handle": 4242,
        "process_id": 9001,
        "rect": {"x": 10, "y": 20, "width": 160, "height": 100},
    }
    assert evidence["capture"]["viewport_size"] == {"width": 160, "height": 100}
    assert evidence["recognition"] == {
        "status": "not_requested", "goal": None,
        "result_sha256": None,
        "result_projection_contract": "fresh_read_only_recognition_projection_v1",
        "result_is_original": False,
        "result": None,
    }
    assert evidence["artifact_is_authorization"] is False
    assert evidence["execute_binding_enabled"] is False
    assert evidence["action_executed"] is False
    assert screenshot.calls == [{
        "save_image": True,
        "focus_window": False,
        "purpose": "learning-observation",
    }]
    assert len(origin.calls) == 3 and len(uia.calls) == 1 and runner.calls == []
    assert not (tmp_path / "runtime_state/reviewed-workflow-assets-v2").exists()
    with pytest.raises(FrozenInstanceError):
        packet.png_bytes = b"changed"
    evidence["target"]["process_id"] = 1
    assert packet.evidence()["target"]["process_id"] == 9001


def test_www_origin_observation_remains_exact_and_capturable(tmp_path):
    origin = 'https://www.google.com'
    owner = _owner(tmp_path, application={'kind': 'web', 'canonical_origin': origin},
        origin=_OriginReader(*[origin] * 3))
    packet = owner.observe(target_window_handle=4242, target_process_id=9001, goal=None)
    assert packet.evidence()['application']['canonical_origin'] == origin


@pytest.mark.parametrize('observed', [
    'https://google.com', 'https://maps.google.com', 'http://www.google.com',
    'https://www.google.com:8443', 'https://www.google.com.evil.example',
])
def test_www_origin_never_grants_apex_subdomain_scheme_or_port_equivalence(tmp_path, observed):
    screenshot = _ScreenshotService(tmp_path)
    owner = _owner(tmp_path, application={'kind': 'web', 'canonical_origin': 'https://www.google.com'},
        origin=_OriginReader(observed), screenshot=screenshot)
    with pytest.raises(FreshLearningObservationError, match='origin does not match'):
        owner.observe(target_window_handle=4242, target_process_id=9001, goal=None)
    assert screenshot.calls == []


def test_native_explicit_goal_uses_exact_saved_path_and_pinned_uia_without_authority(
    tmp_path: Path,
) -> None:
    screenshot = _ScreenshotService(tmp_path)
    native = _NativeReader()
    uia = _UIAProvider()
    runner = _RecognitionRunner()
    owner = _owner(
        tmp_path,
        application={"kind": "native", "executable_path": r"c:\fresh\app.exe"},
        screenshot=screenshot,
        native=native,
        uia=uia,
        runner=runner,
    )
    goal = "Find the exact fresh control"

    packet = owner.observe(
        target_window_handle=4242, target_process_id=9001, goal=goal,
    )

    evidence = packet.evidence()
    assert evidence["application"]["kind"] == "native"
    assert evidence["application"]["executable_path"] == r"c:\fresh\app.exe"
    assert evidence["application"]["process_create_time"] == 100.5
    assert evidence["recognition"]["status"] == "completed"
    assert evidence["recognition"]["goal"] == goal
    assert evidence["recognition"]["result_projection_contract"] == (
        "fresh_read_only_recognition_projection_v1"
    )
    assert evidence["recognition"]["result_is_original"] is False
    assert evidence["recognition"]["result"]["summary"] == {"text": "Fresh result"}
    assert "image_path" not in evidence["recognition"]["result"]
    assert "caller_path" not in str(evidence)
    assert evidence["artifact_is_authorization"] is False
    assert evidence["execute_binding_enabled"] is False
    assert evidence["action_executed"] is False
    assert len(native.calls) == 3
    assert len(runner.calls) == 1
    assert runner.calls[0]["image_path"] == str(screenshot.path.resolve())
    assert runner.calls[0]["goal"] == goal
    assert runner.calls[0]["uia_snapshot"]["control_count"] == 1


def test_valid_default_recognition_internal_metadata_is_excluded_not_rejected(
    tmp_path: Path,
) -> None:
    runner = _RecognitionRunner(include_internal_metadata=True)
    packet = _owner(tmp_path, runner=runner).observe(
        target_window_handle=4242,
        target_process_id=9001,
        goal="Inspect fresh screen",
    )

    recognition = packet.evidence()["recognition"]
    assert recognition["status"] == "completed"
    assert recognition["result_is_original"] is False
    assert set(recognition["result"]) == {
        "contract_version",
        "goal",
        "candidate_result",
        "narrow_search_result",
        "summary",
    }
    assert "operation_context" not in recognition["result"]
    assert runner.calls[0]["image_path"] not in packet.evidence_json.decode("utf-8")


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"target_window_handle": True, "target_process_id": 9001}, "window handle"),
        ({"target_window_handle": 4242, "target_process_id": 0}, "process ID"),
        ({"target_window_handle": 4242, "target_process_id": 9001, "goal": ""}, "goal"),
        ({"target_window_handle": 4242, "target_process_id": 9001, "goal": "x" * 513}, "goal"),
    ],
)
def test_invalid_target_or_goal_fails_before_capture(tmp_path: Path, kwargs: dict, error: str) -> None:
    screenshot = _ScreenshotService(tmp_path)
    owner = _owner(tmp_path, screenshot=screenshot)
    with pytest.raises(FreshLearningObservationError, match=error):
        owner.observe(**kwargs)
    assert screenshot.calls == []


@pytest.mark.parametrize("case", ["handle", "pid", "web_origin", "native_path"])
def test_initial_target_or_application_mismatch_fails_before_capture(
    tmp_path: Path,
    case: str,
) -> None:
    screenshot = _ScreenshotService(tmp_path)
    manager = _WindowManager(
        _bound(handle=999) if case == "handle" else
        _bound(pid=999) if case == "pid" else _bound()
    )
    application = {"kind": "web", "canonical_origin": "https://fresh.example"}
    origin = _OriginReader(
        "https://wrong.example" if case == "web_origin" else "https://fresh.example",
    )
    native = _NativeReader(path=r"c:\wrong\app.exe")
    if case == "native_path":
        application = {"kind": "native", "executable_path": r"c:\fresh\app.exe"}
    owner = _owner(
        tmp_path, application=application, manager=manager, screenshot=screenshot,
        origin=origin, native=native,
    )
    with pytest.raises(FreshLearningObservationError):
        owner.observe(target_window_handle=4242, target_process_id=9001)
    assert screenshot.calls == []


@pytest.mark.parametrize(
    "case", ["missing_png", "non_png", "wrong_dimensions", "uia"],
)
def test_capture_or_uia_failure_has_no_packet_or_fallback(tmp_path: Path, case: str) -> None:
    screenshot = _ScreenshotService(
        tmp_path,
        missing=case == "missing_png",
        image_format="JPEG" if case == "non_png" else "PNG",
        width=161 if case == "wrong_dimensions" else 160,
    )
    uia = _UIAProvider(pid=999 if case == "uia" else 9001)
    owner = _owner(tmp_path, screenshot=screenshot, uia=uia)
    with pytest.raises(FreshLearningObservationError):
        owner.observe(target_window_handle=4242, target_process_id=9001)
    assert len(screenshot.calls) == 1


@pytest.mark.parametrize("case", ["window", "origin", "native", "png", "recognition_path"])
def test_post_capture_or_recognition_drift_never_returns_packet(
    tmp_path: Path,
    case: str,
) -> None:
    screenshot = _ScreenshotService(tmp_path)
    application = {"kind": "web", "canonical_origin": "https://fresh.example"}
    manager = _WindowManager(
        _bound(), _bound(), _bound(pid=9002) if case == "window" else _bound(),
    )
    origin = _OriginReader(
        "https://fresh.example",
        "https://fresh.example",
        "https://wrong.example" if case == "origin" else "https://fresh.example",
    )
    native = _NativeReader(100.5, 100.5, 200.5 if case == "native" else 100.5)
    if case == "native":
        application = {"kind": "native", "executable_path": r"c:\fresh\app.exe"}
    runner = _RecognitionRunner(
        returned_path=str(tmp_path / "other.png") if case == "recognition_path" else None,
        mutate_path=screenshot.path if case == "png" else None,
    )
    owner = _owner(
        tmp_path, application=application, manager=manager, screenshot=screenshot,
        origin=origin, native=native, runner=runner,
    )
    with pytest.raises(FreshLearningObservationError):
        owner.observe(
            target_window_handle=4242,
            target_process_id=9001,
            goal="Inspect fresh screen",
        )
    assert len(screenshot.calls) == 1
    assert len(runner.calls) == 1


@pytest.mark.parametrize("malformed", ["contract", "missing_results", "goal"])
def test_malformed_or_wrong_goal_recognition_protocol_is_rejected(
    tmp_path: Path,
    malformed: str,
) -> None:
    runner = _RecognitionRunner(malformed=malformed)
    owner = _owner(tmp_path, runner=runner)

    with pytest.raises(FreshLearningObservationError):
        owner.observe(
            target_window_handle=4242,
            target_process_id=9001,
            goal="Inspect fresh screen",
        )


@pytest.mark.parametrize("path_location", ["value", "key"])
def test_valid_protocol_cannot_expose_capture_path_under_an_unrelated_key(
    tmp_path: Path,
    path_location: str,
) -> None:
    runner = _RecognitionRunner(
        nested_capture_reference=path_location == "value",
        capture_path_as_key=path_location == "key",
    )
    owner = _owner(tmp_path, runner=runner)

    with pytest.raises(FreshLearningObservationError, match="capture path"):
        owner.observe(
            target_window_handle=4242,
            target_process_id=9001,
            goal="Inspect fresh screen",
        )


@pytest.mark.parametrize("key,value", [
    ("path_graph_recall_used", "private/image.png"),
    ("path_graph_recall_used", 1),
    ("path_graph_recall_candidate_count", True),
    ("path_graph_recall_selected_count", -1),
    ("path_graph_recall_selected_count", {"path": "private/image.png"}),
])
def test_graph_recall_metric_names_cannot_carry_paths_or_invalid_types(tmp_path, key, value):
    from app.agent.fresh_learning_observation import _sanitize_result

    with pytest.raises(FreshLearningObservationError, match="graph recall metric"):
        _sanitize_result({key: value}, capture_path=tmp_path / "capture.png")


def test_graph_metrics_do_not_exempt_unknown_path_fields(tmp_path):
    from app.agent.fresh_learning_observation import _sanitize_result

    metrics = {"path_graph_recall_used": True, "path_graph_recall_candidate_count": 3,
               "path_graph_recall_selected_count": 1}
    value = {**metrics, "path_graph_recall_file_path": "private/image.png",
             "image_path": "private/image.png", "crop_path": "private/crop.png"}
    assert _sanitize_result(value, capture_path=tmp_path / "capture.png") == metrics


def test_strict_application_identity_and_module_boundary(tmp_path: Path) -> None:
    for value in (
        {},
        {"kind": "native", "executable_path": "relative.exe"},
        {"kind": "web", "canonical_origin": "file:///tmp"},
        {"kind": "web", "canonical_origin": "https://fresh.example/path"},
        {"kind": "web", "canonical_origin": "https://fresh.example", "asset_id": "fake"},
    ):
        with pytest.raises((TypeError, ValueError)):
            _owner(tmp_path, application=value)

    import inspect
    import app.agent.fresh_learning_observation as module

    source = inspect.getsource(module)
    assert "ReviewedWorkflow" not in source
    assert "Backend" not in source
    assert "dispatch" not in source
