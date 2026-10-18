"""原生历史发现和仅后验恢复；不创建执行 attachment 或网络权限。"""

from copy import deepcopy


def history_item(store, claim):
    from app.agent.fresh_learning_action_contracts import RuntimeFreshLearningClaimSnapshot
    from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt

    grounded = claim.grounded_confirmation
    if grounded is None:
        raise ValueError("grounded history identity is missing")
    preview = grounded.preview.to_dict()
    receipt = None
    operation = {
        "grounded_confirmation_pending": "close_unexecuted",
        "grounded_confirmation_approved": "close_unexecuted",
        "verification_pending": "verify_postcheck",
        "grounded_confirmation_consume_started": "indeterminate",
        "dispatch_started": "indeterminate",
    }.get(claim.phase, "view_history")
    requested_at = grounded.requested_at
    if isinstance(claim, RuntimeFreshLearningClaimSnapshot):
        if claim.phase not in {"grounded_confirmation_pending", "grounded_confirmation_approved",
                               "grounded_confirmation_denied", "grounded_confirmation_closed",
                               "grounded_confirmation_consume_started", "dispatch_started", "terminal"}:
            raise ValueError("fresh history phase is invalid")
        if claim.phase == "terminal":
            loaded = store.load_terminal_receipt(
                session_id=claim.observation.session_id,
                observation_id=claim.observation.observation_id,
            )
            if type(loaded) is not RuntimeFreshResultReceipt:
                raise ValueError("fresh history receipt family is invalid")
            consume = claim.grounded_consume
            if (consume is None or claim.terminal_receipt_id != loaded.receipt_id
                    or loaded.session_id != claim.observation.session_id
                    or loaded.observation_id != claim.observation.observation_id
                    or loaded.intent_id != claim.intent.intent_id
                    or loaded.source_sha256 != claim.server_binding.source_sha256
                    or loaded.action.action_id != claim.intent.action_id
                    or loaded.action.semantic_action != claim.intent.semantic_action
                    or loaded.evidence.source_sha256 != claim.server_binding.source_sha256
                    or loaded.evidence.confirmation_id != grounded.confirmation_id
                    or loaded.evidence.consume_content_sha256 != consume.content_sha256
                    or loaded.evidence.approved_preview_sha256 != consume.approved_preview_sha256
                    or loaded.evidence.fresh_preview_sha256 != consume.fresh_preview_sha256):
                raise ValueError("fresh history receipt binding is invalid")
            receipt = loaded.model_dump(mode="json")
        target = preview["observation_evidence"]["target"]
        selection = {"source_kind": "fresh_learning", "source_sha256": preview["source_sha256"],
                     "target_window_handle": target["window_handle"], "target_process_id": target["process_id"]}
        requested_at = grounded.requested_at.isoformat().replace("+00:00", "Z")
    else:
        if claim.phase == "terminal":
            receipt = store.load_terminal_receipt(
                session_id=claim.observation.session_id, observation_id=claim.observation.observation_id,
            ).model_dump(mode="json")
        selection = {"asset_id": claim.observation.workflow.asset_id,
                     "asset_content_sha256": claim.observation.workflow.asset_content_sha256,
                     "target_window_handle": preview["target_window_handle"],
                     "target_process_id": preview["target_process_id"]}
    return {
        "confirmation_id": grounded.confirmation_id,
        "session_id": claim.observation.session_id,
        "observation_id": claim.observation.observation_id,
        "action_id": claim.intent.action_id,
        "phase": claim.phase,
        "operation": operation,
        "selection": selection,
        "claim_sha256": claim.claim_content_sha256,
        "request_sha256": grounded.request_content_sha256,
        "requested_at": requested_at,
        "reason_code": grounded.closed_reason_code,
        "receipt": receipt,
    }


class GroundedHistoryMixin:
    def _grounded_history_store(self):
        if self._history_store is None:
            from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
            from app.agent.runtime_receipt_store import RuntimeReceiptStore

            self._history_store = RuntimeIntentClaimStore(
                project_root=self._project_root,
                receipt_store=RuntimeReceiptStore(project_root=self._project_root),
            )
        return self._history_store

    def history(self):
        self._begin_any({"idle", "history_recovery_required"})
        try:
            self._require_host_ready(require_unattached=True)

            def read():
                store = self._grounded_history_store()
                return [history_item(store, claim) for claim in store.list_grounded_claims()]

            return {
                "contract_version": "native_grounded_history_v1",
                "items": self._owner.call(read),
                "retained_confirmation_id": self._history_confirmation_id,
                "artifact_is_authorization": False,
            }
        except Exception as error:
            raise self._mapped(error, "grounded_history_unavailable", "Persisted history could not be verified.") from None
        finally:
            self._end()

    def recover_history(self, *, confirmation_id: str):
        self._begin_any({"idle", "history_recovery_required"})
        try:
            self._require_host_ready(require_unattached=True)
            retained = self._history_confirmation_id
            if retained is not None and retained != confirmation_id:
                raise self._error("grounded_recovery_owner_busy", "The same recovery must finish before selecting another record.")
            self._cancel_wait.clear()
            return self._owner.call(lambda: self._recover_history_on_owner(confirmation_id))
        except Exception as error:
            if self._factory_outcome_unknown or self._runtime is not None:
                self._phase = "history_recovery_required"
            else:
                self._history_confirmation_id = None
                self._phase = "idle"
            raise self._mapped(error, "grounded_recovery_required", "History recovery did not complete; no action was dispatched.",
                               force_unknown=self._history_confirmation_id is not None) from None
        finally:
            self._end()

    def _recover_history_on_owner(self, confirmation_id):
        from app.agent.runtime_contracts import RuntimeResultReceiptV1
        from .single_step_coordinator import _selection

        store = self._grounded_history_store()
        claim = store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        item = history_item(store, claim)
        if self._history_confirmation_id is None and item["operation"] == "close_unexecuted":
            claim = store.close_grounded_confirmation(
                confirmation_id=confirmation_id, reason_code="grounded_confirmation_restarted",
            )
            return self._history_response(history_item(store, claim))
        if self._history_confirmation_id is None and item["operation"] != "verify_postcheck":
            return self._history_response(item)
        if claim.phase not in {"verification_pending", "terminal"}:
            raise ValueError("retained recovery phase is invalid")
        target = item["selection"]
        selection = _selection(target["asset_id"], target["asset_content_sha256"],
                               target["target_window_handle"], target["target_process_id"])
        if self._factory_outcome_unknown:
            raise self._error("grounded_recovery_factory_unknown", "The retained factory outcome is unknown.", result_unknown=True)
        if self._runtime is None:
            self._history_confirmation_id = confirmation_id
            runtime = self._create_runtime_on_owner(selection)
            self._runtime = runtime
            self._selection = selection
            self._factory_outcome_unknown = False
        elif self._selection != selection:
            raise ValueError("retained recovery selection changed")
        elif claim.phase == "verification_pending":
            self._wait_foreground_on_owner(selection, bind=False)
        self._phase = "history_recovery_required"
        result = self._runtime.recover_grounded_confirmation(confirmation_id=confirmation_id)
        refreshed = store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        item = history_item(store, refreshed)
        if isinstance(result, RuntimeResultReceiptV1):
            if item["phase"] != "terminal" or result.model_dump(mode="json") != item["receipt"]:
                raise ValueError("recovered receipt differs from durable history")
            self._clear()
            return self._history_response(item)
        if (getattr(result, "status", None) not in {"RECOVERY_REQUIRED", "REJECTED"}
                or getattr(result, "confirmation_id", None) != confirmation_id):
            raise ValueError("recovery response identity is invalid")
        return self._history_response(item, reason_code=result.reason_code)

    def _history_response(self, item, *, reason_code=None):
        return {
            "contract_version": "native_grounded_recovery_v1",
            "item": deepcopy(item),
            "owner_retained": self._history_confirmation_id is not None,
            "reason_code": reason_code,
            "artifact_is_authorization": False,
        }
