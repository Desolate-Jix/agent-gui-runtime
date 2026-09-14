"""无 reviewed asset 的首次屏幕只读事实包。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from app.agent.live_runtime_composition import (
    _bound_identity,
    _require_unchanged_screenshot,
    _parse_recognition,
    _run_existing_read_only_recognition,
    _validated_native_identity,
    _validated_origin_fact,
    _validated_saved_capture,
    _validated_uia_snapshot,
)
from app.agent.native_identity import (
    WindowsNativeIdentityReader,
    normalize_windows_executable_path,
    validate_native_identity_fact,
)
from app.agent.windows_uia_origin_reader import WindowsUIAOriginReader
from app.learn.application_identity import normalize_application_identity
from app.vision.configuration import (
    VisionConfigurationSnapshot,
    load_formal_vision_configuration,
    resolve_vision_config_path,
)


CONTRACT_VERSION = "fresh_learning_observation_v1"
MAX_GOAL_LENGTH = 512
_FORBIDDEN_RESULT_KEYS = {
    "artifact_is_authorization",
    "execute_binding_enabled",
    "action_executed",
}
_PUBLIC_RECOGNITION_KEYS = (
    "contract_version",
    "goal",
    "candidate_result",
    "narrow_search_result",
    "summary",
)
_PUBLIC_GRAPH_METRIC_TYPES = {
    "path_graph_recall_used": bool,
    "path_graph_recall_candidate_count": int,
    "path_graph_recall_selected_count": int,
}


class FreshLearningObservationError(ValueError):
    """首次观察的目标、身份、截图或只读识别不满足绑定。"""


@dataclass(frozen=True, slots=True)
class FreshLearningObservationPacket:
    png_bytes: bytes
    evidence_json: bytes

    def evidence(self) -> dict[str, Any]:
        """每次解码为新的映射，不暴露内部可变引用。"""

        try:
            value = json.loads(self.evidence_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:  # pragma: no cover
            raise FreshLearningObservationError("fresh evidence bytes are corrupt") from error
        if not isinstance(value, dict):  # pragma: no cover
            raise FreshLearningObservationError("fresh evidence bytes are invalid")
        return value


@dataclass(frozen=True, slots=True)
class FreshLearningActionObservation:
    packet: FreshLearningObservationPacket
    recognition_json: bytes = field(repr=False)
    uia_snapshot_json: bytes = field(repr=False)
    artifact_is_authorization: bool = field(default=False, init=False)

    def recognition_result(self) -> dict[str, Any]:
        return json.loads(self.recognition_json.decode("utf-8"))

    def uia_snapshot(self) -> dict[str, Any]:
        return json.loads(self.uia_snapshot_json.decode("utf-8"))


@dataclass(frozen=True, slots=True)
class FreshLearningPassiveObservation:
    packet: FreshLearningObservationPacket
    uia_snapshot_json: bytes = field(repr=False)
    artifact_is_authorization: bool = field(default=False, init=False)

    def uia_snapshot(self) -> dict[str, Any]:
        return json.loads(self.uia_snapshot_json.decode('utf-8'))


class FreshLearningObservationOwner:
    """组合现有 passive capture、身份、UIA 与无 seed 只读识别。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        application_identity: Mapping[str, Any],
        screenshot_service: Any | None = None,
        window_manager: Any | None = None,
        native_identity_reader: Any | None = None,
        origin_reader: Any | None = None,
        uia_provider: Any | None = None,
        recognition_runner: Callable[..., Mapping[str, Any]] | None = None,
        vision_configuration: VisionConfigurationSnapshot | None = None,
        text_field_reader: Any | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.application = _application_identity(application_identity)
        if vision_configuration is not None and not isinstance(
            vision_configuration, VisionConfigurationSnapshot,
        ):
            raise TypeError(
                "vision_configuration must be VisionConfigurationSnapshot or None"
            )
        if screenshot_service is None:
            from app.core.screenshot import screenshot_service as active_screenshot_service

            screenshot_service = active_screenshot_service
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        if uia_provider is None:
            from app.operation.screen_reading.uia_provider import (
                uia_provider as active_uia_provider,
            )

            uia_provider = active_uia_provider
        self._screenshot_service = screenshot_service
        self._window_manager = window_manager
        self._native_identity_reader = native_identity_reader or WindowsNativeIdentityReader(
            window_manager=window_manager,
        )
        self._origin_reader = origin_reader or WindowsUIAOriginReader(
            window_manager=window_manager,
        )
        self._uia_provider = uia_provider
        self._recognition_runner = recognition_runner
        self._vision_configuration = vision_configuration
        self._text_field_reader = text_field_reader

    def read_text_field(
        self, *, bundle: FreshLearningActionObservation, target_field_id: str,
        decision: Mapping[str, Any], require_keyboard_focus: bool = False,
        automatic_safety_interception: bool = True,
    ):
        from .fresh_text_field import read_fresh_text_field

        return read_fresh_text_field(self, bundle=bundle, target_field_id=target_field_id,
            decision=decision, require_keyboard_focus=require_keyboard_focus,
            automatic_safety_interception=automatic_safety_interception)

    def read_text_field_after(self, *, packet, expectation):
        from .fresh_text_field import read_fresh_text_field_after

        return read_fresh_text_field_after(self, packet=packet, expectation=expectation)

    def observe(
        self,
        *,
        target_window_handle: int,
        target_process_id: int,
        goal: str | None = None,
    ) -> FreshLearningObservationPacket:
        handle = _positive_int(target_window_handle, "target window handle")
        process_id = _positive_int(target_process_id, "target process ID")
        checked_goal = _goal(goal)
        try:
            return self._observe(
                target_window_handle=handle,
                target_process_id=process_id,
                goal=checked_goal,
            )
        except FreshLearningObservationError:
            raise
        except Exception as error:
            raise FreshLearningObservationError(
                f"fresh learning observation failed: {type(error).__name__}"
            ) from error

    def observe_with_uia(self, *, target_window_handle: int, target_process_id: int):
        """同次被动截图返回完整 UIA，不另采一棵树拼接来源。"""
        handle = _positive_int(target_window_handle, 'target window handle')
        process_id = _positive_int(target_process_id, 'target process ID')
        originals = {}
        try:
            packet = self._observe(target_window_handle=handle, target_process_id=process_id,
                                   goal=None, originals=originals)
        except FreshLearningObservationError:
            raise
        except Exception as error:
            raise FreshLearningObservationError(
                f'fresh passive observation failed: {type(error).__name__}') from error
        return FreshLearningPassiveObservation(packet=packet, uia_snapshot_json=originals['uia'])

    def observe_for_action(
        self,
        *,
        target_window_handle: int,
        target_process_id: int,
        goal: str,
        semantic_action: str | None = None,
        expected_visual: Mapping[str, Any] | None = None,
        text_visual_scope=None,
        control_target: dict | None = None,
        scroll_parameters: dict | None = None,
    ) -> FreshLearningActionObservation:
        handle = _positive_int(target_window_handle, "target window handle")
        process_id = _positive_int(target_process_id, "target process ID")
        checked_goal = _goal(goal)
        if checked_goal is None:
            raise FreshLearningObservationError("action observation requires goal")
        if semantic_action not in (None, "fill_field", "open_detail", "scroll_region"):
            raise FreshLearningObservationError("unsupported recognition action hint")
        if scroll_parameters is not None and semantic_action != "scroll_region":
            raise FreshLearningObservationError("scroll parameters require scroll semantics")
        if semantic_action == "scroll_region":
            from app.agent.scroll_parameters import ReviewedScrollParameters
            scroll_parameters = ReviewedScrollParameters.from_payload(scroll_parameters).to_payload()
        if expected_visual is not None and semantic_action != "fill_field":
            raise FreshLearningObservationError("visual stabilization is only available for text input")
        if text_visual_scope is not None and (semantic_action != "fill_field" or expected_visual is None):
            raise FreshLearningObservationError("text visual scope requires a bound fill preview")
        originals: dict[str, bytes] = {}
        try:
            from app.agent.fresh_capture_stability import TransientCapturePixelsChanged
            from app.operation.recognition.control_target import validate_control_target

            checked_target = validate_control_target(control_target) if control_target is not None else None

            for attempt in range(7 if expected_visual is not None else 1):
                try:
                    packet = self._observe(
                        target_window_handle=handle, target_process_id=process_id,
                        goal=checked_goal, originals=originals, semantic_action=semantic_action,
                        expected_visual=expected_visual,
                        text_visual_scope=text_visual_scope,
                        control_target=checked_target,
                        scroll_parameters=scroll_parameters,
                    )
                    break
                except TransientCapturePixelsChanged:
                    if attempt == 6:
                        raise
                    time.sleep(0.1)
        except FreshLearningObservationError:
            raise
        except Exception as error:
            raise FreshLearningObservationError(
                f"fresh action observation failed: {type(error).__name__}"
            ) from error
        return FreshLearningActionObservation(
            packet=packet, recognition_json=originals["recognition"],
            uia_snapshot_json=originals["uia"],
        )

    def _observe(
        self,
        *,
        target_window_handle: int,
        target_process_id: int,
        goal: str | None,
        originals: dict[str, bytes] | None = None,
        semantic_action: str | None = None,
        expected_visual: Mapping[str, Any] | None = None,
        text_visual_scope=None,
        control_target: dict | None = None,
        scroll_parameters: dict | None = None,
    ) -> FreshLearningObservationPacket:
        before_bound = self._window_manager.get_bound_window()
        before_identity = _bound_identity(
            before_bound, target_window_handle=target_window_handle,
        )
        before_rect = _bound_rect(before_bound)
        if before_identity[1] != target_process_id:
            raise FreshLearningObservationError(
                "bound window process ID does not match the requested target"
            )
        application_fact = self._read_application_fact(
            target_window_handle, target_process_id,
        )

        capture_started_ns = time.perf_counter_ns()
        capture = self._screenshot_service.capture_window(
            save_image=True,
            focus_window=False,
            purpose="learning-observation",
        )
        captured_at_ns = time.perf_counter_ns()
        after_bound = self._window_manager.get_bound_window()
        after_identity = _bound_identity(
            after_bound, target_window_handle=target_window_handle,
        )
        if after_identity != before_identity or _bound_rect(after_bound) != before_rect:
            raise FreshLearningObservationError(
                "bound window changed during passive learning capture"
            )
        if self._read_application_fact(
            target_window_handle, target_process_id,
        ) != application_fact:
            raise FreshLearningObservationError(
                "application identity changed during passive learning capture"
            )
        image_path, image_bytes, viewport = _validated_saved_capture(
            capture, expected_size=before_identity[2],
        )
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FreshLearningObservationError(
                "passive learning capture must be a PNG image"
            )
        screenshot_digest = sha256(image_bytes).hexdigest()
        capture_id = f"fresh-capture.{uuid4().hex}"

        uia_snapshot = _validated_uia_snapshot(
            self._uia_provider.snapshot_window(after_bound),
            expected_identity=before_identity,
        )
        _require_uia_rect(uia_snapshot, before_rect)
        uia_digest = sha256(_canonical_bytes(uia_snapshot)).hexdigest()
        if expected_visual is not None:
            from app.agent.fresh_capture_stability import require_exact_fresh_capture

            # 填写保护域通过后仍对当前原图运行识别；其他动作继续要求全图一致。
            require_exact_fresh_capture(original=expected_visual, png_bytes=image_bytes, current={
                "target": {"window_handle": target_window_handle, "process_id": target_process_id, "rect": before_rect},
                "application": _public_application(self.application, application_fact),
                "uia": {"provider": uia_snapshot.get("provider"), "provider_version": uia_snapshot.get("provider_version"),
                    "status": uia_snapshot.get("status"), "control_count": uia_snapshot.get("control_count"), "snapshot_sha256": uia_digest},
                "capture": {"capture_id": capture_id, "capture_started_ns": capture_started_ns,
                    "capture_clock_id": "windows-perf-counter-v1", "viewport_size": viewport, "screenshot_sha256": screenshot_digest},
            }, text_visual_scope=text_visual_scope,
                current_uia_snapshot=uia_snapshot if text_visual_scope is not None else None)
        from .native_field_hit_context import make_field_hit_collector, pinned_field_hit_collector
        from .native_control_hit_context import make_control_hit_collector, pinned_control_hit_collector
        collector = (make_field_hit_collector(self, image_path=image_path, image_bytes=image_bytes,
            uia_snapshot=uia_snapshot, capture_id=capture_id, capture_started_ns=capture_started_ns,
            captured_at_ns=captured_at_ns, application_fact=application_fact,
            target_window_handle=target_window_handle, target_process_id=target_process_id,
            window_rect=before_rect) if semantic_action == 'fill_field' else None)
        icon_collector = (make_control_hit_collector(self, image_path=image_path, image_bytes=image_bytes,
            uia_snapshot=uia_snapshot, capture_id=capture_id, capture_started_ns=capture_started_ns,
            captured_at_ns=captured_at_ns, application_fact=application_fact,
            target_window_handle=target_window_handle, target_process_id=target_process_id,
            window_rect=before_rect) if semantic_action == 'open_detail' else None)
        # 只在当前只读识别调用中开放命中采集，不通过请求 metadata 接受外部证明。
        with pinned_field_hit_collector(collector), pinned_control_hit_collector(icon_collector):
            recognition = self._recognize(
                image_path=image_path,
                goal=goal,
                uia_snapshot=uia_snapshot,
                originals=originals,
                semantic_action=semantic_action,
                control_target=control_target,
                scroll_parameters=scroll_parameters,
            )

        final_bound = self._window_manager.get_bound_window()
        final_identity = _bound_identity(
            final_bound, target_window_handle=target_window_handle,
        )
        if final_identity != before_identity or _bound_rect(final_bound) != before_rect:
            raise FreshLearningObservationError(
                "bound window changed after learning observation"
            )
        if self._read_application_fact(
            target_window_handle, target_process_id,
        ) != application_fact:
            raise FreshLearningObservationError(
                "application identity changed after learning observation"
            )
        _require_unchanged_screenshot(
            image_path, expected_sha256=screenshot_digest,
        )
        observed_at_ns = time.perf_counter_ns()
        evidence = {
            "contract_version": CONTRACT_VERSION,
            "capture": {
                "capture_id": capture_id,
                "screenshot_sha256": screenshot_digest,
                "viewport_size": viewport,
                "capture_clock_id": "windows-perf-counter-v1",
                "capture_started_ns": capture_started_ns,
                "captured_at_ns": captured_at_ns,
                "observed_at_ns": observed_at_ns,
            },
            "target": {
                "window_handle": target_window_handle,
                "process_id": target_process_id,
                "rect": before_rect,
            },
            "application": _public_application(self.application, application_fact),
            "uia": {
                "provider": uia_snapshot.get("provider"),
                "provider_version": uia_snapshot.get("provider_version"),
                "status": uia_snapshot.get("status"),
                "control_count": uia_snapshot.get("control_count"),
                "snapshot_sha256": uia_digest,
            },
            "recognition": recognition,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_executed": False,
        }
        evidence_bytes = _canonical_bytes(evidence)
        if originals is not None:
            originals["uia"] = _canonical_bytes(uia_snapshot)
        return FreshLearningObservationPacket(
            png_bytes=bytes(image_bytes),
            evidence_json=bytes(evidence_bytes),
        )

    def _read_application_fact(
        self,
        target_window_handle: int,
        target_process_id: int,
    ) -> dict[str, Any] | str:
        if self.application["kind"] == "native":
            return _validated_native_identity(
                self._native_identity_reader.read_identity(target_window_handle),
                target_window_handle=target_window_handle,
                process_id=target_process_id,
                expected_executable_path=self.application["executable_path"],
            )
        origin = _validated_origin_fact(
            self._origin_reader.read_origin(target_window_handle),
            target_window_handle=target_window_handle,
            process_id=target_process_id,
        )
        if origin != self.application["canonical_origin"]:
            raise FreshLearningObservationError(
                "current web origin does not match the configured application"
            )
        native = validate_native_identity_fact(
            self._native_identity_reader.read_identity(target_window_handle),
            target_window_handle=target_window_handle,
            expected_process_id=target_process_id,
        )
        if native is None:
            raise FreshLearningObservationError("current web native process binding is unavailable")
        return {"canonical_origin": origin, **native}

    def _recognize(
        self,
        *,
        image_path: Path,
        goal: str | None,
        uia_snapshot: Mapping[str, Any],
        originals: dict[str, bytes] | None = None,
        semantic_action: str | None = None,
        control_target: dict | None = None,
        scroll_parameters: dict | None = None,
    ) -> dict[str, Any]:
        if goal is None:
            return {
                "status": "not_requested",
                "goal": None,
                "result_sha256": None,
                "result_projection_contract": (
                    "fresh_read_only_recognition_projection_v1"
                ),
                "result_is_original": False,
                "result": None,
            }
        runner = self._recognition_runner
        configuration = self._vision_configuration
        if runner is None:
            configuration = configuration or load_formal_vision_configuration(
                resolve_vision_config_path(project_root=self.project_root),
            )
            runner = _run_existing_read_only_recognition
        result = runner(
            image_path=str(image_path),
            goal=goal,
            provider_mode=configuration.mode if configuration is not None else None,
            uia_snapshot=deepcopy(dict(uia_snapshot)),
            vision_configuration=configuration,
            **({"semantic_action": semantic_action} if semantic_action is not None else {}),
            **({"control_target": deepcopy(control_target)} if control_target is not None else {}),
            **({"scroll_parameters": deepcopy(scroll_parameters)} if scroll_parameters is not None else {}),
        )
        if not isinstance(result, Mapping):
            raise FreshLearningObservationError(
                "read-only recognition returned an invalid result"
            )
        result_path = result.get("image_path")
        if (
            not isinstance(result_path, str)
            or Path(result_path).resolve() != image_path.resolve()
        ):
            raise FreshLearningObservationError(
                "read-only recognition image path does not match the fresh capture"
            )
        candidates, grounding = _parse_recognition(result)
        if candidates.summary.get("control_target") != control_target:
            raise FreshLearningObservationError("read-only recognition control target differs from request")
        if (
            result.get("goal") != goal
            or candidates.goal != goal
            or grounding.goal != goal
        ):
            raise FreshLearningObservationError(
                "read-only recognition goal does not match the requested goal"
            )
        raw = _canonical_bytes(result)
        semantic_projection = {
            key: result[key]
            for key in _PUBLIC_RECOGNITION_KEYS
            if key in result
        }
        projected = _sanitize_result(
            semantic_projection, capture_path=image_path.resolve(),
        )
        _canonical_bytes(projected)
        if originals is not None:
            originals["recognition"] = raw
        return {
            "status": "completed",
            "goal": goal,
            "result_sha256": sha256(raw).hexdigest(),
            "result_projection_contract": (
                "fresh_read_only_recognition_projection_v1"
            ),
            "result_is_original": False,
            "result": projected,
        }


def _application_identity(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("application_identity must be an object")
    source = dict(value)
    kind = source.get("kind")
    if kind == "native" and set(source) == {"kind", "executable_path"}:
        path = normalize_windows_executable_path(source.get("executable_path"))
        if path is None:
            raise ValueError("native application requires an absolute executable_path")
        normalized = normalize_application_identity(
            {"kind": "native", "executable_path": path},
        )
        if normalized.get("identity_status") != "resolved":
            raise ValueError("native application identity is unresolved")
        return {"kind": "native", "executable_path": path}
    if kind == "web" and set(source) == {"kind", "canonical_origin"}:
        origin = source.get("canonical_origin")
        if not isinstance(origin, str) or not origin:
            raise ValueError("web application requires canonical_origin")
        normalized = normalize_application_identity(
            {"kind": "web", "canonical_origin": origin},
        )
        canonical = normalized.get("canonical_origin")
        if normalized.get("identity_status") != "resolved" or canonical != origin:
            raise ValueError("web canonical_origin must be a canonical HTTP(S) origin")
        return {"kind": "web", "canonical_origin": canonical}
    raise ValueError("application_identity must be strict native or web identity")


def _public_application(
    configured: Mapping[str, str],
    observed: dict[str, Any] | str,
) -> dict[str, Any]:
    if configured["kind"] == "web":
        if not isinstance(observed, dict):
            raise FreshLearningObservationError("web application fact is invalid")
        return {"kind": "web", "canonical_origin": observed["canonical_origin"],
                "executable_path": observed["executable_path"],
                "process_create_time": observed["process_create_time"]}
    if not isinstance(observed, dict):  # pragma: no cover
        raise FreshLearningObservationError("native application fact is invalid")
    return {
        "kind": "native",
        "executable_path": observed["executable_path"],
        "process_create_time": observed["process_create_time"],
    }


def _bound_rect(bound: Any) -> dict[str, int]:
    try:
        left = int(bound.rect.left)
        top = int(bound.rect.top)
        right = int(bound.rect.right)
        bottom = int(bound.rect.bottom)
    except (AttributeError, TypeError, ValueError) as error:
        raise FreshLearningObservationError("bound window rectangle is unavailable") from error
    if right <= left or bottom <= top:
        raise FreshLearningObservationError("bound window rectangle is invalid")
    return {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
    }


def _require_uia_rect(snapshot: Mapping[str, Any], rect: Mapping[str, int]) -> None:
    window = snapshot.get("window")
    bbox = window.get("bbox") if isinstance(window, Mapping) else None
    if not isinstance(bbox, Mapping) or {
        "x": bbox.get("x"),
        "y": bbox.get("y"),
        "width": bbox.get("w"),
        "height": bbox.get("h"),
    } != {"x": 0, "y": 0, "width": rect["width"], "height": rect["height"]}:
        raise FreshLearningObservationError(
            "current UIA snapshot rectangle does not match the bound capture epoch"
        )


def _goal(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_GOAL_LENGTH
        or "\x00" in value
    ):
        raise FreshLearningObservationError("goal must be nonempty bounded text or None")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FreshLearningObservationError(f"{label} must be a positive integer")
    return value


def _sanitize_result(value: Any, *, capture_path: Path) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise FreshLearningObservationError(
                    "read-only recognition result keys must be strings"
                )
            if _contains_capture_path(key, capture_path):
                raise FreshLearningObservationError(
                    "read-only recognition result exposes the original capture path"
                )
            lowered = key.casefold()
            if key in {'current_native_field_hit', 'current_native_control_hit'}:
                # 原生命中只保留明确的只读否定标记，后续仍完整复核来源与捕获绑定。
                hit = item.get('hit') if isinstance(item, Mapping) else None
                if (not isinstance(hit, Mapping) or hit.get('artifact_is_authorization') is not False
                        or hit.get('action_executed') is not False):
                    raise FreshLearningObservationError('native field hit must remain read-only')
                projected = _sanitize_result(item, capture_path=capture_path)
                projected['hit'].update(artifact_is_authorization=False, action_executed=False)
                result[key] = projected
                continue
            # 流程图统计不是文件路径；只保留已知的严格标量，未知路径字段仍过滤。
            metric_type = _PUBLIC_GRAPH_METRIC_TYPES.get(key)
            if metric_type is not None:
                if type(item) is not metric_type or (metric_type is int and item < 0):
                    raise FreshLearningObservationError("read-only graph recall metric has invalid type or value")
                result[key] = item
                continue
            if lowered in _FORBIDDEN_RESULT_KEYS or "path" in lowered:
                continue
            result[key] = _sanitize_result(item, capture_path=capture_path)
        return result
    if isinstance(value, list):
        return [
            _sanitize_result(item, capture_path=capture_path) for item in value
        ]
    if isinstance(value, tuple):
        return [
            _sanitize_result(item, capture_path=capture_path) for item in value
        ]
    if isinstance(value, str) and _contains_capture_path(value, capture_path):
        raise FreshLearningObservationError(
            "read-only recognition result exposes the original capture path"
        )
    return deepcopy(value)


def _contains_capture_path(value: str, capture_path: Path) -> bool:
    normalized_value = value.replace("/", "\\").casefold()
    normalized_path = str(capture_path).replace("/", "\\").casefold()
    return normalized_path in normalized_value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise FreshLearningObservationError(
            "fresh observation evidence is not canonical JSON"
        ) from error


__all__ = [
    "FreshLearningObservationError",
    "FreshLearningObservationOwner",
    "FreshLearningObservationPacket",
    "FreshLearningActionObservation",
]
