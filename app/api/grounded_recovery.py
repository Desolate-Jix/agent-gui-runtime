"""重启后的本地 grounded 后验恢复；此入口不恢复执行批准。"""

from app.agent.live_controller import LiveControllerDecision
from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError


class GroundedRecoveryMixin:
    def _require_no_grounded_recovery(self):
        if self._grounded_recovery_id is not None:
            raise self._error(409, "grounded_recovery_owner_busy", "Only exact post-verification recovery may use the retained owner.")

    def recover_grounded_confirmation(self, *, confirmation_id: str):
        from .agent_runtime import _DecisionProjection

        with self._lock:
            self._require_exact_selection()
            recovery_id = self._grounded_recovery_id
            if recovery_id is not None and recovery_id != confirmation_id:
                raise self._error(409, "grounded_recovery_owner_busy", "The exact recovery owner must be retained.")
            if recovery_id is None and (
                self._controller is not None or self._observation is not None
                or self._grounded_intent is not None or self._pending_cleanup is not None
                or self._grounded_cleanup is not None or self._preparation_owner is not None
                or self._preparation_unknown
            ):
                raise self._error(409, "grounded_recovery_owner_busy", "A live preparation or execution owner is still active.")
            claim = self._load_grounded_by_confirmation(confirmation_id)
            if self._grounded_recovery_factory_unknown:
                raise self._error(503, "grounded_recovery_factory_unknown", "Recovery factory ownership is unknown; it cannot be recreated.")
            if claim.phase == "terminal" and recovery_id is None:
                return self._load_terminal_receipt(claim)
            if claim.phase not in {"verification_pending", "terminal"}:
                reason = {
                    "dispatch_started": "dispatch_indeterminate",
                    "grounded_confirmation_consume_started": "grounded_consume_indeterminate",
                }.get(claim.phase, "grounded_recovery_not_allowed")
                return _DecisionProjection("RECOVERY_REQUIRED", reason, confirmation_id)
            if claim.phase == "verification_pending":
                if claim.verification_checkpoint is None or claim.grounded_consume is None:
                    raise self._error(503, "grounded_recovery_checkpoint_invalid", "A complete grounded verification checkpoint is required.")
                resolved = self._resolve_server_binding()
                if resolved.workflow != claim.observation.workflow or claim.server_binding.to_dict() != {
                    "workflow_id": resolved.binding.workflow_id,
                    "asset_id": resolved.binding.asset_id,
                    "application_identity_key": resolved.binding.application_identity_key,
                    "target_window_handle": resolved.binding.target_window_handle,
                }:
                    raise self._error(412, "agent_runtime_binding_mismatch", "Recovery cannot change the persisted workflow or window binding.")
            if recovery_id is None:
                # 在可能取得资源的 factory 前记账；异常不是可安全重试的创建失败。
                self._grounded_recovery_id = confirmation_id
                self._grounded_recovery_factory_unknown = True
                self._grounded_intent = claim.intent
                self._grounded_confirmation_id = confirmation_id
                try:
                    controller = self._controller_factory(resolved.binding)
                except Exception as exc:
                    raise self._error(503, "grounded_recovery_factory_unknown", "Recovery controller ownership could not be established.") from exc
                self._controller = controller
                if not callable(getattr(controller, "consume_grounded_confirmation", None)):
                    raise self._error(503, "grounded_recovery_factory_unknown", "Recovery controller protocol is invalid.")
                self._observation = claim.observation
                self._target_window_handle = resolved.binding.target_window_handle
                self._target_process_id = resolved.process_id
                self._grounded_recovery_factory_unknown = False
            controller = self._controller
            # 仅允许持久 checkpoint / terminal 两种状态进入原后验或清理尾部。
            try:
                result = controller.consume_grounded_confirmation(confirmation_id=confirmation_id)
            except Exception as exc:
                raise self._error(503, "grounded_recovery_required", "Post-verification recovery did not complete; the same owner is retained.") from exc
            if isinstance(result, LiveControllerDecision):
                if result.status not in {"RECOVERY_REQUIRED", "REJECTED"} or result.confirmation_id not in {None, confirmation_id}:
                    raise self._error(503, "grounded_recovery_result_invalid", "Recovery decision identity is invalid.")
                return _DecisionProjection(result.status, result.reason_code, confirmation_id)
            if not isinstance(result, RuntimeResultReceiptV1):
                raise self._error(503, "grounded_recovery_result_invalid", "Recovery did not return a verified receipt.")
            try:
                verified = self._claim_store.load_terminal_receipt(
                    session_id=claim.observation.session_id, observation_id=claim.observation.observation_id,
                )
            except RuntimeIntentClaimStoreError as exc:
                raise self._grounded_store_error(exc)
            if verified != result:
                raise self._error(503, "grounded_recovery_result_invalid", "Recovery receipt differs from the authoritative stored receipt.")
            self._grounded_cancelled_sessions.add(claim.observation.session_id)
            self._clear_active()
            return verified
