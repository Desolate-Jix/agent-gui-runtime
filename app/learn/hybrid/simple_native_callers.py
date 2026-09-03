"""Guarded actual caller seams; importing this module never starts a model."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots


class HTTPTransport(Protocol):
    def post(self, *, url: str, payload: Mapping[str, object], timeout: float) -> object: ...


@dataclass(frozen=True)
class SimpleNativeActualDependencies:
    scope_name: Callable[[Mapping[str, object], str], str]
    create_scope: Callable[[str], object]
    observe_scope_cleanup: Callable[..., Mapping[str, object]]
    build_omni_adapter: Callable[[], object]
    load_omni_cleanup: Callable[[str], Mapping[str, object]]
    acquire_qwen: Callable[..., dict[str, Any]]
    run_qwen: Callable[..., object]
    release_qwen: Callable[[dict[str, Any], str], Mapping[str, object]]
    acquire_vista: Callable[..., dict[str, Any]]
    run_vista: Callable[..., str]
    release_vista: Callable[..., Mapping[str, object]]


def _response_value(value: object) -> object:
    if isinstance(value, Mapping) and "content" in value:
        return value["content"]
    return value


def call_qwen_projected_binding(
    *, image_path: Path, projection: Mapping[str, object], transport: HTTPTransport
) -> object:
    """Send only the short projection; full runtime request remains with the runner."""
    payload = {
        "projection": dict(projection),
        "image_path": str(image_path),
        "instruction": "Return closed per-goal bindings only.",
    }
    return _response_value(transport.post(url="qwen", payload=payload, timeout=120.0))


def call_vista_bare_point(
    *, roi_path: Path, target_text: str, transport: HTTPTransport
) -> str:
    """Dedicated native VISTA transport: no generic system message/JSON response format."""
    payload = {
        "messages": [
            {
                "role": "user",
                "content": f"{target_text}\nReturn only [x,y] normalized to 0..1000.",
            }
        ],
        "image_path": str(roi_path),
    }
    result = _response_value(transport.post(url="vista", payload=payload, timeout=120.0))
    if not isinstance(result, str):
        raise ValueError("VISTA transport must return raw text")
    return result


def project_omni_official_items(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Remove all worker/runtime fields before the native contract boundary."""
    return {
        "items": [
            {
                "bbox": item.get("bbox"),
                "type": item.get("type"),
                "content": item.get("content"),
                "interactivity": item.get("interactivity"),
            }
            for item in items
        ]
    }


class SimpleNativeActualSession:
    """按 Omni、Qwen、VISTA 顺序持有单个 provider 的精确作用域。"""

    _PROVIDERS = ("omni", "qwen", "vista")

    def __init__(
        self,
        *,
        config: Mapping[str, object],
        artifact_dir: Path,
        dependencies: SimpleNativeActualDependencies,
    ) -> None:
        provider = config.get("provider")
        profiles = provider.get("profile_ids") if isinstance(provider, Mapping) else None
        limits = config.get("limits")
        if (
            not isinstance(profiles, Mapping)
            or set(profiles) != set(self._PROVIDERS)
            or any(not isinstance(profiles[name], str) or not profiles[name] for name in self._PROVIDERS)
            or not isinstance(limits, Mapping)
            or isinstance(limits.get("timeout_seconds"), bool)
            or not isinstance(limits.get("timeout_seconds"), int)
            or limits["timeout_seconds"] <= 0
            or isinstance(limits.get("max_output_bytes"), bool)
            or not isinstance(limits.get("max_output_bytes"), int)
            or limits["max_output_bytes"] <= 0
        ):
            raise ValueError("simple-native actual configuration is invalid")
        self._profiles = {name: str(profiles[name]) for name in self._PROVIDERS}
        self._timeout = int(limits["timeout_seconds"])
        self._max_output_bytes = int(limits["max_output_bytes"])
        self._artifact_dir = artifact_dir.resolve()
        self._dependencies = dependencies
        identity = sha256(
            json.dumps(
                {"config": deepcopy(dict(config)), "artifact_dir": str(self._artifact_dir)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self._lineage = {
            "run_id": f"simple-native-actual-{identity[:16]}",
            "workflow_revision": 1,
            "operation_id": f"simple-native-provider-diagnostic-{identity[:16]}",
            "stage": "simple_native_provider_diagnostic",
            "stage_execution_id": identity,
        }
        self._active: dict[str, Any] | None = None
        self._next_provider = 0
        self._blocked = False
        self._omni_adapter: object | None = None
        self._cleanup_receipts: list[dict[str, object]] = []

    @property
    def slots(self) -> SimpleNativeSlots:
        return SimpleNativeSlots(
            omni=self.omni,
            qwen=self.qwen,
            vista=self.vista,
            release_provider=self.release_provider,
            cleanup=self.cleanup,
        )

    def _begin(self, provider: str) -> dict[str, Any]:
        if self._blocked:
            raise RuntimeError("simple-native actual provider transition is blocked")
        if self._next_provider >= len(self._PROVIDERS) or self._PROVIDERS[self._next_provider] != provider:
            raise RuntimeError("simple-native actual provider order is invalid")
        if self._active is not None:
            if self._active["provider"] != provider:
                raise RuntimeError("another simple-native provider still owns the GPU")
            if self._active["dispatch_failed"]:
                raise RuntimeError("simple-native provider phase is blocked after failed dispatch")
            return self._active
        scope_name = self._dependencies.scope_name(self._lineage, provider)
        saved_environment = {
            name: os.environ.get(name)
            for name in (
                "AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME",
                "AGENT_GUI_HYBRID_LINEAGE_JSON",
                "AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH",
            )
        }
        scope = self._dependencies.create_scope(scope_name)
        os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] = scope_name
        os.environ["AGENT_GUI_HYBRID_LINEAGE_JSON"] = json.dumps(
            self._lineage, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        os.environ.pop("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", None)
        self._active = {
            "provider": provider,
            "scope_name": scope_name,
            "scope": scope,
            "saved_environment": saved_environment,
            "lease": None,
            "invocation_ids": [],
            "call_evidence": [],
            "call_count": 0,
            "dispatch_failed": False,
        }
        return self._active

    def omni(self, image_path: Path) -> object:
        phase = self._begin("omni")
        if phase["call_count"] >= 5:
            raise RuntimeError("simple-native Omni call limit exceeded")
        from app.learn.recognition.uei.provider_adapters import (
            ProviderRunBudget,
            RestrictedCaptureLease,
        )

        path = image_path.resolve()
        image_bytes = path.read_bytes()
        image_sha256 = sha256(image_bytes).hexdigest()
        with Image.open(path) as image:
            image_size = {"width": image.width, "height": image.height}
        invocation_id = f"invocation/simple-native/{self._lineage['stage_execution_id']}/omni/{phase['call_count'] + 1}"
        runtime_path = self._artifact_dir / "actual-lifecycle" / f"omni-{phase['call_count'] + 1}.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        os.environ["AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH"] = str(runtime_path)
        ref = {"id": invocation_id, "content_sha256": image_sha256}
        capture = RestrictedCaptureLease(
            request_ref=deepcopy(ref),
            capture_lineage_ref=deepcopy(ref),
            artifact_ref=deepcopy(ref),
            capture_id=f"capture/{image_sha256}",
            artifact_sha256=image_sha256,
            image_size=image_size,
            local_path=path,
        )
        budget = ProviderRunBudget(
            timeout_ms=self._timeout * 1000,
            max_output_bytes=self._max_output_bytes,
            max_element_count=512,
            max_string_length=4096,
            resource_group="gpu_vision",
        )
        try:
            if self._omni_adapter is None:
                self._omni_adapter = self._dependencies.build_omni_adapter()
            invoke = getattr(self._omni_adapter, "invoke_native", None)
            if not callable(invoke):
                raise RuntimeError("managed Omni adapter has no native invocation")
            if getattr(self._omni_adapter, "profile_id", None) != self._profiles["omni"]:
                raise RuntimeError("managed Omni adapter profile does not match actual configuration")
            result = invoke(
                capture=capture,
                budget=budget,
                invocation_id=invocation_id,
                cancellation_event=None,
            )
            phase["call_evidence"].append(
                {"invocation_id": invocation_id, "capture_sha256": image_sha256}
            )
            return result
        except BaseException:
            phase["dispatch_failed"] = True
            raise
        finally:
            if runtime_path.is_file():
                phase["invocation_ids"].append(invocation_id)
            phase["call_count"] += 1

    def qwen(self, image_path: Path, projection: Mapping[str, object]) -> object:
        phase = self._begin("qwen")
        if phase["call_count"] >= 5:
            raise RuntimeError("simple-native Qwen call limit exceeded")
        try:
            if phase["lease"] is None:
                phase["lease"] = self._dependencies.acquire_qwen(
                    profile_id=self._profiles["qwen"],
                    request_id=f"simple-native-actual-qwen-{self._lineage['stage_execution_id']}",
                    wait_seconds=float(self._timeout),
                    scope_name=phase["scope_name"],
                )
            image_bytes = image_path.resolve().read_bytes()
            result = self._dependencies.run_qwen(
                projection=deepcopy(dict(projection)),
                screenshot_bytes=image_bytes,
                screenshot_media_type=_image_media_type(image_path),
                screenshot_sha256=sha256(image_bytes).hexdigest(),
                model_lease=phase["lease"],
                timeout_seconds=float(self._timeout),
            )
            phase["call_evidence"].append(
                {
                    "projection_sha256": _content_sha256(projection),
                    "response_sha256": _content_sha256(result),
                }
            )
            return result
        except BaseException:
            phase["dispatch_failed"] = True
            raise
        finally:
            phase["call_count"] += 1

    def vista(self, roi_path: Path, target_text: str) -> str:
        phase = self._begin("vista")
        if phase["call_count"] >= 25:
            raise RuntimeError("simple-native VISTA call limit exceeded")
        try:
            if phase["lease"] is None:
                phase["lease"] = self._dependencies.acquire_vista(
                    profile_id=self._profiles["vista"],
                    wait_seconds=float(self._timeout),
                    scope_name=phase["scope_name"],
                )
            roi_bytes = roi_path.resolve().read_bytes()
            result = self._dependencies.run_vista(
                roi_bytes=roi_bytes,
                roi_media_type=_image_media_type(roi_path),
                roi_sha256=sha256(roi_bytes).hexdigest(),
                target_text=target_text,
                model_lease=phase["lease"],
                timeout_seconds=float(self._timeout),
            )
            phase["call_evidence"].append(
                {
                    "roi_sha256": sha256(roi_bytes).hexdigest(),
                    "target_text": target_text,
                    "response_sha256": sha256(result.encode("utf-8")).hexdigest(),
                }
            )
            return result
        except BaseException:
            phase["dispatch_failed"] = True
            raise
        finally:
            phase["call_count"] += 1

    def release_provider(self, provider: str) -> Mapping[str, object]:
        if self._next_provider >= len(self._PROVIDERS) or self._PROVIDERS[self._next_provider] != provider:
            raise RuntimeError("simple-native actual provider release order is invalid")
        phase = self._active
        if phase is None:
            scope_name = self._dependencies.scope_name(self._lineage, provider)
            outer = self._dependencies.observe_scope_cleanup(
                scope_name,
                terminate=False,
                stable_zero_observations=3,
            )
            receipt = _cleanup_receipt(provider, outer=outer, source_clean=True)
            self._next_provider += 1
            self._cleanup_receipts.append(receipt)
            if not receipt["verified"]:
                self._blocked = True
            return receipt
        if phase["provider"] != provider:
            raise RuntimeError("simple-native actual provider release does not match active scope")
        release_error: BaseException | None = None
        source_clean = False
        source: object = None
        outer: Mapping[str, object] = {}
        close_error: BaseException | None = None
        try:
            try:
                if provider == "omni":
                    source = [
                        self._dependencies.load_omni_cleanup(invocation_id)
                        for invocation_id in phase["invocation_ids"]
                    ]
                    source_clean = _omni_source_is_clean(source)
                elif provider == "qwen":
                    if phase["lease"] is None:
                        source_clean = True
                    else:
                        source = self._dependencies.release_qwen(
                            phase["lease"],
                            "provider_failure" if phase["dispatch_failed"] else "completed",
                        )
                        source_clean = _qwen_source_is_clean(source)
                else:
                    if phase["lease"] is None:
                        source_clean = True
                    else:
                        source = self._dependencies.release_vista(
                            model_lease=phase["lease"],
                            lineage=deepcopy(self._lineage),
                            predecessor_sha256=_content_sha256(
                                {"provider": "qwen", "stage_execution_id": self._lineage["stage_execution_id"]}
                            ),
                            provider_result_sha256=_content_sha256(phase["call_evidence"]),
                        )
                        source_clean = _vista_source_is_clean(source)
            except BaseException as error:
                release_error = error
            try:
                outer = self._dependencies.observe_scope_cleanup(
                    phase["scope_name"],
                    terminate=True,
                    stable_zero_observations=3,
                )
            except BaseException as error:
                if release_error is None:
                    release_error = error
        finally:
            try:
                close = getattr(phase["scope"], "close", None)
                if not callable(close):
                    raise RuntimeError("simple-native provider scope has no close operation")
                close()
            except BaseException as error:
                close_error = error
            self._restore_environment(phase["saved_environment"])
            self._active = None
            self._next_provider += 1
            if phase["dispatch_failed"] or release_error is not None or close_error is not None:
                self._blocked = True
        if release_error is not None or close_error is not None:
            failure = RuntimeError(f"{provider} managed cleanup failed")
            raise failure from (release_error or close_error)
        receipt = _cleanup_receipt(provider, outer=outer, source_clean=source_clean, source=source)
        self._cleanup_receipts.append(receipt)
        if not receipt["verified"]:
            self._blocked = True
        return receipt

    def cleanup(self) -> Mapping[str, object]:
        verified = (
            self._next_provider == len(self._PROVIDERS)
            and len(self._cleanup_receipts) == len(self._PROVIDERS)
            and [receipt["provider"] for receipt in self._cleanup_receipts]
            == list(self._PROVIDERS)
            and all(receipt.get("verified") is True for receipt in self._cleanup_receipts)
            and not self._blocked
            and self._active is None
        )
        return {
            "contract_version": "simple_native_actual_session_cleanup_v1",
            "verified": verified,
            "provider_receipts": deepcopy(self._cleanup_receipts),
        }

    @staticmethod
    def _restore_environment(saved: Mapping[str, object]) -> None:
        for name, value in saved.items():
            if isinstance(value, str):
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _default_actual_dependencies() -> SimpleNativeActualDependencies:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        observe_process_scope_cleanup,
        process_scope_name,
    )
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        load_omniparser_invocation_cleanup_observation,
    )

    def acquire_qwen(**kwargs: object) -> dict[str, Any]:
        scope_name = str(kwargs.pop("scope_name"))
        if os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME") != scope_name:
            raise RuntimeError("simple-native Qwen scope environment changed before acquisition")
        return model_server.ensure_and_acquire_scoped_qwen_model_lease(
            stage="understanding",
            profile_id=str(kwargs["profile_id"]),
            request_id=str(kwargs["request_id"]),
            wait_seconds=float(kwargs["wait_seconds"]),
        )

    def acquire_vista(**kwargs: object) -> dict[str, Any]:
        scope_name = str(kwargs["scope_name"])
        if os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME") != scope_name:
            raise RuntimeError("simple-native VISTA scope environment changed before acquisition")
        profile_id = str(kwargs["profile_id"])
        profile = model_server.profile_for_stage("grounding", profile_id)
        readiness = model_server.ensure_model_server(
            stage="grounding",
            profile_id=profile_id,
            wait_until_ready=True,
            wait_seconds=float(kwargs["wait_seconds"]),
        )
        return model_server.build_hybrid_vista_model_lease(profile, readiness)

    return SimpleNativeActualDependencies(
        scope_name=process_scope_name,
        create_scope=lambda name: WindowsProcessScope(name, create=True),
        observe_scope_cleanup=observe_process_scope_cleanup,
        build_omni_adapter=OmniParserShadowAdapter,
        load_omni_cleanup=load_omniparser_invocation_cleanup_observation,
        acquire_qwen=acquire_qwen,
        run_qwen=model_server.run_qwen_projection_model,
        release_qwen=model_server.release_scoped_qwen_model_lease,
        acquire_vista=acquire_vista,
        run_vista=model_server.run_hybrid_vista_bare_point,
        release_vista=model_server.release_hybrid_vista_model_lease,
    )


def make_actual_simple_native_slots(
    *,
    config: Mapping[str, object],
    artifact_dir: Path,
    dependencies: SimpleNativeActualDependencies | None = None,
) -> SimpleNativeSlots:
    session = SimpleNativeActualSession(
        config=config,
        artifact_dir=artifact_dir,
        dependencies=dependencies or _default_actual_dependencies(),
    )
    return session.slots


def _image_media_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    raise ValueError("simple-native provider image type is unsupported")


def _content_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _scope_is_clean(scope: Mapping[str, object]) -> bool:
    return (
        scope.get("cleanup_status") == "verified"
        and scope.get("member_pids_after") == []
        and scope.get("member_identities_after") == []
        and scope.get("active_listeners_after") == []
        and scope.get("pid_file_after") is None
    )


def _omni_source_is_clean(source: object) -> bool:
    return isinstance(source, list) and all(
        isinstance(item, Mapping)
        and item.get("cleanup_status") == "verified"
        and item.get("inventory_observable") is True
        and item.get("provider_processes_after") == []
        and item.get("orphan_descendant_identities") == []
        and item.get("active_listeners_after") == []
        and item.get("lease_files_after") == []
        and isinstance(item.get("process_scope_cleanup"), Mapping)
        and item["process_scope_cleanup"].get("cleanup_status") == "verified"
        for item in source
    )


def _qwen_source_is_clean(source: object) -> bool:
    return (
        isinstance(source, Mapping)
        and source.get("status") == "released"
        and source.get("shared_server_retained") is False
        and source.get("server_termination")
        in {"verified_exact_process_exited", "verified_exact_process_proven_absent_on_retry"}
        and isinstance(source.get("release"), Mapping)
        and source["release"].get("status") == "proven_absent"
        and isinstance(source.get("hybrid_descendant_cleanup"), Mapping)
        and source["hybrid_descendant_cleanup"].get("status") == "verified"
        and isinstance(source.get("hybrid_process_scope_cleanup"), Mapping)
        and _scope_is_clean(source["hybrid_process_scope_cleanup"])
    )


def _vista_source_is_clean(source: object) -> bool:
    return (
        isinstance(source, Mapping)
        and source.get("release_status") == "verified"
        and source.get("provider_processes_after") == []
        and source.get("helper_processes_after") == []
        and source.get("orphan_descendant_pids") == []
        and source.get("active_listeners_after") == []
        and source.get("lease_files_after") == []
        and isinstance(source.get("source_cleanup_evidence"), Mapping)
        and source["source_cleanup_evidence"].get("status") == "verified"
    )


def _cleanup_receipt(
    provider: str,
    *,
    outer: Mapping[str, object],
    source_clean: bool,
    source: object = None,
) -> dict[str, object]:
    provider_after = list(outer.get("member_identities_after") or [])
    helper_after: list[object] = []
    orphan_pids = list(outer.get("member_pids_after") or [])
    listeners = list(outer.get("active_listeners_after") or [])
    lease_files = [str(outer["pid_file_after"])] if outer.get("pid_file_after") else []
    if isinstance(source, Mapping):
        provider_after.extend(list(source.get("provider_processes_after") or []))
        helper_after.extend(list(source.get("helper_processes_after") or []))
        orphan_pids.extend(list(source.get("orphan_descendant_pids") or []))
        listeners.extend(list(source.get("active_listeners_after") or []))
        lease_files.extend(str(path) for path in source.get("lease_files_after") or [])
    elif isinstance(source, list):
        for item in source:
            if not isinstance(item, Mapping):
                continue
            provider_after.extend(list(item.get("provider_processes_after") or []))
            helper_after.extend(list(item.get("orphan_descendant_identities") or []))
            orphan_pids.extend(
                identity["pid"]
                for identity in item.get("orphan_descendant_identities") or []
                if isinstance(identity, Mapping) and isinstance(identity.get("pid"), int)
            )
            listeners.extend(list(item.get("active_listeners_after") or []))
            lease_files.extend(str(path) for path in item.get("lease_files_after") or [])
    verified = (
        source_clean
        and _scope_is_clean(outer)
        and not provider_after
        and not helper_after
        and not orphan_pids
        and not listeners
        and not lease_files
    )
    return {
        "contract_version": "simple_native_provider_cleanup_v1",
        "provider": provider,
        "verified": verified,
        "cleanup_status": "verified" if verified else "failed",
        "owned_processes": [*provider_after, *helper_after],
        "provider_processes_after": provider_after,
        "helper_processes_after": helper_after,
        "orphan_descendant_pids": orphan_pids,
        "active_listeners_after": listeners,
        "lease_files_after": lease_files,
    }


def verify_cleanup_receipt(receipt: Mapping[str, object]) -> bool:
    return receipt.get("verified") is True and receipt.get("owned_processes") == []


def cancel_owned_processes(lifecycle: object) -> Mapping[str, object]:
    stop = getattr(lifecycle, "stop_owned", None)
    if not callable(stop):
        raise ValueError("lifecycle cannot prove owned-process cleanup")
    receipt = stop()
    if not isinstance(receipt, Mapping) or not verify_cleanup_receipt(receipt):
        raise ValueError("owned process cleanup is not verified")
    return receipt
