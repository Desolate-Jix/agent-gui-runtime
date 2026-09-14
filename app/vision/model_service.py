"""正式单步模型准备；复用既有启动器，只拥有本次创建的 Job。"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.vision.configuration import VisionConfigurationSnapshot, _select_local_config, _source_project_root


class ModelServiceError(RuntimeError):
    def __init__(self, code: str, *, result_unknown: bool = False) -> None:
        self.code = code
        self.result_unknown = result_unknown
        super().__init__(code)


@dataclass(frozen=True)
class ModelServiceConfiguration:
    readiness_timeout_seconds: float
    _profile_json: str = field(repr=False)
    worker_executable: Path | None = field(default=None, repr=False)

    def profile(self) -> dict[str, Any]:
        return json.loads(self._profile_json)


def freeze_model_service(snapshot: VisionConfigurationSnapshot) -> ModelServiceConfiguration | None:
    local = _select_local_config(snapshot.to_dict()["vision"], snapshot.mode)
    settings = local.get("model_service")
    if settings is None:
        return None
    if (not isinstance(settings, dict) or settings.get("mode") != "managed"
            or set(settings) - {"mode", "profile_path", "readiness_timeout_seconds"}):
        raise ModelServiceError("model_service_config_invalid")
    timeout = settings.get("readiness_timeout_seconds", 180.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ModelServiceError("model_service_config_invalid")
    raw_path = settings.get("profile_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ModelServiceError("model_service_config_invalid")
    path = Path(raw_path).expanduser()
    path = (snapshot.path.parent / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ModelServiceError("model_service_profile_unreadable") from error
    if (not isinstance(profile, dict) or profile.get("launchable") is not True
            or not isinstance(profile.get("profile_id"), str)
            or re.fullmatch(r"[A-Za-z0-9_-]+", profile["profile_id"]) is None):
        raise ModelServiceError("model_service_profile_invalid")
    endpoint = urlparse(local["endpoint"])
    if (endpoint.hostname not in {"127.0.0.1", "::1", "localhost"} or endpoint.username or endpoint.password
            or profile.get("endpoint") != local["endpoint"] or profile.get("model_name") != local["model_name"]
            or type(profile.get("port")) is not int or profile["port"] != (endpoint.port or (443 if endpoint.scheme == "https" else 80))):
        raise ModelServiceError("model_service_profile_mismatch")
    # 调用端是回环地址不代表监听端也是；二者必须绑定，不能把无鉴权服务公开到网卡。
    host = profile.get("host", endpoint.hostname)
    if host != endpoint.hostname:
        raise ModelServiceError("model_service_profile_mismatch")
    profile["host"] = host
    if profile.get("request_cancel_supported") is True:
        try:
            cancel = urlparse(profile.get("request_cancel_endpoint") or "")
            if (cancel.scheme != endpoint.scheme or cancel.hostname != endpoint.hostname
                    or (cancel.port or (443 if cancel.scheme == "https" else 80)) != profile["port"]
                    or cancel.username or cancel.password or cancel.query or cancel.fragment
                    or cancel.path.rstrip("/") not in {"/cancel", "/v1/cancel"}):
                raise ValueError("cancel endpoint differs")
        except (ValueError, TypeError) as error:
            raise ModelServiceError("model_service_cancel_endpoint_mismatch") from error
    source_root = _source_project_root()
    resource_root = source_root if path.parent == (source_root / "configs/model_profiles").resolve() else path.parent
    worker_executable = None
    if (str(profile.get("runtime") or "").strip().casefold() == "transformers"
            or str(profile.get("output_contract") or "").strip().casefold() == "vista_point_v1"):
        if "python_path" not in profile:
            if getattr(sys, "frozen", False):
                executable = Path(sys.executable).resolve()
                if (str(profile.get("output_contract") or "").strip().casefold() != "vista_point_v1"
                        or executable.name.casefold() not in {"agentreview.exe", "agentreviewbridge.exe"}):
                    raise ModelServiceError("model_service_interpreter_required")
                # 只派生同一安装位置的固定入口，不把 GUI 当解释器或从 PATH 寻找替代。
                worker_executable = executable.with_name("AgentReviewBridge.exe")
                if not worker_executable.is_file():
                    raise ModelServiceError("model_service_worker_missing")
            else:
                profile["python_path"] = sys.executable
    for key in ("model_path", "mmproj_path", "server_path", "start_script", "stop_script", "python_path"):
        value = profile.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ModelServiceError("model_service_profile_invalid")
        candidate = Path(value).expanduser()
        profile[key] = str((resource_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve())
    if "python_path" in profile and not Path(profile["python_path"]).is_file():
        raise ModelServiceError("model_service_interpreter_invalid")
    if ((worker_executable is None and not profile.get("start_script"))
            or not profile.get("model_path") or profile["model_path"] != local.get("model_path")):
        raise ModelServiceError("model_service_profile_mismatch")
    return ModelServiceConfiguration(float(timeout), json.dumps(profile, ensure_ascii=False, sort_keys=True), worker_executable)


class FormalModelService:
    """由串行 Runtime 线程调用；取消方只设置事件，不越线程关闭 Job。"""

    def __init__(self, configuration: ModelServiceConfiguration, *, output_root: Path,
                 allow_resource_coexistence: bool = False) -> None:
        if type(allow_resource_coexistence) is not bool:
            raise ModelServiceError("model_service_config_invalid")
        self._configuration = configuration
        self._allow_resource_coexistence = allow_resource_coexistence
        self._profile = configuration.profile()
        identity = uuid4().hex
        self._scope_name = "Local\\AgentGuiNativeModel-" + sha256(identity.encode("ascii")).hexdigest()
        self._output_root = Path(output_root).resolve() / "model-services" / identity
        self._pid_path = self._output_root / "model-server-pids" / (self._profile["profile_id"] + ".pid")
        self._scope = None
        self._initialization_cleanup = None
        self._prepared = False
        self._closed = False
        self._ownership = "none"
        self._instance_identity: tuple[tuple[int, int], ...] | None = None
        self._pending_request_id: str | None = None
        self._completed_request_id: str | None = None
        self._last_cancellation: dict[str, Any] | None = None
        self._cleanup_member_identities: dict[tuple[int, int], dict[str, int]] = {}

    def prepare(self, cancelled: Event) -> dict[str, Any]:
        from app.core import model_server
        from app.learn.hybrid import windows_process_scope as scopes

        if self._closed or self._prepared or self._scope is not None or self._initialization_cleanup is not None:
            raise ModelServiceError("model_service_invalid_phase")
        try:
            self._check_cancel(cancelled)
            deadline = time.monotonic() + self._configuration.readiness_timeout_seconds
            state = self._probe(deadline)
            self._check_cancel(cancelled)
            if state.get("status") not in {"running", "loading", "busy"}:
                if scopes._listeners([self._profile["port"]]):
                    raise ModelServiceError("model_service_endpoint_in_use")
                if not self._allow_resource_coexistence:
                    self._reject_resource_conflict(cancelled, deadline)
                self._check_cancel(cancelled)
                if not scopes.scoped_process_launch_ready():
                    raise ModelServiceError("model_service_scope_unavailable")
                self._scope = scopes.WindowsProcessScope(self._scope_name, create=True)
                self._ownership = "owned"
                model_server.start_model_server(self._profile, scope_name=self._scope_name,
                    child_env=dict(os.environ), output_root=self._output_root, cancelled=cancelled, deadline=deadline,
                    **({"worker_executable": self._configuration.worker_executable}
                       if self._configuration.worker_executable is not None else {}))
                self._check_cancel(cancelled)
                state = self._probe(deadline)
            else:
                self._ownership = "external"
            while True:
                self._check_cancel(cancelled)
                if time.monotonic() >= deadline:
                    raise ModelServiceError("model_service_readiness_timeout")
                if state.get("status") == "running":
                    if state.get("model_id") != self._profile["model_name"]:
                        raise ModelServiceError("model_service_identity_mismatch")
                    self._instance_identity = self._listener_identity()
                    confirmed = self._probe(deadline)
                    if self._listener_identity() != self._instance_identity:
                        raise ModelServiceError("model_service_instance_changed")
                    if confirmed.get("status") != "running":
                        state = confirmed
                        continue
                    if confirmed.get("model_id") != self._profile["model_name"]:
                        raise ModelServiceError("model_service_identity_mismatch")
                    self._check_cancel(cancelled)
                    if time.monotonic() >= deadline:
                        raise ModelServiceError("model_service_readiness_timeout")
                    self._prepared = True
                    return {"status": "ready", "ownership": self._ownership}
                if self._scope is not None and not self._scope.pids():
                    raise ModelServiceError("model_service_exited")
                cancelled.wait(min(0.05, max(0.0, deadline - time.monotonic())))
                self._check_cancel(cancelled)
                state = self._probe(deadline)
        except BaseException as error:
            if isinstance(error, scopes.HybridProcessScopeHandleCleanupError):
                self._initialization_cleanup = error.cleanup_owner
            self._retain_cleanup_identities(getattr(error, "cleanup_evidence", {}))
            self.close()
            if isinstance(error, ModelServiceError):
                raise
            if not isinstance(error, Exception):
                raise
            if getattr(error, "code", None) in {"model_service_cancelled", "model_service_readiness_timeout"}:
                raise ModelServiceError(error.code) from error
            raise ModelServiceError("model_service_prepare_failed") from error

    def can_retain(self) -> bool:
        """只判断驻留资格；不探测健康，不收养外部进程。"""
        return (self._ownership == "owned" and self._prepared and not self._closed
                and self._pending_request_id is None and self._scope is not None
                and self._initialization_cleanup is None)

    def reuse_ready(self, cancelled: Event) -> dict[str, Any]:
        """重验原实例；失败保留持有者，由串行协调器负责清理。"""
        if (self._closed or not self._prepared or self._instance_identity is None
                or self._initialization_cleanup is not None
                or self._ownership not in {"owned", "external"}
                or (self._ownership == "owned" and self._scope is None)):
            raise ModelServiceError("model_service_invalid_phase")
        if self._pending_request_id is not None:
            raise ModelServiceError("model_service_request_pending", result_unknown=True)
        try:
            self._check_cancel(cancelled)
            deadline = time.monotonic() + self._configuration.readiness_timeout_seconds
            if self._listener_identity() != self._instance_identity:
                raise ModelServiceError("model_service_instance_changed")
            self._check_cancel(cancelled)
            state = self._probe(deadline)
            self._check_cancel(cancelled)
            if self._listener_identity() != self._instance_identity:
                raise ModelServiceError("model_service_instance_changed")
            self._check_cancel(cancelled)
            if time.monotonic() >= deadline:
                raise ModelServiceError("model_service_readiness_timeout")
            if state.get("status") != "running":
                raise ModelServiceError("model_service_not_ready")
            if state.get("model_id") != self._profile["model_name"]:
                raise ModelServiceError("model_service_identity_mismatch")
            return {"status": "ready", "ownership": self._ownership, "reused": True}
        except ModelServiceError:
            raise
        except Exception as error:
            raise ModelServiceError("model_service_reuse_failed") from error

    def _listener_identity(self) -> tuple[tuple[int, int], ...]:
        from app.learn.hybrid import windows_process_scope as scopes

        try:
            pids = {item["pid"] for item in scopes._listeners([self._profile["port"]])}
            if not pids or any(type(pid) is not int or pid <= 0 for pid in pids):
                raise ModelServiceError("model_service_instance_unobservable")
            if self._scope is not None and not pids.issubset(set(self._scope.pids())):
                raise ModelServiceError("model_service_owner_mismatch")
            records = scopes._identities_for_pids(sorted(pids))
            identity = tuple(sorted((item["pid"], item["create_time_ns"]) for item in records))
            if ({pid for pid, _ in identity} != pids or len(identity) != len(pids)
                    or any(type(created) is not int or created <= 0 for _, created in identity)
                    or {item["pid"] for item in scopes._listeners([self._profile["port"]])} != pids):
                raise ModelServiceError("model_service_instance_unobservable")
            return identity
        except ModelServiceError:
            raise
        except Exception as error:
            raise ModelServiceError("model_service_instance_unobservable") from error

    def verify_request_instance(self, endpoint: str, model_name: str) -> None:
        if self._closed or not self._prepared or self._instance_identity is None:
            raise ModelServiceError("model_service_invalid_phase")
        expected = str(self._profile["endpoint"]).rstrip("/")
        if not expected.endswith("/chat/completions"):
            expected += "/chat/completions" if expected.endswith("/v1") else "/v1/chat/completions"
        if endpoint != expected or model_name != self._profile["model_name"]:
            raise ModelServiceError("model_service_request_mismatch")
        if self._listener_identity() != self._instance_identity:
            raise ModelServiceError("model_service_instance_changed")

    def begin_request(self, request_id: str) -> None:
        if self._closed or not self._prepared:
            raise ModelServiceError("model_service_invalid_phase")
        if self._pending_request_id is not None:
            raise ModelServiceError("model_service_request_pending", result_unknown=True)
        if not isinstance(request_id, str) or not request_id.strip():
            raise ModelServiceError("model_service_request_mismatch")
        self._pending_request_id = request_id
        self._last_cancellation = None

    def complete_request(self, request_id: str) -> None:
        if request_id != self._pending_request_id:
            raise ModelServiceError("model_service_request_mismatch")
        self._completed_request_id = request_id
        self._pending_request_id = None

    def cancel_request(self, request_id: str) -> dict[str, Any]:
        from app.core.model_server import _cancel_profile_request
        from app.vision.request_control import ModelRequestContext, read_cancellable_response

        if request_id != self._pending_request_id:
            if request_id == self._completed_request_id:
                return {"request_id": request_id, "status": "response_completed", "computation_stopped": False}
            raise ModelServiceError("model_service_request_mismatch")
        status = "unsupported"
        if self._profile.get("request_cancel_supported") is True:
            endpoint = str(self._profile["endpoint"]).rstrip("/")
            if not endpoint.endswith("/chat/completions"):
                endpoint += "/chat/completions" if endpoint.endswith("/v1") else "/v1/chat/completions"
            # 控制请求有独立预算；不能复位或忽略原推理请求已经收到的取消。
            control = ModelRequestContext(Event())
            proof = _cancel_profile_request(profile=self._profile, request_id=request_id,
                timeout=0.5, verify_seconds=1.0,
                verify_instance=lambda: self.verify_request_instance(endpoint, self._profile["model_name"]),
                request_reader=lambda request, timeout: read_cancellable_response(request, timeout=timeout, context=control))
            status = str(proof.get("status") or "unverified")
        stopped = status in {"terminated", "request_not_active"}
        evidence = {"request_id": request_id, "status": status, "computation_stopped": stopped,
                    "ownership": self._ownership}
        self._last_cancellation = evidence
        if stopped:
            self._pending_request_id = None
        return dict(evidence)

    def _probe(self, deadline: float, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        from app.core import model_server

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelServiceError("model_service_readiness_timeout")
        # 现有健康探测至多依次查询 health/models；每次阻塞均分剩余预算。
        return model_server.check_model_server(self._profile if profile is None else profile,
                                               timeout=min(0.25, remaining / 2))

    def _reject_resource_conflict(self, cancelled: Event, deadline: float) -> None:
        from app.core import model_server

        group = self._profile.get("exclusive_resource_group")
        if not group:
            return
        for profile in model_server.load_model_profiles():
            if profile.get("exclusive_resource_group") != group or profile.get("endpoint") == self._profile["endpoint"]:
                continue
            self._check_cancel(cancelled)
            if self._probe(deadline, profile).get("status") in {"running", "loading", "busy"}:
                raise ModelServiceError("model_service_resource_conflict")

    @staticmethod
    def _check_cancel(cancelled: Event) -> None:
        if cancelled.is_set():
            raise ModelServiceError("model_service_cancelled")

    def _retain_cleanup_identities(self, evidence: dict[str, Any]) -> None:
        if not isinstance(evidence, dict):
            return
        observed = evidence.get("scope_cleanup_evidence", evidence)
        if not isinstance(observed, dict) or observed.get("scope_name") != self._scope_name:
            return
        # 下层可在预采样之后发现新子进程；失败回执中的身份必须进入同一重试状态。
        for key in ("observed_member_identities_before", "remaining_owned_process_identities"):
            for item in observed.get(key, []):
                self._cleanup_member_identities[(item["pid"], item["create_time_ns"])] = dict(item)

    def close(self) -> dict[str, Any]:
        from app.learn.hybrid.windows_process_scope import _identities_for_pids, observe_process_scope_cleanup

        if self._pending_request_id is not None and self._ownership == "external":
            evidence = self.cancel_request(self._pending_request_id)
            if evidence.get("computation_stopped") is not True:
                raise ModelServiceError("model_service_compute_pending", result_unknown=True)

        if self._initialization_cleanup is not None:
            try:
                # 初始化失败没有启动子进程；只重试原句柄关闭，绝不终止可能同名的外部 Job。
                self._initialization_cleanup.close()
            except Exception as error:
                raise ModelServiceError("model_service_cleanup_pending", result_unknown=True) from error
            self._initialization_cleanup = None
        if self._scope is not None:
            try:
                # 失败重试时 Job 可能已空，旧进程身份不能随观察调用结束而丢失。
                for item in _identities_for_pids(self._scope.pids()):
                    self._cleanup_member_identities[(item["pid"], item["create_time_ns"])] = item
                # 只证明本 Job 和专用 PID 文件清空，不要求也不清理旁人的监听端口。
                evidence = observe_process_scope_cleanup(self._scope_name, terminate=True,
                    listener_ports=[], pid_file=self._pid_path, remove_owned_pid_file=True,
                    stable_zero_observations=3, interval_seconds=0.1,
                    retained_process_identities=tuple(self._cleanup_member_identities.values()))
                self._retain_cleanup_identities(evidence)
                if evidence.get("cleanup_status") != "verified":
                    raise ModelServiceError("model_service_cleanup_pending", result_unknown=True)
                self._scope.close()
            except Exception as error:
                raise ModelServiceError("model_service_cleanup_pending", result_unknown=True) from error
            self._scope = None
            self._cleanup_member_identities.clear()
            self._pending_request_id = None
        self._closed = True
        return {"cleanup_verified": True, "ownership": self._ownership}
