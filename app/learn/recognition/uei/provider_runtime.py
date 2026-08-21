"""Sealed, review-only Shadow execution over trusted local provider adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import os
import re
import stat
from threading import RLock
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
from app.learn.recognition.uei.contracts import UEIOuterBoundaryError, UEIProjectionFailure, UEIValidationError
from app.learn.recognition.uei.projections import make_source_item
from app.learn.recognition.uei.provider_adapters import (
    AdapterFailure,
    NormalizedProviderItem,
    NormalizedScreenParseOutput,
    ProviderRunBudget,
    RestrictedCaptureLease,
    TrustedProviderAdapterRegistry,
)
from app.learn.recognition.uei.registry import resolve_projection_context, resolve_requested_profile
from app.learn.recognition.uei.store import UEIObjectStore


_SECRET_PATTERN = re.compile(r"(?i)(password|cookie|authorization|bearer|api[ _-]?key|access[ _-]?key|token|[a-z]:\\users\\|[\w.+-]+@[\w.-]+\.[a-z]{2,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----)")


def _outer(name: str) -> UEIOuterBoundaryError:
    return UEIOuterBoundaryError(f"{name}: invalid or unresolved")


class ShadowProviderRuntime:
    """Run exactly one trusted Shadow adapter and persist only sealed safe records."""

    def __init__(
        self, *, store: UEIObjectStore, registry: TrustedProviderAdapterRegistry,
        trusted_profiles: dict[tuple[str, str], tuple[dict[str, str], dict[str, str]]],
        budget: ProviderRunBudget,
    ) -> None:
        if not isinstance(store, UEIObjectStore) or not isinstance(registry, TrustedProviderAdapterRegistry):
            raise UEIValidationError("runtime_invalid_configuration")
        self._store = store
        self._registry = registry
        self._budget = budget
        self._trusted_profiles = {
            key: (deepcopy(value[0]), deepcopy(value[1]))
            for key, value in trusted_profiles.items()
            if isinstance(key, tuple) and len(key) == 2 and isinstance(value, tuple) and len(value) == 2
        }
        if len(self._trusted_profiles) != len(trusted_profiles):
            raise UEIValidationError("runtime_invalid_configuration")
        self._lock = RLock()
        self._states: dict[str, dict[str, object]] = {}

    def invoke(
        self, *, request_ref: dict[str, str], capture_lease: RestrictedCaptureLease,
    ) -> dict[str, object]:
        context = resolve_projection_context(store=self._store, request_ref=request_ref)
        self._verify_lease(context=context, request_ref=request_ref, lease=capture_lease)
        provider_id, profile_id, mode = self._select_requested_profile(context)
        invocation_id = self._invocation_id(request_ref, capture_lease.capture_lineage_ref, provider_id, profile_id)

        binding = self._trusted_profiles.get((provider_id, profile_id))
        adapter = self._registry.resolve(provider_id=provider_id, profile_id=profile_id)
        if mode != "Shadow" or binding is None or adapter is None:
            return self._persist_rejection(
                context=context, provider_id=provider_id, profile_id=profile_id, invocation_id=invocation_id,
            )
        profile = resolve_requested_profile(
            context=context, registration_ref=binding[0], manifest_ref=binding[1],
            provider_id=provider_id, profile_id=profile_id,
        )
        if profile.get("resolved") is not True:
            return self._persist_rejection(
                context=context, provider_id=provider_id, profile_id=profile_id, invocation_id=invocation_id,
            )
        if (getattr(adapter, "provider_id", None) != provider_id
                or getattr(adapter, "profile_id", None) != profile_id
                or getattr(adapter, "provider_version", None) != profile.get("manifest", {}).get("provider_version")):
            return self._persist_rejection(
                context=context, provider_id=provider_id, profile_id=profile_id, invocation_id=invocation_id,
            )
        invocation_id = self._invocation_id(
            request_ref, capture_lease.capture_lineage_ref, provider_id, profile_id,
            registration_ref=profile.get("registration_ref"), manifest_ref=profile.get("manifest_ref"),
            provider_version=getattr(adapter, "provider_version", None),
        )
        recovered = self._claim_or_recover(invocation_id)
        if recovered is not None:
            return recovered
        with self._lock:
            if invocation_id in self._states:
                raise _outer("invocation")
            self._states[invocation_id] = {"state": "in_progress"}
        try:
            budget = self._effective_budget(profile)
            output = adapter.invoke(capture=capture_lease, budget=budget, invocation_id=invocation_id)
            reply = self._persist_success(
                context=context, profile=profile, adapter=adapter, output=output, invocation_id=invocation_id, budget=budget,
            )
        except AdapterFailure as failure:
            if failure.disposition == "rejected":
                reply = self._persist_rejection(
                    context=context, provider_id=provider_id, profile_id=profile_id, invocation_id=invocation_id,
                    reason_class=failure.reason_class, retryable=failure.retryable, duration_ms=failure.duration_ms,
                    resource_units=failure.resource_units, output_item_count=failure.output_item_count,
                    cleanup_status=failure.cleanup_status,
                )
            else:
                reply = self._persist_failure(
                    context=context, profile=profile, provider_id=provider_id, profile_id=profile_id,
                    invocation_id=invocation_id, reason_class=failure.reason_class, retryable=failure.retryable,
                    duration_ms=failure.duration_ms, resource_units=failure.resource_units,
                    output_item_count=failure.output_item_count, cleanup_status=failure.cleanup_status,
                )
        except Exception:
            reply = self._persist_failure(
                context=context, profile=profile, provider_id=provider_id, profile_id=profile_id,
                invocation_id=invocation_id, reason_class="runtime_provider_failed", retryable=False,
                duration_ms=0, resource_units=0, output_item_count=0, cleanup_status="failed",
            )
        with self._lock:
            self._states[invocation_id] = {"state": "complete", "reply": deepcopy(reply)}
        self._complete_claim(invocation_id, reply)
        return reply

    def _select_requested_profile(self, context: dict[str, object]) -> tuple[str, str, str]:
        request = context.get("request")
        profiles = request.get("requested_profiles") if isinstance(request, dict) else None
        if not isinstance(profiles, list) or len(profiles) != 1 or not isinstance(profiles[0], dict):
            raise _outer("requested_profiles")
        profile = profiles[0]
        provider_id, profile_id, mode = profile.get("provider_id"), profile.get("profile_id"), profile.get("mode")
        if not all(isinstance(value, str) for value in (provider_id, profile_id, mode)):
            raise _outer("requested_profiles")
        return provider_id, profile_id, mode

    def _effective_budget(self, profile: dict[str, object]) -> ProviderRunBudget:
        limits = profile.get("safe_payload_limits")
        if not isinstance(limits, dict):
            raise UEIProjectionFailure("projection_failed")
        output_bytes, items, string_chars = (
            limits.get("max_json_bytes"), limits.get("max_array_items"), limits.get("max_string_chars"),
        )
        if not all(isinstance(value, int) and value > 0 for value in (output_bytes, items, string_chars)):
            raise UEIProjectionFailure("projection_failed")
        return ProviderRunBudget(
            timeout_ms=self._budget.timeout_ms, max_output_bytes=min(self._budget.max_output_bytes, output_bytes),
            max_element_count=min(self._budget.max_element_count, items),
            max_string_length=min(self._budget.max_string_length, string_chars), resource_group=self._budget.resource_group,
        )

    def _verify_lease(
        self, *, context: dict[str, object], request_ref: dict[str, str], lease: RestrictedCaptureLease,
    ) -> None:
        if not isinstance(lease, RestrictedCaptureLease) or not isinstance(lease.local_path, type(self._store.root)):
            raise _outer("capture_lease")
        expected = (
            ("request_ref", request_ref), ("capture_lineage_ref", context.get("capture_lineage_ref")),
            ("artifact_ref", context.get("artifact_ref")),
        )
        for name, value in expected:
            if getattr(lease, name) != value:
                raise _outer(name)
        lineage = context.get("capture_lineage")
        if not isinstance(lineage, dict) or lease.capture_id != lineage.get("capture_id"):
            raise _outer("capture_id")
        if lease.artifact_sha256 != context.get("artifact_sha256") or lease.image_size != context.get("image_size"):
            raise _outer("capture_lease")
        artifact = context.get("artifact")
        if not isinstance(artifact, dict) or not isinstance(artifact.get("byte_length"), int):
            raise _outer("artifact")
        try:
            raw = lease.local_path.read_bytes()
            with Image.open(lease.local_path) as image:
                image.verify()
            with Image.open(lease.local_path) as image:
                dimensions = {"width": image.width, "height": image.height}
        except (OSError, UnidentifiedImageError, SyntaxError):
            raise _outer("capture_artifact") from None
        if (len(raw) != artifact["byte_length"] or sha256(raw).hexdigest() != context["artifact_sha256"]
                or dimensions != context["image_size"]):
            raise _outer("capture_artifact")

    @staticmethod
    def _invocation_id(
        request_ref: dict[str, str], capture_ref: dict[str, str], provider_id: str, profile_id: str,
        *, registration_ref: object | None = None, manifest_ref: object | None = None,
        provider_version: object | None = None,
    ) -> str:
        return "invocation/" + content_sha256({
            "request_ref": request_ref, "capture_lineage_ref": capture_ref,
            "registration_ref": registration_ref, "manifest_ref": manifest_ref,
            "provider_id": provider_id, "profile_id": profile_id, "provider_version": provider_version,
        })

    def _claim_or_recover(self, invocation_id: str) -> dict[str, object] | None:
        """原子认领一次调用；遗留进行中记录一律拒绝重跑。"""
        path = self._claim_path(invocation_id)
        payload = {"state": "in_progress", "invocation_id": invocation_id}
        try:
            descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raise _outer("invocation") from None
            if not isinstance(existing, dict) or existing.get("invocation_id") != invocation_id:
                raise _outer("invocation")
            if existing.get("state") != "complete" or not isinstance(existing.get("reply"), dict):
                raise _outer("invocation")
            reply = deepcopy(existing["reply"])
            self._verify_completed(reply)
            return reply
        except OSError:
            raise _outer("invocation") from None
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            raise _outer("invocation") from None
        return None

    def _complete_claim(self, invocation_id: str, reply: dict[str, object]) -> None:
        path = self._claim_path(invocation_id)
        temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump({"state": "complete", "invocation_id": invocation_id, "reply": reply}, handle,
                          ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError:
            raise _outer("invocation") from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _claim_path(self, invocation_id: str):
        digest = invocation_id.rsplit("/", 1)[-1]
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise _outer("invocation")
        root = self._store.root / ".shadow-runtime-claims"
        try:
            root.mkdir(exist_ok=True)
            metadata = os.lstat(root)
        except OSError:
            raise _outer("invocation") from None
        if stat.S_ISLNK(metadata.st_mode) or not root.is_dir():
            raise _outer("invocation")
        path = root / f"{digest}.json"
        if path.parent != root or (path.exists() and path.is_symlink()):
            raise _outer("invocation")
        return path

    def _persist_rejection(
        self, *, context: dict[str, object], provider_id: str, profile_id: str, invocation_id: str,
        reason_class: str = "policy_rejected", retryable: bool = False, duration_ms: int = 0,
        resource_units: int = 0, output_item_count: int = 0, cleanup_status: str = "not_required",
    ) -> dict[str, object]:
        receipt_ref = self._store.put(seal_immutable(self._receipt(
            context=context, provider_id=provider_id, profile_id=profile_id, invocation_id=invocation_id,
            status="rejected", reason_class=reason_class, retryable=retryable, duration_ms=duration_ms,
            resource_units=resource_units, output_item_count=output_item_count, cleanup_status=cleanup_status,
        )))
        reply: dict[str, object] = {"invocation_id": invocation_id, "result_ref": None, "error_ref": None,
                                    "receipt_ref": receipt_ref}
        with self._lock:
            self._states[invocation_id] = {"state": "complete", "reply": deepcopy(reply)}
        return reply

    def _persist_success(
        self, *, context: dict[str, object], profile: dict[str, object], adapter: object,
        output: object, invocation_id: str, budget: ProviderRunBudget,
    ) -> dict[str, object]:
        if not isinstance(output, NormalizedScreenParseOutput):
            raise UEIProjectionFailure("projection_failed")
        if (not isinstance(output.items, tuple) or len(output.items) > budget.max_element_count
                or not isinstance(output.duration_ms, int) or not 0 <= output.duration_ms <= 86400000
                or not isinstance(output.resource_units, int) or not 0 <= output.resource_units <= 1048576):
            raise UEIProjectionFailure("projection_failed")
        provider_id, profile_id = str(getattr(adapter, "provider_id")), str(getattr(adapter, "profile_id"))
        sanitized = [self._safe_item(item, context, provider_id, profile_id, index, budget) for index, item in enumerate(output.items)]
        items = [value[0] for value in sanitized]
        redacted_fields = sum(value[1] for value in sanitized)
        redacted_items = sum(1 for value in sanitized if value[1])
        result = self._result(
            context=context, profile=profile, provider_id=provider_id, profile_id=profile_id,
            provider_version=str(getattr(adapter, "provider_version")), status="success", items=items, error_ref=None,
            invocation_id=invocation_id, redaction_summary={"redacted_item_count": redacted_items,
                "redacted_field_count": redacted_fields, "secret_detected": redacted_fields > 0,
                "sensitive_categories": ["credential"] if redacted_fields else []},
        )
        result_ref = self._store.put(seal_immutable(result))
        receipt_ref = self._store.put(seal_immutable(self._receipt(
            context=context, provider_id=provider_id, profile_id=profile_id, invocation_id=invocation_id,
            status="succeeded", reason_class="none", retryable=False, duration_ms=output.duration_ms,
            resource_units=output.resource_units, output_item_count=len(items), cleanup_status="clean", result_ref=result_ref,
        )))
        return {"invocation_id": invocation_id, "result_ref": result_ref, "error_ref": None, "receipt_ref": receipt_ref}

    def _safe_item(
        self, item: object, context: dict[str, object], provider_id: str, profile_id: str, index: int,
        budget: ProviderRunBudget,
    ) -> tuple[dict[str, object], int]:
        if not isinstance(item, NormalizedProviderItem):
            raise UEIProjectionFailure("projection_failed")
        if (item.safe_text is not None and (not isinstance(item.safe_text, str) or len(item.safe_text) > budget.max_string_length)
                or item.safe_role is not None and (not isinstance(item.safe_role, str) or len(item.safe_role) > budget.max_string_length)
                or not isinstance(item.safe_states, tuple) or any(not isinstance(value, str) or len(value) > budget.max_string_length for value in item.safe_states)
                or item.kind not in {"element", "text", "role", "state", "icon", "structure"}
                or item.source_item_id is not None and (not isinstance(item.source_item_id, str) or not item.source_item_id or len(item.source_item_id) > 512)):
            raise UEIProjectionFailure("projection_failed")
        fields = [item.safe_text, item.safe_role, *item.safe_states]
        redacted = sum(1 for value in fields if isinstance(value, str) and _SECRET_PATTERN.search(value))
        safe_text = "[redacted]" if isinstance(item.safe_text, str) and _SECRET_PATTERN.search(item.safe_text) else item.safe_text
        safe_role = "[redacted]" if isinstance(item.safe_role, str) and _SECRET_PATTERN.search(item.safe_role) else item.safe_role
        safe_states = ["[redacted]" if _SECRET_PATTERN.search(value) else value for value in item.safe_states]
        return make_source_item(
            provider_id=provider_id, profile_id=profile_id, capture_lineage_ref=context["capture_lineage_ref"],
            source_index=index, source_item_id=item.source_item_id, source_id_origin="provider", kind=item.kind,
            safe_text=safe_text, safe_role=safe_role, safe_states=safe_states,
            source_bbox=None if item.source_bbox is None else list(item.source_bbox),
            source_coordinate_space=item.source_coordinate_space,
            capture_bbox=None if item.source_bbox is None or item.source_coordinate_space != "capture_pixel_xyxy" else list(item.source_bbox),
            coordinate_transform_ref=None, opaque_attributes={}, provider_confidence=item.provider_confidence,
        ), redacted

    def _persist_failure(
        self, *, context: dict[str, object], profile: dict[str, object], provider_id: str,
        profile_id: str, invocation_id: str, reason_class: str, retryable: bool, duration_ms: int,
        resource_units: int, output_item_count: int, cleanup_status: str,
    ) -> dict[str, object]:
        error = {
            "contract_version": "provider_error_v1", "error_id": "error/" + invocation_id.rsplit("/", 1)[1],
            "request_ref": context["request_ref"], "requested_provider_id": provider_id,
            "requested_profile_id": profile_id, "registration_resolution": profile["registration_resolution"],
            "manifest_resolution": profile["manifest_resolution"], "registration_ref": profile["registration_ref"],
            "manifest_ref": profile["manifest_ref"], "provider_id": provider_id, "profile_id": profile_id,
            "stage": "projection", "code": "projection_failed", "retryable": retryable,
            "message": "Provider execution failed.", "safe_details": {"reason_class": reason_class},
            "capture_lineage_ref": context["capture_lineage_ref"],
        }
        error_ref = self._store.put(seal_immutable(error))
        result_ref = self._store.put(seal_immutable(self._result(
            context=context, profile=profile, provider_id=provider_id, profile_id=profile_id,
            provider_version="unavailable", status="failed", items=[], error_ref=error_ref, invocation_id=invocation_id,
        )))
        receipt_ref = self._store.put(seal_immutable(self._receipt(
            context=context, provider_id=provider_id, profile_id=profile_id, invocation_id=invocation_id,
            status="failed", reason_class=reason_class, retryable=retryable, duration_ms=duration_ms,
            resource_units=resource_units, output_item_count=output_item_count, cleanup_status=cleanup_status, result_ref=result_ref, error_ref=error_ref,
        )))
        return {"invocation_id": invocation_id, "result_ref": result_ref, "error_ref": error_ref, "receipt_ref": receipt_ref}

    @staticmethod
    def _result(
        *, context: dict[str, object], profile: dict[str, object], provider_id: str, profile_id: str,
        provider_version: str, status: str, items: list[dict[str, object]], error_ref: dict[str, str] | None,
        invocation_id: str, redaction_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "contract_version": "provider_safe_result_v1", "result_id": "result/" + invocation_id.rsplit("/", 1)[1],
            "request_ref": context["request_ref"], "requested_provider_id": provider_id,
            "requested_profile_id": profile_id, "registration_resolution": profile["registration_resolution"],
            "manifest_resolution": profile["manifest_resolution"], "registration_ref": profile["registration_ref"],
            "manifest_ref": profile["manifest_ref"], "provider_id": provider_id, "profile_id": profile_id,
            "provider_version": provider_version, "capture_lineage_ref": context["capture_lineage_ref"],
            "status": status, "review_only": True, "items": items,
            "redaction_summary": redaction_summary or {"redacted_item_count": 0, "redacted_field_count": 0,
                                  "secret_detected": False, "sensitive_categories": []},
        }
        if error_ref is not None:
            value["error_ref"] = error_ref
        return value

    @staticmethod
    def _receipt(
        *, context: dict[str, object], provider_id: str, profile_id: str, invocation_id: str,
        status: str, reason_class: str, retryable: bool, duration_ms: int, resource_units: int,
        output_item_count: int, cleanup_status: str, result_ref: dict[str, str] | None = None,
        error_ref: dict[str, str] | None = None,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "contract_version": "provider_runtime_receipt_v1",
            "receipt_id": "receipt/" + invocation_id.rsplit("/", 1)[1], "request_ref": context["request_ref"],
            "capture_lineage_ref": context["capture_lineage_ref"], "artifact_ref": context["artifact_ref"],
            "provider_id": provider_id, "profile_id": profile_id, "mode": "Shadow", "status": status,
            "reason_class": reason_class, "retryable": retryable,
            "metrics": {"duration_ms": duration_ms, "resource_units": resource_units,
                        "output_item_count": output_item_count}, "cleanup_status": cleanup_status,
        }
        if result_ref is not None:
            value["result_ref"] = result_ref
        if error_ref is not None:
            value["error_ref"] = error_ref
        return value

    def _verify_completed(self, reply: dict[str, object]) -> None:
        receipt_ref = reply.get("receipt_ref")
        if not isinstance(receipt_ref, dict):
            raise _outer("invocation")
        self._store.get(receipt_ref, contract_version="provider_runtime_receipt_v1")
        for name, contract in (("result_ref", "provider_safe_result_v1"), ("error_ref", "provider_error_v1")):
            reference = reply.get(name)
            if reference is not None:
                if not isinstance(reference, dict):
                    raise _outer("invocation")
                self._store.get(reference, contract_version=contract)
