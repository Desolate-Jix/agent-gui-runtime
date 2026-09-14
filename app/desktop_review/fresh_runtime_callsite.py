"""首次学习的本地生命周期适配，不提供第二套执行器。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.agent.fresh_learning_action_contracts import FreshLearningClaimObservation
from app.agent.fresh_learning_runtime_source import FreshLearningRuntimeSource, reload_fresh_learning_runtime_source
from app.agent.fresh_learning_runtime_session import ServerFreshLearningBinding, validate_fresh_runtime_owners
from app.agent.live_controller import LiveController, LiveControllerDecision
from app.agent.runtime_intent_claim_store import RuntimeFreshLearningClaimSnapshot
from app.agent.text_parameters import ResolvedTextParameters
from app.agent_link.learning_runtime_binding import LearningRuntimeBinding


@dataclass(frozen=True)
class FreshRuntimeSelection:
    source: FreshLearningRuntimeSource

    def __post_init__(self):
        if not isinstance(self.source, FreshLearningRuntimeSource):
            raise TypeError("fresh selection requires a real runtime source")

    @property
    def target_window_handle(self):
        return self.source.reference()["target_window_handle"]

    @property
    def target_process_id(self):
        return self.source.reference()["target_process_id"]

    def to_dict(self):
        return {"source_kind": "fresh_learning", "source_sha256": self.source.reference()["source_sha256"],
                "target_window_handle": self.target_window_handle, "target_process_id": self.target_process_id}


class FreshLearningRuntimeCallsite:
    def __init__(self, *, controller, learning_binding):
        if not isinstance(controller, LiveController) or not isinstance(controller._binding, ServerFreshLearningBinding):
            raise TypeError("fresh callsite requires the actual fresh controller")
        if not isinstance(learning_binding, LearningRuntimeBinding):
            raise TypeError("fresh callsite requires a learning binding")
        self._controller = controller
        self._learning_binding = learning_binding
        self._selection = FreshRuntimeSelection(controller._binding.source)
        self._preparation_id = "fresh-preparation." + uuid4().hex
        self._started = False
        self._session = None
        self._closed = False
        self._validate()

    def _validate(self):
        controller, binding, source = self._controller, self._learning_binding, self._selection.source
        if (controller._binding.source != source or controller._fresh_source_owner.segments is not binding.owner
                or controller._action_learning_recorder is not binding.recorder
                or binding.project_root != source.project_root):
            raise ValueError("fresh callsite owners or recorder do not match")
        reference = source.reference()
        if any(reference[key] != getattr(binding, key) for key in ("connection_id", "task_id", "segment_id")):
            raise ValueError("fresh callsite learning scope does not match source")
        validate_fresh_runtime_owners(source, controller._fresh_source_owner,
            controller._observation_source, controller._intent_claim_store.project_root)
        reload_fresh_learning_runtime_source(controller._fresh_source_owner, source)

    def start_session(self):
        self._validate()
        if self._started:
            raise ValueError("fresh preparation was already started")
        self._started = True
        self._session = self._controller.start_session_preparation(preparation_id=self._preparation_id)
        # 先保留会话再绑定，失败后仍能重试原所有者的清理。
        self._learning_binding.attach_validated_runtime(runtime_session_id=self._session.session_id)
        return FreshLearningClaimObservation.from_dict(self._session.current_observation.to_dict())

    def cancel_local_preparation(self):
        if not self._closed:
            if self._started:
                self._controller.cancel_session_preparation(preparation_id=self._preparation_id)
            if self._session is not None:
                self._close_empty_child()
            self._closed = True
        return {"contract_version": "local_preparation_cleanup_v1", "selection": self._selection.to_dict(),
                "cleanup_verified": True, "artifact_is_authorization": False}

    def _close_empty_child(self):
        binding = self._learning_binding
        # 附加失败可停在 pending_bind，直接读取既有清理范围，不重新创建 child。
        segment = binding.owner.store.read(lambda state: binding.owner._stored_cleanup_segment(
            state, binding.connection_id, binding.task_id, binding.segment_id))
        if any(child["runtime_session_id"] == self._session.session_id for child in segment["children"]):
            binding.close_unconsumed(runtime_session_id=self._session.session_id)

    def _close_empty_child_after_terminal_claim(self, *, confirmation_id=None):
        """仅凭持久 claim 的确切 session/observation 事实清理空 child。"""
        if self._session is None:
            return
        observation = self._session.current_observation
        claim = self._controller._intent_claim_store.find_for_observation(
            session_id=self._session.session_id,
            observation_id=observation.observation_id,
        )
        # Snapshot 类型由 claim store 返回；避免把 Decision 或普通结果当作事实。
        if not isinstance(claim, RuntimeFreshLearningClaimSnapshot):
            return
        if (claim.observation.session_id != self._session.session_id
                or claim.observation.observation_id != observation.observation_id
                or claim.phase not in {"grounded_confirmation_denied", "grounded_confirmation_closed"}
                or claim.recovery_required
                or claim.grounded_confirmation is None
                or (confirmation_id is not None
                    and claim.grounded_confirmation.confirmation_id != confirmation_id)):
            return
        self._close_empty_child()

    def request_grounded_confirmation(self, request, *, text_input: ResolvedTextParameters | None = None):
        self._validate()
        return self._controller.request_grounded_confirmation(request,
            target_process_id=self._selection.target_process_id,
            **({"text_input": text_input} if text_input is not None else {}))

    def get_local_grounded_confirmation(self, *, confirmation_id):
        return self._controller.get_local_grounded_confirmation(confirmation_id=confirmation_id)

    def get_local_grounded_image(self, *, confirmation_id):
        return self._controller.get_local_grounded_image(confirmation_id=confirmation_id)

    def get_local_grounded_text_input(self, *, confirmation_id):
        return self._controller.get_local_grounded_text_input(confirmation_id=confirmation_id)

    def get_local_grounded_text_field_expectation(self, *, confirmation_id):
        return self._controller.get_local_grounded_text_field_expectation(confirmation_id=confirmation_id)

    def decide_grounded_confirmation(self, *, confirmation_id, decision):
        result = self._controller.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id, decision=decision)
        self._close_empty_child_after_terminal_claim(confirmation_id=confirmation_id)
        return result

    def consume_grounded_confirmation(self, *, confirmation_id):
        result = self._controller.consume_grounded_confirmation(confirmation_id=confirmation_id)
        self._close_empty_child_after_terminal_claim(confirmation_id=confirmation_id)
        return result

    def release_local_fresh_recovery(self, *, confirmation_id):
        if self._session is None:
            raise ValueError("fresh recovery session is not owned")
        claim = self._controller._intent_claim_store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        if claim.observation.session_id != self._session.session_id:
            raise ValueError("fresh recovery confirmation is not owned")
        # 不调用空 child 清理：pending before 和未知派发必须留给后续恢复。
        return self._controller.release_local_fresh_recovery(confirmation_id=confirmation_id)

    def cancel_grounded_review(self, *, session_id):
        if self._session is None or session_id != self._session.session_id:
            raise ValueError("fresh review session is not owned")
        result = self._controller.cancel_grounded_review(session_id=session_id)
        self._close_empty_child_after_terminal_claim()
        return result

    def get_fresh_runtime_state(self):
        self._validate()
        if self._session is None:
            raise ValueError("fresh runtime has no observation")
        before = self._session.current_observation.to_dict()
        observation = before
        result = {"source_kind": "fresh_learning", "session_id": self._session.session_id,
                  "source_sha256": self._selection.source.reference()["source_sha256"],
                  "observation_role": "before_action"}
        store = self._controller._intent_claim_store
        claim = store.find_for_observation(session_id=self._session.session_id,
            observation_id=before["observation_id"])
        if claim is not None:
            result["claim_phase"] = claim.phase
            result["recovery_required"] = claim.recovery_required
            if claim.grounded_confirmation is not None:
                result["confirmation_id"] = claim.grounded_confirmation.confirmation_id
            if claim.phase == "terminal":
                claim, record = store.read_committed_terminal_evidence(session_id=self._session.session_id,
                    observation_id=before["observation_id"])
                result["receipt"] = record.runtime_receipt.model_dump(mode="json")
                observation = None if record.next_observation is None else record.next_observation.to_dict()
                result["observation_role"] = "unavailable_after_action" if observation is None else "after_action"
        if observation is not None:
            source = self._selection.source.reference()
            packet = self._controller._fresh_source_owner.archive.read(observation["capture_source"],
                **{key: source[key] for key in ("connection_id", "task_id", "segment_id")})
            if packet.evidence()["capture"] != observation["capture"]:
                raise ValueError("fresh runtime image does not match observation")
            capture = observation["capture"]
            size = capture["viewport_size"]
            result["observation"] = observation
            result["screenshot"] = {"mime_type": "image/png", "sha256": capture["screenshot_sha256"],
                "width": size["width"], "height": size["height"],
                "png_base64": base64.b64encode(packet.png_bytes).decode("ascii")}
        self._validate()
        return result


def build_fresh_runtime_callsite(*, project_root, selection, window_manager, fresh_source_owner,
                                learning_binding, vision_configuration=None, automatic_safety_interception=True):
    if type(automatic_safety_interception) is not bool:
        raise TypeError("automatic_safety_interception must be a bool")
    from app.agent.desktop_backend import ExistingWindowsBackendAdapter
    from app.agent.fresh_learning_factory import create_fresh_learning_observation_owner
    from app.agent.live_controller import ExistingWindowManagerVisibilityChecker
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    if not isinstance(selection, FreshRuntimeSelection) or selection.source.project_root != Path(project_root).resolve():
        raise ValueError("fresh production source root does not match")
    if not isinstance(learning_binding, LearningRuntimeBinding) or fresh_source_owner.segments is not learning_binding.owner:
        raise ValueError("fresh production learning owner does not match")
    reference = selection.source.reference()
    if any(reference[key] != getattr(learning_binding, key) for key in ("connection_id", "task_id", "segment_id")):
        raise ValueError("fresh production learning scope does not match")
    reload_fresh_learning_runtime_source(fresh_source_owner, selection.source)
    observation = create_fresh_learning_observation_owner(project_root=project_root,
        application_identity=reference["application_identity"],
        target_window_handle=selection.target_window_handle, target_process_id=selection.target_process_id,
        vision_configuration=vision_configuration)
    receipts = RuntimeReceiptStore(project_root=project_root)
    claims = RuntimeIntentClaimStore(project_root=project_root, receipt_store=receipts)
    controller = LiveController(binding=ServerFreshLearningBinding(selection.source),
        fresh_source_owner=fresh_source_owner, observation_source=observation,
        # 首次来源由已有 fresh preview 门禁校验，不构造已审核资产依赖。
        target_resolver=None, gate=None, asset_loader=None,
        window_visibility_checker=ExistingWindowManagerVisibilityChecker(window_manager=window_manager),
        backend=ExistingWindowsBackendAdapter(window_manager=window_manager),
        intent_claim_store=claims, grounding_policy={}, action_learning_recorder=learning_binding.recorder,
        automatic_safety_interception=automatic_safety_interception)
    return FreshLearningRuntimeCallsite(controller=controller, learning_binding=learning_binding)
