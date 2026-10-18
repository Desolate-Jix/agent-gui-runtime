"""原生宿主持有的 canonical 单步执行控制面与严格客户端。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from threading import Condition, RLock
import time
from typing import Any
from urllib.parse import urlsplit

import httpx


_CONFIRMATION = re.compile(r"^grounded-confirmation\.[0-9a-f]{64}$")
_RESPONSE_KEYS = {
    "contract_version", "confirmation_id", "kind", "payload",
    "artifact_is_authorization",
}


class NativeSingleStepError(RuntimeError):
    def __init__(
        self, code: str, message: str, *, result_unknown: bool = False
    ) -> None:
        self.code = code
        self.message = message
        self.result_unknown = result_unknown
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GroundedRuntimeAttachment:
    confirmation_id: str
    session_id: str
    observation_id: str
    intent_id: str
    workflow_id: str | None
    asset_id: str | None
    target_window_handle: int
    target_process_id: int
    source_kind: str = "reviewed_workflow"
    source_sha256: str | None = None
    destination_window_handle: int | None = None
    destination_process_id: int | None = None
    preview_sha256: str | None = None
    automatic_safety_interception: bool | None = None

    def __post_init__(self) -> None:
        if self.source_kind == 'fresh_learning':
            if type(self.automatic_safety_interception) is not bool:
                raise ValueError('fresh attachment requires a frozen safety mode')
        elif self.automatic_safety_interception is not None:
            raise ValueError('non-fresh attachment cannot override safety mode')
        if self.source_kind == 'taskbar_activation':
            if (type(self.destination_window_handle) is not int or self.destination_window_handle <= 0
                    or type(self.destination_process_id) is not int or self.destination_process_id <= 0
                    or not isinstance(self.preview_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', self.preview_sha256) is None):
                raise ValueError('taskbar attachment destination is invalid')
        elif any(value is not None for value in (self.destination_window_handle, self.destination_process_id, self.preview_sha256)):
            raise ValueError('non-taskbar attachment carries taskbar fields')
        if self.source_kind in {"fresh_learning", "taskbar_activation"}:
            if (self.workflow_id is not None or self.asset_id is not None
                    or not isinstance(self.source_sha256, str)
                    or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None):
                raise ValueError("fresh attachment cannot contain reviewed lineage")
        elif self.source_kind == "reviewed_workflow":
            if (self.source_sha256 is not None
                    or not isinstance(self.workflow_id, str) or not self.workflow_id
                    or not isinstance(self.asset_id, str) or not self.asset_id):
                raise ValueError("reviewed attachment cannot contain fresh lineage")
        else:
            raise ValueError("attachment source family is invalid")


class NativeSingleStepController:
    """持有一个 exact local Runtime owner；不实现第二套执行引擎。"""

    def __init__(self) -> None:
        self._condition = Condition(RLock())
        self._attachment: GroundedRuntimeAttachment | None = None
        self._callsite: Any | None = None
        self._accepting = False
        self._inflight = 0
        self._execution_started = False
        self._last_envelope: dict[str, Any] | None = None

    @property
    def attached(self) -> bool:
        with self._condition:
            return self._attachment is not None

    def attachment_snapshot(self) -> GroundedRuntimeAttachment | None:
        with self._condition:
            return self._attachment

    def attach(self, callsite: Any, *, confirmation_id: str) -> GroundedRuntimeAttachment:
        _confirmation_id(confirmation_id)
        getter = getattr(callsite, "get_local_grounded_confirmation", None)
        if not callable(getter):
            raise NativeSingleStepError(
                "runtime_unavailable", "grounded runtime owner query is unavailable"
            )
        try:
            claim = getter(confirmation_id=confirmation_id)
            from app.desktop_review.taskbar_activation import TaskbarActivationClaim
            from app.agent.fresh_learning_action_contracts import RuntimeFreshLearningClaimSnapshot

            if type(claim) is TaskbarActivationClaim:
                attachment = _taskbar_attachment(claim)
            elif type(claim) is RuntimeFreshLearningClaimSnapshot:
                attachment = _fresh_attachment(claim)
            else:
                grounded = claim.grounded_confirmation
                preview = grounded.preview.to_dict()
                attachment = GroundedRuntimeAttachment(
                    confirmation_id=grounded.confirmation_id,
                    session_id=claim.observation.session_id,
                    observation_id=claim.observation.observation_id,
                    intent_id=claim.intent.intent_id,
                    workflow_id=claim.observation.workflow.workflow_id,
                    asset_id=claim.observation.workflow.asset_id,
                    target_window_handle=claim.server_binding.target_window_handle,
                    target_process_id=preview["target_process_id"],
                )
        except NativeSingleStepError:
            raise
        except Exception:
            raise NativeSingleStepError(
                "runtime_owner_unavailable",
                "grounded runtime owner could not be verified",
            ) from None
        if attachment.confirmation_id != confirmation_id:
            raise NativeSingleStepError(
                "runtime_owner_mismatch", "grounded runtime owner identity differs"
            )
        with self._condition:
            if self._attachment is not None:
                if self._callsite is callsite and self._attachment == attachment:
                    return attachment
                raise NativeSingleStepError(
                    "runtime_already_attached", "another grounded runtime owner is attached"
                )
            self._attachment = attachment
            self._callsite = callsite
            self._execution_started = False
            self._last_envelope = None
            return attachment

    def set_accepting(self, value: bool) -> None:
        if type(value) is not bool:
            raise TypeError("accepting must be a bool")
        with self._condition:
            self._accepting = value
            if not value:
                self._condition.notify_all()

    def execute_server(self, *, confirmation_id: str) -> dict[str, Any]:
        _confirmation_id(confirmation_id)
        with self._condition:
            attachment, callsite = self._attachment, self._callsite
            if not self._accepting:
                raise NativeSingleStepError(
                    "host_not_ready", "single-step execution is not accepting requests"
                )
            if attachment is None or callsite is None:
                raise NativeSingleStepError(
                    "runtime_not_attached", "no grounded runtime owner is attached"
                )
            if confirmation_id != attachment.confirmation_id:
                raise NativeSingleStepError(
                    "confirmation_not_attached",
                    "the grounded confirmation is not attached to this host",
                )
            if self._inflight:
                raise NativeSingleStepError(
                    "execution_in_progress",
                    "the grounded single-step request is already in progress",
                )
            self._inflight += 1
            self._execution_started = True
        try:
            try:
                result = callsite.consume_grounded_confirmation(
                    confirmation_id=confirmation_id
                )
            except Exception:
                raise NativeSingleStepError(
                    "runtime_consume_failed",
                    "grounded single-step result is unknown",
                    result_unknown=True,
                ) from None
            envelope = _runtime_envelope(result, confirmation_id=confirmation_id)
            _validate_attachment_result(envelope, attachment)
            with self._condition:
                self._last_envelope = deepcopy(envelope)
            return envelope
        finally:
            with self._condition:
                self._inflight -= 1
                self._condition.notify_all()

    def wait_for_drain(self, timeout: float) -> None:
        wait = _timeout(timeout)
        deadline = time.monotonic() + wait
        with self._condition:
            while self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NativeSingleStepError(
                        "shutdown_timeout",
                        "single-step execution is still draining",
                        result_unknown=True,
                    )
                self._condition.wait(remaining)

    def cleanup_attachment(self, *, confirmation_id: str | None = None) -> None:
        with self._condition:
            if self._inflight:
                raise NativeSingleStepError(
                    "runtime_cleanup_pending",
                    "single-step execution is still active",
                    result_unknown=True,
                )
            attachment, callsite = self._attachment, self._callsite
            started = self._execution_started
            last = deepcopy(self._last_envelope)
            if confirmation_id is not None:
                identity = _confirmation_id(confirmation_id)
                if attachment is None or attachment.confirmation_id != identity:
                    raise NativeSingleStepError(
                        "confirmation_not_attached",
                        "the grounded confirmation is not attached to this host",
                    )
        if attachment is None or callsite is None:
            return
        try:
            if not started:
                cancelled = callsite.cancel_grounded_review(
                    session_id=attachment.session_id
                )
                _validate_cancelled_snapshot(cancelled, attachment=attachment)
            elif last is not None and last.get("kind") == "receipt":
                replay = callsite.consume_grounded_confirmation(
                    confirmation_id=attachment.confirmation_id
                )
                checked = _runtime_envelope(
                    replay, confirmation_id=attachment.confirmation_id
                )
                _validate_attachment_result(checked, attachment)
                if checked.get("kind") != "receipt":
                    raise NativeSingleStepError(
                        "runtime_cleanup_pending",
                        "grounded terminal cleanup is incomplete",
                        result_unknown=True,
                    )
            elif (
                last is not None
                and last.get("kind") == "decision"
                and last.get("payload", {}).get("status") == "REJECTED"
            ):
                reason = last["payload"].get("reason_code")
                if reason == "grounded_confirmation_stale":
                    pass
                elif reason == "grounded_confirmation_not_approved":
                    cancelled = callsite.cancel_grounded_review(
                        session_id=attachment.session_id
                    )
                    _validate_cancelled_snapshot(cancelled, attachment=attachment)
                else:
                    raise NativeSingleStepError(
                        "runtime_cleanup_pending",
                        "grounded rejection does not prove terminal cleanup",
                        result_unknown=False,
                    )
            elif (attachment.source_kind == "fresh_learning"
                    and last is not None and last.get("kind") == "decision"
                    and last.get("payload", {}).get("status") == "RECOVERY_REQUIRED"
                    and last["payload"].get("reason_code") in {
                        "fresh_dispatch_preparation_failed", "fresh_dispatch_indeterminate"}):
                # 只释放 exact 本地 owner；未知消费/派发仍保持 recovery_required。
                released = callsite.release_local_fresh_recovery(confirmation_id=attachment.confirmation_id)
                _validate_fresh_recovery_release(released, attachment=attachment)
            else:
                raise NativeSingleStepError(
                    "runtime_cleanup_pending",
                    "grounded consume state requires explicit recovery",
                    result_unknown=True,
                )
        except NativeSingleStepError:
            raise
        except Exception:
            raise NativeSingleStepError(
                "runtime_cleanup_pending",
                "grounded runtime cleanup could not be verified",
                result_unknown=started,
            ) from None
        with self._condition:
            if self._attachment == attachment and self._callsite is callsite:
                self._attachment = None
                self._callsite = None
                self._execution_started = False
                self._last_envelope = None


class OwnedSingleStepClient:
    """只向宿主自己的 loopback canonical route 发一次请求。"""

    def __init__(self, *, base_url: str, token: str, confirmation_id: str) -> None:
        self._base_url = _base_url(base_url)
        if not isinstance(token, str) or not token or not token.isascii():
            raise NativeSingleStepError("invalid_client", "execution token is invalid")
        self._token = token
        self._confirmation_id = _confirmation_id(confirmation_id)
        self._condition = Condition(RLock())
        self._live = True
        self._inflight = 0

    def __repr__(self) -> str:
        return "OwnedSingleStepClient(base_url=<owned>, token=<redacted>)"

    def execute(self, *, confirmation_id: str) -> dict[str, Any]:
        identity = _confirmation_id(confirmation_id)
        if identity != self._confirmation_id:
            raise NativeSingleStepError(
                "confirmation_not_attached", "confirmation does not match owned client"
            )
        with self._condition:
            if not self._live:
                raise NativeSingleStepError(
                    "single_step_client_revoked",
                    "owned single-step client is no longer active",
                )
            self._inflight += 1
            base_url, token = self._base_url, self._token
        try:
            try:
                with httpx.Client(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0),
                ) as client:
                    response = client.post(
                        base_url + "/action/execute_recognition_plan",
                        headers={
                            "authorization": f"Bearer {token}",
                            "content-type": "application/json",
                        },
                        json={"confirmation_id": identity},
                    )
            except httpx.HTTPError:
                raise NativeSingleStepError(
                    "single_step_result_unknown",
                    "single-step HTTP result is unknown",
                    result_unknown=True,
                ) from None
            try:
                payload = json.loads(
                    response.content,
                    object_pairs_hook=_unique_object,
                    parse_constant=_invalid_constant,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
                raise NativeSingleStepError(
                    "invalid_response", "single-step host returned invalid JSON",
                    result_unknown=True,
                ) from None
            if response.status_code != 200:
                _raise_http_error(payload)
            try:
                return validate_single_step_response(
                    payload, confirmation_id=identity
                )
            except RecursionError:
                raise NativeSingleStepError(
                    "invalid_response",
                    "single-step host returned an invalid response",
                    result_unknown=True,
                ) from None
        finally:
            with self._condition:
                self._inflight -= 1
                self._condition.notify_all()

    def invalidate(self) -> None:
        with self._condition:
            self._live = False
            self._condition.notify_all()

    def wait_for_drain(self, timeout: float) -> None:
        wait = _timeout(timeout)
        deadline = time.monotonic() + wait
        with self._condition:
            while self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NativeSingleStepError(
                        "shutdown_timeout",
                        "owned single-step client is still draining",
                        result_unknown=True,
                    )
                self._condition.wait(remaining)


def validate_single_step_response(
    value: Any, *, confirmation_id: str
) -> dict[str, Any]:
    identity = _confirmation_id(confirmation_id)
    if (
        not isinstance(value, dict)
        or set(value) != _RESPONSE_KEYS
        or value.get("contract_version") != "native_single_step_response_v1"
        or value.get("confirmation_id") != identity
        or value.get("artifact_is_authorization") is not False
        or not isinstance(value.get("kind"), str)
        or value.get("kind") not in {"receipt", "decision"}
        or not isinstance(value.get("payload"), dict)
    ):
        raise NativeSingleStepError(
            "invalid_response", "single-step host returned an invalid response",
            result_unknown=True,
        )
    payload = value["payload"]
    if value["kind"] == "receipt":
        try:
            from app.agent.runtime_contracts import RuntimeResultReceiptV1
            from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
            from app.desktop_review.taskbar_activation import TaskbarActivationReceipt

            if payload.get("contract_version") == "taskbar_activation_receipt_v1":
                checked = TaskbarActivationReceipt.model_validate(payload)
                if checked.confirmation_id != identity:
                    raise ValueError("taskbar receipt confirmation differs")
            elif payload.get("contract_version") in {'runtime_fresh_result_receipt_v1', 'runtime_fresh_result_receipt_v2'}:
                checked = RuntimeFreshResultReceipt.from_dict(payload)
                if checked.evidence.confirmation_id != identity:
                    raise ValueError("fresh receipt confirmation differs")
            else:
                checked = RuntimeResultReceiptV1.model_validate(payload)
            if checked.model_dump(mode="json") != payload:
                raise ValueError("receipt was normalized")
        except (ImportError, TypeError, ValueError, RecursionError):
            raise NativeSingleStepError(
                "invalid_response", "single-step receipt is invalid",
                result_unknown=True,
            ) from None
    elif (
        set(payload) != {"status", "reason_code", "confirmation_id"}
        or not isinstance(payload.get("status"), str)
        or payload.get("status") not in {"REJECTED", "RECOVERY_REQUIRED"}
        or not isinstance(payload.get("reason_code"), str)
        or not payload["reason_code"]
        or payload.get("confirmation_id") != identity
    ):
        raise NativeSingleStepError(
            "invalid_response", "single-step decision is invalid",
            result_unknown=True,
        )
    return deepcopy(value)


def _runtime_envelope(result: Any, *, confirmation_id: str) -> dict[str, Any]:
    try:
        from app.agent.runtime_contracts import RuntimeResultReceiptV1
        from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
        from app.desktop_review.taskbar_activation import TaskbarActivationReceipt

        if isinstance(result, (RuntimeResultReceiptV1, RuntimeFreshResultReceipt, TaskbarActivationReceipt)):
            kind = "receipt"
            payload = result.model_dump(mode="json")
        else:
            status = getattr(result, "status", None)
            reason = getattr(result, "reason_code", None)
            returned_id = getattr(result, "confirmation_id", None)
            if status not in {"REJECTED", "RECOVERY_REQUIRED"}:
                raise ValueError("unsupported decision")
            if returned_id not in {None, confirmation_id}:
                raise ValueError("decision identity mismatch")
            kind = "decision"
            payload = {
                "status": status,
                "reason_code": reason,
                "confirmation_id": confirmation_id,
            }
        envelope = {
            "contract_version": "native_single_step_response_v1",
            "confirmation_id": confirmation_id,
            "kind": kind,
            "payload": payload,
            "artifact_is_authorization": False,
        }
        return validate_single_step_response(envelope, confirmation_id=confirmation_id)
    except NativeSingleStepError:
        raise
    except Exception:
        raise NativeSingleStepError(
            "runtime_result_invalid",
            "grounded runtime returned an invalid result",
            result_unknown=True,
        ) from None


def _taskbar_attachment(claim) -> GroundedRuntimeAttachment:
    from app.agent.taskbar_activation_guard import TaskbarActivationExpectation
    from app.desktop_review.taskbar_activation import _digest

    preview = claim.preview
    if (claim.phase not in {"pending", "approved"}
            or preview.get("contract_version") != "taskbar_activation_preview_v1"
            or preview.get("source_kind") != "taskbar_activation"
            or preview.get("semantic_action") != "taskbar_activate"
            or preview.get("session_id") != claim.session_id
            or preview.get("confirmation_id") != claim.confirmation_id
            or preview.get("artifact_is_authorization") is not False
            or preview.get("grants_action_authority") is not False
            or preview.get("preview_sha256") != _digest({k: v for k, v in preview.items() if k != "preview_sha256"})):
        raise ValueError("taskbar confirmation is not attachable")
    source = TaskbarActivationExpectation.from_dict(preview["source"])
    return GroundedRuntimeAttachment(confirmation_id=claim.confirmation_id,
        session_id=claim.session_id, observation_id=source.capture_id, intent_id=claim.confirmation_id,
        workflow_id=None, asset_id=None, target_window_handle=source.taskbar_handle,
        target_process_id=preview["source"]["taskbar"]["pid"],
        source_kind="taskbar_activation", source_sha256=source.source_sha256,
        destination_window_handle=source.destination_handle,
        destination_process_id=preview['source']['destination']['pid'], preview_sha256=preview['preview_sha256'])


def _fresh_attachment(claim) -> GroundedRuntimeAttachment:
    from app.agent.fresh_learning_action_contracts import FreshLearningServerBinding
    from app.agent.fresh_learning_action_preview import validate_fresh_preview_binding
    from app.agent.runtime_fresh_confirmation import RuntimeFreshLearningGroundedConfirmationSnapshot
    from app.agent.automatic_safety_policy import preview_automatic_safety_interception

    grounded = claim.grounded_confirmation
    if (type(grounded) is not RuntimeFreshLearningGroundedConfirmationSnapshot
            or grounded.owner_is_current is not True
            or claim.phase not in {"grounded_confirmation_pending", "grounded_confirmation_approved"}
            or grounded.phase != claim.phase.removeprefix("grounded_confirmation_")
            or any(getattr(value, key) is not False for value in (claim, grounded)
                   for key in ("artifact_is_authorization", "grants_action_authority"))):
        raise ValueError("fresh confirmation is not attachable")
    source = claim.observation.to_dict()["source"]
    validate_fresh_preview_binding(grounded.preview, claim.observation, claim.intent, source)
    if claim.server_binding != FreshLearningServerBinding.from_source(source):
        raise ValueError("fresh attachment source differs")
    return GroundedRuntimeAttachment(
        confirmation_id=grounded.confirmation_id,
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        intent_id=claim.intent.intent_id,
        workflow_id=None, asset_id=None,
        target_window_handle=claim.server_binding.target_window_handle,
        target_process_id=claim.server_binding.target_process_id,
        source_kind="fresh_learning", source_sha256=claim.server_binding.source_sha256,
        automatic_safety_interception=preview_automatic_safety_interception(grounded.preview),
    )


def _validate_attachment_result(envelope, attachment) -> None:
    if envelope["kind"] != "receipt":
        return
    payload = envelope["payload"]
    taskbar = payload.get("contract_version") == "taskbar_activation_receipt_v1"
    if taskbar or attachment.source_kind == "taskbar_activation":
        if (not taskbar or attachment.source_kind != "taskbar_activation"
                or any(payload[key] != getattr(attachment, key)
                       for key in ("confirmation_id", "session_id", "source_sha256", "target_window_handle",
                                   "destination_window_handle", "destination_process_id", "preview_sha256"))):
            raise NativeSingleStepError("runtime_result_invalid", "taskbar receipt does not match attached owner", result_unknown=True)
        return
    fresh = payload.get("contract_version") in {'runtime_fresh_result_receipt_v1', 'runtime_fresh_result_receipt_v2'}
    if fresh and attachment.source_kind == 'fresh_learning':
        # 从挂接时的预览固定模式，不读取之后可能变化的本地设置。
        expected_version, expected_gate = (
            ('runtime_fresh_result_receipt_v1', 'allowed') if attachment.automatic_safety_interception
            else ('runtime_fresh_result_receipt_v2', 'manual_confirmed'))
        if payload.get('contract_version') != expected_version or payload.get('gate_status') != expected_gate:
            raise NativeSingleStepError('runtime_result_invalid',
                'single-step receipt safety mode differs from attached preview', result_unknown=True)
    if fresh != (attachment.source_kind == "fresh_learning") or (fresh and any(
        payload[key] != getattr(attachment, key)
        for key in ("session_id", "observation_id", "intent_id", "source_sha256")
    )):
        raise NativeSingleStepError(
            "runtime_result_invalid", "single-step receipt does not match attached owner",
            result_unknown=True,
        )


def _raise_http_error(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"error"}:
        raise NativeSingleStepError(
            "invalid_response", "single-step host returned an invalid error",
            result_unknown=True,
        )
    error = value["error"]
    if (
        not isinstance(error, dict)
        or set(error) != {"code", "message", "result_unknown"}
        or not isinstance(error.get("code"), str)
        or not error["code"]
        or not isinstance(error.get("message"), str)
        or not error["message"]
        or type(error.get("result_unknown")) is not bool
    ):
        raise NativeSingleStepError(
            "invalid_response", "single-step host returned an invalid error",
            result_unknown=True,
        )
    raise NativeSingleStepError(
        error["code"], error["message"], result_unknown=error["result_unknown"]
    )


def _validate_fresh_recovery_release(value: Any, *, attachment: GroundedRuntimeAttachment) -> None:
    from app.agent.fresh_learning_action_contracts import RuntimeFreshLearningClaimSnapshot

    if (attachment.source_kind != "fresh_learning"
            or type(value) is not RuntimeFreshLearningClaimSnapshot
            or value.phase not in {"grounded_confirmation_consume_started", "dispatch_started"}
            or value.recovery_required is not True or value.grounded_consume is None
            or value.observation.session_id != attachment.session_id
            or value.observation.observation_id != attachment.observation_id
            or value.intent.intent_id != attachment.intent_id
            or value.server_binding.source_sha256 != attachment.source_sha256
            or value.grounded_confirmation is None
            or value.grounded_confirmation.confirmation_id != attachment.confirmation_id
            or value.grounded_consume.confirmation_id != attachment.confirmation_id):
        raise NativeSingleStepError("runtime_cleanup_pending", "fresh local recovery release cannot be verified", result_unknown=True)


def _validate_cancelled_snapshot(
    value: Any,
    *,
    attachment: GroundedRuntimeAttachment,
) -> None:
    if attachment.source_kind == "taskbar_activation":
        from app.desktop_review.taskbar_activation import TaskbarActivationClaim

        if (type(value) is not TaskbarActivationClaim or value.phase != "cancelled"
                or value.session_id != attachment.session_id or value.confirmation_id != attachment.confirmation_id
                or value.preview["source"]["source_sha256"] != attachment.source_sha256):
            raise NativeSingleStepError("runtime_cleanup_pending", "taskbar cancellation could not be verified")
        return
    grounded = getattr(value, "grounded_confirmation", None)
    observation = getattr(value, "observation", None)
    if attachment.source_kind == "fresh_learning":
        from app.agent.fresh_learning_action_contracts import RuntimeFreshLearningClaimSnapshot

        if (type(value) is not RuntimeFreshLearningClaimSnapshot
                or observation.session_id != attachment.session_id
                or observation.observation_id != attachment.observation_id
                or value.intent.intent_id != attachment.intent_id
                or value.server_binding.source_sha256 != attachment.source_sha256
                or grounded is None or grounded.confirmation_id != attachment.confirmation_id
                or not (
                    value.phase == "grounded_confirmation_denied" and grounded.decision == "denied"
                    or value.phase == "grounded_confirmation_closed"
                    and grounded.closed_reason_code == "grounded_confirmation_cancelled"
                )):
            raise NativeSingleStepError("runtime_cleanup_pending", "fresh cancellation could not be verified")
        return
    if (
        getattr(value, "phase", None) != "grounded_confirmation_closed"
        or getattr(observation, "session_id", None) != attachment.session_id
        or getattr(grounded, "confirmation_id", None) != attachment.confirmation_id
        or getattr(grounded, "closed_reason_code", None)
        != "grounded_confirmation_cancelled"
    ):
        raise NativeSingleStepError(
            "runtime_cleanup_pending",
            "grounded cancellation could not be verified",
            result_unknown=False,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _confirmation_id(value: Any) -> str:
    if not isinstance(value, str) or _CONFIRMATION.fullmatch(value) is None:
        raise NativeSingleStepError(
            "invalid_confirmation_id", "grounded confirmation identity is invalid"
        )
    return value


def _base_url(value: Any) -> str:
    try:
        parsed = urlsplit(value)
        if (
            not isinstance(value, str)
            or parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or value != f"http://127.0.0.1:{parsed.port}"
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise NativeSingleStepError("invalid_base_url", "owned base URL is invalid") from None
    return value


def _timeout(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise NativeSingleStepError("invalid_timeout", "timeout must be positive")
    return float(value)


__all__ = [
    "GroundedRuntimeAttachment", "NativeSingleStepController",
    "NativeSingleStepError", "OwnedSingleStepClient",
    "validate_single_step_response",
]
