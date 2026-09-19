from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from functools import partial
from hashlib import sha256
from io import BytesIO
import json
import math
import time
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1
from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.agent.live_controller import (
    ExistingWindowManagerVisibilityChecker,
    LiveController,
    ProjectedObservationCapture,
    ServerWorkflowBinding,
)
from app.agent.native_identity import (
    WindowsNativeIdentityReader,
    require_reviewed_native_executable_path,
    validate_native_identity_fact,
)
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.agent.action_parameters import reviewed_action_parameter_fields, validate_reviewed_action_grounding_geometry
from app.agent.action_learning_recorder import ActionLearningRecorder
from app.agent.action_learning_capture_archive import ActionLearningCaptureArchive
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_contracts import (
    AgentObservationV1,
    WorkflowRefV1,
    validate_agent_observation_v1,
)
from app.agent.windows_uia_origin_reader import WindowsUIAOriginReader
from app.agent.text_field_evidence import TextFieldSnapshot
from app.operation.page_structure.schemas import InteractionPolicy, PageElement, VerificationHints
from app.operation.recognition.decision import decide_pre_click
from app.operation.recognition.schemas import (
    CandidateRankResult,
    LocalGroundingCandidateResult,
    LocalGroundingResult,
    RecognitionCandidate,
    ScoreBreakdown,
)
from app.vision.schemas import BBox
from app.vision.configuration import (
    VisionConfigurationSnapshot, load_formal_vision_configuration,
    pinned_vision_configuration, resolve_vision_config_path,
)


_DEFAULT_GROUNDING_POLICY = {
    "minimum_confidence": 0.45,
    "minimum_score_margin": 0.06,
}


@dataclass(frozen=True, slots=True)
class _CurrentEvidenceBundle:
    session_id: str
    capture_id: str
    screenshot_sha256: str
    asset_content_sha256: str
    target_window_handle: int
    target_process_id: int
    viewport_size: tuple[int, int]
    image_path: str
    asset_json: bytes
    current_observation_json: bytes
    native_identity_json: bytes | None
    recognition_by_anchor: tuple[tuple[str, bytes], ...]
    scroll_capture_json: bytes | None = None
    text_capture_json: bytes | None = None


class ExistingWindowsCurrentEvidenceAdapter:
    """把当前 Windows 事实投影给 LiveController，不产生执行权限。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        application_identity_key: str,
        provider_mode: str | None = None,
        screenshot_service: Any | None = None,
        origin_reader: Any | None = None,
        native_identity_reader: Any | None = None,
        window_manager: Any | None = None,
        recognition_runner: Callable[..., Mapping[str, Any]] | None = None,
        uia_provider: Any | None = None,
        text_field_reader: Any | None = None,
        grounding_policy: Mapping[str, Any] | None = None,
        cache_limit: int = 8,
        vision_configuration: VisionConfigurationSnapshot | None = None,
        capture_archive: ActionLearningCaptureArchive | None = None,
    ) -> None:
        if vision_configuration is not None and not isinstance(vision_configuration, VisionConfigurationSnapshot):
            raise TypeError("vision_configuration must be VisionConfigurationSnapshot or None")
        if recognition_runner is None:
            configuration = vision_configuration or load_formal_vision_configuration(
                resolve_vision_config_path(project_root=project_root), provider_mode=provider_mode,
            )
            if provider_mode is not None and provider_mode.strip().lower() != configuration.mode:
                raise ValueError("vision provider mode differs from the owned configuration")
            provider_mode = configuration.mode
            recognition_runner = partial(_run_existing_read_only_recognition, vision_configuration=configuration)
        if screenshot_service is None:
            from app.core.screenshot import screenshot_service as active_screenshot_service

            screenshot_service = active_screenshot_service
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        resolved_project_root = Path(project_root).resolve()
        if capture_archive is not None and not isinstance(
            capture_archive, ActionLearningCaptureArchive,
        ):
            raise TypeError("capture_archive must be ActionLearningCaptureArchive or None")
        if (
            capture_archive is not None
            and capture_archive.project_root != resolved_project_root
        ):
            raise ValueError("capture_archive must use the same project root")
        self._project_root = resolved_project_root
        self._application_identity_key = application_identity_key
        self._provider_mode = provider_mode
        self._screenshot_service = screenshot_service
        self._window_manager = window_manager
        self._origin_reader = origin_reader or WindowsUIAOriginReader(window_manager=window_manager)
        self._native_identity_reader = native_identity_reader or WindowsNativeIdentityReader(window_manager=window_manager)
        self._recognition_runner = recognition_runner
        if uia_provider is None:
            from app.operation.screen_reading.uia_provider import uia_provider as active_uia_provider

            uia_provider = active_uia_provider
        self._uia_provider = uia_provider
        self._text_field_reader = text_field_reader
        policy = dict(_DEFAULT_GROUNDING_POLICY if grounding_policy is None else grounding_policy)
        self._minimum_confidence = _number(policy["minimum_confidence"], minimum=0.0, maximum=1.0)
        self._minimum_score_margin = _number(
            policy["minimum_score_margin"],
            minimum=0.0,
            maximum=1.0,
        )
        self._cache_limit = max(1, int(cache_limit))
        self._capture_archive = capture_archive
        self._cache: OrderedDict[tuple[str, str, str], _CurrentEvidenceBundle] = OrderedDict()
        self._native_session_identities: dict[str, bytes] = {}
        self._lock = RLock()

    def create_initial(
        self,
        *,
        session_id: str,
        workflow: dict[str, Any],
        asset: dict[str, Any],
        target_window_handle: int,
    ):
        return self.capture_projected(
            session_id=session_id,
            workflow=workflow,
            asset=asset,
            target_window_handle=target_window_handle,
        ).agent_observation

    def capture_current(
        self,
        *,
        session_id: str,
        asset: dict[str, Any],
        target_window_handle: int,
    ) -> Mapping[str, Any]:
        return self._capture_current(
            session_id=session_id,
            asset=asset,
            target_window_handle=target_window_handle,
        )

    def capture_projected(
        self,
        *,
        session_id: str,
        workflow: dict[str, Any],
        asset: dict[str, Any],
        target_window_handle: int,
    ) -> ProjectedObservationCapture:
        """一次 passive capture 同时封装 raw C1 与 AgentObservation。"""

        current = self._capture_current(
            session_id=session_id,
            asset=asset,
            target_window_handle=target_window_handle,
        )
        try:
            validated_workflow = WorkflowRefV1.model_validate(workflow)
            state_resolution = resolve_current_state(asset, current)
            projected = adapt_reviewed_context_to_agent_observation_v1(
                observation_id=f"observation.{uuid4().hex}",
                session_id=session_id,
                workflow_id=validated_workflow.workflow_id,
                reviewed_asset=asset,
                current_observation=current,
                state_resolution=state_resolution,
                project_root=self._project_root,
                application_identity_key=self._application_identity_key,
            )
            observation = validate_agent_observation_v1(
                projected.model_dump(mode="json")
                if isinstance(projected, AgentObservationV1)
                else projected
            )
            bundle = self._bundle_for_projected(
                session_id=session_id,
                current_observation=current,
            )
            asset_hash = content_sha256(asset)
            if (
                observation.session_id != session_id
                or observation.workflow != validated_workflow
                or observation.application.identity_ref
                != f"application:{self._application_identity_key}"
                or observation.current_capture.capture_id != current.get("capture_id")
                or observation.current_capture.screenshot_sha256
                != current.get("screenshot_sha256")
                or current.get("asset_id") != validated_workflow.asset_id
                or current.get("expected_asset_content_sha256") != asset_hash
                or validated_workflow.asset_content_sha256 != asset_hash
                or bundle.asset_content_sha256 != asset_hash
                or bundle.target_window_handle != target_window_handle
            ):
                raise ValueError("projected observation lineage mismatch")
        except Exception as exc:
            raise ValueError("current AgentObservation projection failed") from exc
        return ProjectedObservationCapture(
            session_id=session_id,
            workflow=validated_workflow,
            application_identity_key=self._application_identity_key,
            asset_id=validated_workflow.asset_id,
            asset_content_sha256=validated_workflow.asset_content_sha256,
            target_window_handle=bundle.target_window_handle,
            target_process_id=bundle.target_process_id,
            current_observation=deepcopy(current),
            agent_observation=observation,
        )

    def resolve(
        self,
        *,
        session_id: str,
        selection: dict[str, Any],
        current_observation: dict[str, Any],
    ) -> Mapping[str, Any]:
        bundle = self._find_bundle(
            session_id=session_id,
            selection=selection,
            current_observation=current_observation,
        )
        if bundle is None:
            return {"status": "stale", "reason": "current_evidence_missing"}
        try:
            asset = _json_mapping(bundle.asset_json)
            anchor = _unique_anchor(asset, str(selection.get("element_ref") or ""))
        except ValueError:
            return {"status": "unresolved", "reason": "reviewed_target_missing"}
        recognition_bytes = dict(bundle.recognition_by_anchor).get(str(anchor["anchor_id"]))
        if recognition_bytes is None:
            return {"status": "unresolved", "reason": "current_target_unmatched"}
        try:
            candidates, local_grounding = _parse_recognition(_json_mapping(recognition_bytes))
        except ValueError:
            return {"status": "unresolved", "reason": "malformed_current_recognition"}
        transition = next(
            (
                item
                for item in asset.get("transitions", [])
                if item.get("transition_id") == selection.get("transition_id")
            ),
            None,
        )
        try:
            parameter_fields = reviewed_action_parameter_fields(selection)
            if parameter_fields != reviewed_action_parameter_fields(transition or {}):
                return {"status": "unresolved", "reason": "reviewed_scroll_parameters_mismatch"}
        except ValueError:
            return {"status": "unresolved", "reason": "reviewed_scroll_parameters_invalid"}
        matches = _matching_pairs(
            candidates,
            local_grounding,
            anchor,
            contextual_apply_alias=_selected_transition_allows_contextual_apply_alias(
                transition,
                anchor_id=str(anchor["anchor_id"]),
                element_ref=str(selection.get("element_ref") or ""),
            ),
        )
        if not matches:
            return {"status": "unresolved", "reason": "current_target_unmatched"}
        if len(matches) != 1:
            return {"status": "ambiguous", "reason": "current_target_ambiguous"}
        candidate, local = matches[0]
        if (
            not candidates.candidates
            or candidates.candidates[0].candidate_id != candidate.candidate_id
            or candidates.recommended_candidate_id != candidate.candidate_id
            or local_grounding.recommended_candidate_id != candidate.candidate_id
        ):
            return {"status": "ambiguous", "reason": "current_target_not_unique_top"}
        element_ref = str(selection["element_ref"])
        projected_candidate = replace(
            candidate,
            element_id=element_ref,
            element=replace(candidate.element, element_id=element_ref),
        )
        projected_candidates = replace(
            candidates,
            candidates=[projected_candidate],
            margin_to_second=_rank_margin([projected_candidate]),
        )
        projected_local = replace(
            local_grounding,
            results=[replace(local, element_id=element_ref)],
        )
        preliminary = decide_pre_click(
            goal=projected_candidates.goal,
            candidates=projected_candidates,
            grounding=projected_local,
        )
        candidate_decision = next(
            (
                item
                for item in preliminary.candidate_decisions
                if item.candidate_id == candidate.candidate_id
            ),
            None,
        )
        if candidate_decision is None or candidate_decision.click_point is None:
            return {"status": "unresolved", "reason": "current_click_point_unresolved"}
        bbox = _candidate_bbox(projected_candidate)
        lineage = selection.get("capture_lineage")
        if not isinstance(lineage, Mapping):
            return {"status": "stale", "reason": "capture_lineage_mismatch"}
        margin = projected_candidates.margin_to_second
        if margin is None:
            margin = _rank_margin(projected_candidates.candidates)
        confidence = min(float(candidate.score), float(local.confidence))
        evidence_ref = (
            f"current-recognition:{bundle.capture_id}:"
            f"{bundle.screenshot_sha256[:16]}:{anchor['anchor_id']}:{candidate.candidate_id}"
        )
        grounding = {
            "contract_version": "reviewed_workflow_current_grounding_v1",
            "asset_content_sha256": selection.get("asset_content_sha256"),
            "transition_id": selection.get("transition_id"),
            "source_state_id": selection.get("source_state_id"),
            "capture_id": lineage.get("capture_id"),
            "screenshot_sha256": lineage.get("screenshot_sha256"),
            "viewport_size": lineage.get("viewport_size"),
            "element_ref": element_ref,
            "candidate_id": candidate.candidate_id,
            "candidate_current": True,
            "eligible": True,
            "confidence": confidence,
            "score_margin": float(margin),
            "bbox": bbox,
            "click_point": dict(candidate_decision.click_point),
            "evidence_refs": [evidence_ref],
            **parameter_fields,
        }
        gate_context: dict[str, object] = {
            "candidates": projected_candidates,
            "local_grounding": projected_local,
        }
        if isinstance(transition, Mapping) and isinstance(transition.get("expected_effect"), Mapping):
            gate_context["expected_effect"] = dict(transition["expected_effect"])
        return {
            "status": "resolved",
            "grounding": grounding,
            "gate_context": gate_context,
        }

    def _capture_current(
        self,
        *,
        session_id: str,
        asset: dict[str, Any],
        target_window_handle: int,
    ) -> dict[str, Any]:
        application = asset.get("application") if isinstance(asset.get("application"), Mapping) else {}
        is_native = application.get("kind") == "native"
        has_scroll = any(item.get("semantic_action") == "scroll_region" for item in asset.get("transitions", []))
        has_text = any(item.get("semantic_action") == "fill_field" for item in asset.get("transitions", []))
        input_kind = "scroll" if has_scroll else "text"
        expected_native_path = require_reviewed_native_executable_path(application) if is_native else None
        before_bound = self._window_manager.get_bound_window()
        before = _bound_identity(
            before_bound,
            target_window_handle=target_window_handle,
        )
        native_before = (
            _validated_native_identity(
                self._native_identity_reader.read_identity(target_window_handle),
                target_window_handle=target_window_handle,
                process_id=before[1],
                expected_executable_path=expected_native_path,
            )
            if is_native
            else None
        )
        if native_before is not None:
            identity_bytes = _json_bytes(native_before)
            with self._lock:
                previous = self._native_session_identities.setdefault(session_id, identity_bytes)
                if previous != identity_bytes:
                    raise ValueError("native runtime session process identity changed; a new review is required")
        input_identity = None
        input_rect = None
        if has_scroll or has_text:
            input_identity = validate_native_identity_fact(
                native_before if is_native else self._native_identity_reader.read_identity(target_window_handle),
                target_window_handle=target_window_handle, expected_process_id=before[1],
            )
            if input_identity is None:
                raise ValueError(f"{input_kind} capture process identity is unavailable")
            input_rect = {"x": int(before_bound.rect.left), "y": int(before_bound.rect.top),
                           "width": before[2][0], "height": before[2][1]}
        capture_started_ns = time.perf_counter_ns()
        capture = self._screenshot_service.capture_window(
            save_image=True,
            focus_window=False,
            purpose="runtime-observation",
        )
        captured_at_ns = time.perf_counter_ns()
        after_bound = self._window_manager.get_bound_window()
        after = _bound_identity(
            after_bound,
            target_window_handle=target_window_handle,
        )
        if before != after:
            raise ValueError("bound window binding drift detected during passive capture")
        if has_scroll or has_text:
            after_identity = validate_native_identity_fact(
                self._native_identity_reader.read_identity(target_window_handle),
                target_window_handle=target_window_handle, expected_process_id=after[1],
            )
            after_rect = {"x": int(after_bound.rect.left), "y": int(after_bound.rect.top),
                          "width": after[2][0], "height": after[2][1]}
            if after_identity != input_identity or after_rect != input_rect:
                raise ValueError(f"{input_kind} capture window binding changed")
        if is_native:
            native_after_capture = _validated_native_identity(
                self._native_identity_reader.read_identity(target_window_handle),
                target_window_handle=target_window_handle,
                process_id=before[1],
                expected_executable_path=expected_native_path,
            )
            if native_before != native_after_capture:
                raise ValueError("bound native process identity drift detected during passive capture")
        image_path, image_bytes, viewport = _validated_saved_capture(capture, expected_size=before[2])
        screenshot_digest = sha256(image_bytes).hexdigest()
        capture_id = f"runtime-capture.{uuid4().hex}"
        observed_origin = ""
        if not is_native:
            origin_fact = self._origin_reader.read_origin(target_window_handle)
            observed_origin = _validated_origin_fact(
                origin_fact,
                target_window_handle=target_window_handle,
                process_id=before[1],
            )
        asset_hash = content_sha256(asset)
        canonical_origin = str(application.get("canonical_origin") or "")
        recognition_by_anchor: list[tuple[str, bytes]] = []
        recognition_by_goal: dict[str, bytes] = {}
        anchor_evidence: list[dict[str, object]] = []
        if is_native or (observed_origin and observed_origin == canonical_origin):
            uia_snapshot = _validated_uia_snapshot(
                self._uia_provider.snapshot_window(after_bound),
                expected_identity=before,
            )
            for anchor in _all_unique_anchors(asset):
                goal = str(anchor["label"])
                raw_bytes = recognition_by_goal.get(goal)
                if raw_bytes is None:
                    try:
                        raw = self._recognition_runner(
                            image_path=str(image_path),
                            goal=goal,
                            provider_mode=self._provider_mode,
                            uia_snapshot=uia_snapshot,
                        )
                        raw_bytes = _json_bytes(raw)
                    except Exception as exc:
                        raise ValueError("current recognition failed for a reviewed anchor") from exc
                    recognition_by_goal[goal] = raw_bytes
                recognition_by_anchor.append((str(anchor["anchor_id"]), raw_bytes))
                try:
                    candidates, local = _parse_recognition(_json_mapping(raw_bytes))
                except ValueError:
                    continue
                matches = _matching_pairs(
                    candidates,
                    local,
                    anchor,
                    contextual_apply_alias=_anchor_allows_contextual_apply_alias(asset, anchor),
                    allow_text_identity_on_interactive_role=True,
                )
                recommended_matches = [
                    pair
                    for pair in matches
                    if pair[0].candidate_id == candidates.recommended_candidate_id
                    and pair[0].candidate_id == local.recommended_candidate_id
                ]
                if len(recommended_matches) != 1:
                    continue
                candidate, grounded = recommended_matches[0]
                confidence = min(float(candidate.score), float(grounded.confidence))
                if (
                    not candidates.candidates
                    or candidates.candidates[0].candidate_id != candidate.candidate_id
                    or candidates.recommended_candidate_id != candidate.candidate_id
                    or local.recommended_candidate_id != candidate.candidate_id
                    or confidence < self._minimum_confidence
                    or _rank_margin([pair[0] for pair in matches]) < self._minimum_score_margin
                ):
                    continue
                anchor_evidence.append(
                    {
                        "anchor_id": anchor["anchor_id"],
                        "matched": True,
                        "confidence": confidence,
                        "evidence_ref": (
                            f"current-recognition:{capture_id}:{screenshot_digest[:16]}:"
                            f"{anchor['anchor_id']}:{candidate.candidate_id}"
                        ),
                    }
                )
        final_bound = self._window_manager.get_bound_window()
        final = _bound_identity(
            final_bound,
            target_window_handle=target_window_handle,
        )
        if final != before:
            raise ValueError("bound window binding drift detected during current recognition")
        if has_text:
            final_identity = validate_native_identity_fact(
                self._native_identity_reader.read_identity(target_window_handle),
                target_window_handle=target_window_handle, expected_process_id=final[1],
            )
            final_rect = {"x": int(final_bound.rect.left), "y": int(final_bound.rect.top),
                          "width": final[2][0], "height": final[2][1]}
            if final_identity != input_identity or final_rect != input_rect:
                raise ValueError("text capture window binding changed during recognition")
        if is_native:
            native_final = _validated_native_identity(
                self._native_identity_reader.read_identity(target_window_handle),
                target_window_handle=target_window_handle,
                process_id=before[1],
                expected_executable_path=expected_native_path,
            )
            if native_before != native_final:
                raise ValueError("bound native process identity drift detected during current recognition")
        else:
            final_origin = _validated_origin_fact(
                self._origin_reader.read_origin(target_window_handle),
                target_window_handle=target_window_handle,
                process_id=before[1],
            )
            if final_origin != observed_origin:
                raise ValueError("bound window origin drift detected during current recognition")
        _require_unchanged_screenshot(image_path, expected_sha256=screenshot_digest)
        current = {
            "contract_version": "reviewed_workflow_current_observation_v2" if is_native else "reviewed_workflow_current_observation_v1",
            "asset_id": asset["asset_id"],
            "expected_asset_content_sha256": asset_hash,
            "capture_id": capture_id,
            "screenshot_sha256": screenshot_digest,
            "viewport_size": viewport,
            "origin": observed_origin or "",
            "observed_anchor_evidence": anchor_evidence,
        }
        if native_before is not None:
            current["native_identity"] = native_before
        bundle = _CurrentEvidenceBundle(
            session_id=session_id,
            capture_id=capture_id,
            screenshot_sha256=screenshot_digest,
            asset_content_sha256=asset_hash,
            target_window_handle=before[0],
            target_process_id=before[1],
            viewport_size=before[2],
            image_path=str(image_path),
            asset_json=_json_bytes(asset),
            current_observation_json=_json_bytes(current),
            native_identity_json=_json_bytes(native_before) if native_before is not None else None,
            recognition_by_anchor=tuple(recognition_by_anchor),
            scroll_capture_json=_json_bytes({
                "contract_version": "scroll_capture_snapshot_v1", "captured": True,
                "capture_status": "observed", "capture_id": capture_id,
                "capture_clock_id": "windows-perf-counter-v1",
                "capture_started_ns": capture_started_ns, "captured_at_ns": captured_at_ns,
                "roi": None, "window_handle": before[0], "window_rect": input_rect,
                "native_identity": input_identity, "viewport_size": viewport,
                "image_path": str(image_path), "image_sha256": screenshot_digest,
            }) if has_scroll else None,
            text_capture_json=_json_bytes({
                "contract_version": "text_capture_binding_v1", "capture_id": capture_id,
                "captured_at_ns": captured_at_ns, "window_rect": input_rect,
                "native_identity": input_identity,
            }) if has_text else None,
        )
        if self._capture_archive is not None:
            self._capture_archive.pin_current_capture(
                runtime_session_id=session_id,
                capture_id=capture_id,
                screenshot_sha256=screenshot_digest,
                viewport_size=viewport,
                asset_content_sha256=asset_hash,
                target_window_handle=before[0],
                target_process_id=before[1],
                png_bytes=image_bytes,
            )
        self._remember(bundle)
        return current

    def _remember(self, bundle: _CurrentEvidenceBundle) -> None:
        key = (bundle.session_id, bundle.capture_id, bundle.screenshot_sha256)
        with self._lock:
            self._cache[key] = bundle
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_limit:
                self._cache.popitem(last=False)

    def read_scroll_capture(self, *, session_id: str, current_observation: Mapping[str, Any]) -> dict[str, Any]:
        """返回同一次采集的范围证据，不能补拍来替换已确认截图。"""
        bundle = self._bundle_for_projected(session_id=session_id, current_observation=current_observation)
        if bundle.scroll_capture_json is None:
            raise ValueError("scroll capture metadata is unavailable")
        self.read_cached_grounded_image(
            session_id=session_id, asset_id=current_observation["asset_id"],
            asset_content_sha256=bundle.asset_content_sha256,
            target_window_handle=bundle.target_window_handle, target_process_id=bundle.target_process_id,
            capture_lineage={key: current_observation[key] for key in ("capture_id", "screenshot_sha256", "viewport_size")},
        )
        return _json_mapping(bundle.scroll_capture_json)

    def read_text_field(
        self, *, session_id: str, current_observation: Mapping[str, Any],
        selection: Mapping[str, Any], grounding: Mapping[str, Any],
        require_keyboard_focus: bool = False,
    ) -> TextFieldSnapshot:
        """只读当前审核字段的真实值；原文不进入公共观察或截图缓存。"""
        bundle = self._bundle_for_projected(session_id=session_id, current_observation=current_observation)
        if bundle.text_capture_json is None or selection.get("semantic_action") != "fill_field":
            raise ValueError("text field capture binding is unavailable")
        resolved = self.resolve(session_id=session_id, selection=dict(selection), current_observation=dict(current_observation))
        if resolved.get("status") != "resolved" or _json_bytes(resolved["grounding"]) != _json_bytes(grounding):
            raise ValueError("text field grounding differs from current reviewed evidence")
        asset = _json_mapping(bundle.asset_json)
        transitions = [item for item in asset["transitions"] if item["transition_id"] == selection.get("transition_id")]
        if len(transitions) != 1 or transitions[0].get("semantic_action") != "fill_field":
            raise ValueError("text field transition is unavailable")
        transition = transitions[0]
        anchor = _unique_anchor(asset, str(selection.get("element_ref") or ""))
        fields = reviewed_action_parameter_fields(transition)
        target_field_id = fields["text_parameters_ref"]["target_field_id"]
        if (anchor.get("text_field_id") != target_field_id
                or transition.get("element_ref") != selection.get("element_ref")):
            raise ValueError("text field does not match the reviewed anchor")
        validate_reviewed_action_grounding_geometry(transition, grounding)
        self.read_cached_grounded_image(
            session_id=session_id, asset_id=current_observation["asset_id"],
            asset_content_sha256=bundle.asset_content_sha256,
            target_window_handle=bundle.target_window_handle, target_process_id=bundle.target_process_id,
            capture_lineage={key: current_observation[key] for key in ("capture_id", "screenshot_sha256", "viewport_size")},
        )
        capture = _json_mapping(bundle.text_capture_json)
        rect = tuple(capture["window_rect"][key] for key in ("x", "y", "width", "height"))
        bbox = tuple(grounding["bbox"][key] for key in ("x", "y", "w", "h"))
        point = tuple(grounding["click_point"][key] for key in ("x", "y"))
        if self._text_field_reader is None:
            from app.agent.windows_text_field_reader import WindowsTextFieldReader
            self._text_field_reader = WindowsTextFieldReader(
                window_manager=self._window_manager, native_identity_reader=self._native_identity_reader,
            )
        actual = self._text_field_reader.read_field(
            target_field_id=target_field_id, capture_id=bundle.capture_id,
            target_window_handle=bundle.target_window_handle, target_process_id=bundle.target_process_id,
            process_create_time=capture["native_identity"]["process_create_time"],
            window_rect=rect, target_bbox=bbox, click_point=point,
            **({"require_keyboard_focus": True} if require_keyboard_focus else {}),
        )
        if (type(actual) is not TextFieldSnapshot or actual.capture_id != bundle.capture_id
                or actual.observed_at_ns <= capture["captured_at_ns"]
                or actual.identity.target_field_id != target_field_id
                or actual.identity.window_handle != bundle.target_window_handle
                or actual.identity.process_id != bundle.target_process_id
                or actual.identity.process_create_time != capture["native_identity"]["process_create_time"]
                or actual.identity.window_rect != rect):
            raise ValueError("text field result differs from the current capture binding")
        x, y, width, height = actual.identity.control_bbox
        if not (x <= bbox[0] and y <= bbox[1] and bbox[0] + bbox[2] <= x + width
                and bbox[1] + bbox[3] <= y + height):
            raise ValueError("text field geometry differs from the reviewed target")
        return actual

    def read_text_field_after(
        self,
        *,
        session_id: str,
        current_observation: Mapping[str, Any],
        previous_selection: Mapping[str, Any],
    ) -> TextFieldSnapshot:
        """以新 capture 的识别事实回读已批准字段，不重放旧 transition。"""
        bundle = self._bundle_for_projected(
            session_id=session_id, current_observation=current_observation
        )
        if bundle.text_capture_json is None:
            raise ValueError("post text field capture binding is unavailable")
        asset = _json_mapping(bundle.asset_json)
        try:
            transition_id = previous_selection["transition_id"]
            element_ref = previous_selection["element_ref"]
            previous_lineage = previous_selection["capture_lineage"]
            if (
                previous_selection.get("semantic_action") != "fill_field"
                or previous_selection.get("asset_id") != asset.get("asset_id")
                or previous_selection.get("asset_content_sha256") != bundle.asset_content_sha256
                or asset.get("asset_id") != current_observation.get("asset_id")
                or previous_lineage.get("capture_id") == bundle.capture_id
            ):
                raise ValueError
            transitions = [
                item for item in asset["transitions"]
                if item.get("transition_id") == transition_id
            ]
            if len(transitions) != 1 or transitions[0].get("semantic_action") != "fill_field":
                raise ValueError
            transition = transitions[0]
            transition_fields = reviewed_action_parameter_fields(transition)
            previous_fields = reviewed_action_parameter_fields(previous_selection)
            if (
                set(transition_fields) != {"text_parameters_ref"}
                or previous_fields != transition_fields
                or transition.get("element_ref") != element_ref
            ):
                raise ValueError
            anchor = _unique_anchor(asset, str(element_ref))
            target_field_id = transition_fields["text_parameters_ref"]["target_field_id"]
            if anchor.get("text_field_id") != target_field_id:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError("post text field approved target is unavailable") from None

        recognition_bytes = dict(bundle.recognition_by_anchor).get(str(anchor["anchor_id"]))
        if recognition_bytes is None:
            raise ValueError("post text field current target is unmatched")
        try:
            candidates, local_grounding = _parse_recognition(_json_mapping(recognition_bytes))
            matches = _matching_pairs(
                candidates,
                local_grounding,
                anchor,
                allow_text_identity_on_interactive_role=True,
            )
            if len(matches) != 1:
                raise ValueError
            candidate, local = matches[0]
            confidence = min(float(candidate.score), float(local.confidence))
            if (
                not candidates.candidates
                or candidates.candidates[0].candidate_id != candidate.candidate_id
                or candidates.recommended_candidate_id != candidate.candidate_id
                or local_grounding.recommended_candidate_id != candidate.candidate_id
                or confidence < self._minimum_confidence
                or _rank_margin([pair[0] for pair in matches]) < self._minimum_score_margin
            ):
                raise ValueError
            projected_candidate = replace(
                candidate,
                element_id=str(element_ref),
                element=replace(candidate.element, element_id=str(element_ref)),
            )
            projected_candidates = replace(
                candidates,
                candidates=[projected_candidate],
                margin_to_second=_rank_margin([projected_candidate]),
            )
            projected_local = replace(
                local_grounding,
                results=[replace(local, element_id=str(element_ref))],
            )
            decision = decide_pre_click(
                goal=projected_candidates.goal,
                candidates=projected_candidates,
                grounding=projected_local,
            )
            candidate_decision = next(
                item for item in decision.candidate_decisions
                if item.candidate_id == candidate.candidate_id
            )
            if candidate_decision.click_point is None:
                raise ValueError
            bbox = _candidate_bbox(projected_candidate)
            point = dict(candidate_decision.click_point)
            grounding = {
                "bbox": bbox,
                "click_point": point,
                "viewport_size": current_observation["viewport_size"],
            }
            validate_reviewed_action_grounding_geometry(transition, grounding)
        except (KeyError, StopIteration, TypeError, ValueError):
            raise ValueError("post text field current grounding is unavailable") from None

        self.read_cached_grounded_image(
            session_id=session_id,
            asset_id=current_observation["asset_id"],
            asset_content_sha256=bundle.asset_content_sha256,
            target_window_handle=bundle.target_window_handle,
            target_process_id=bundle.target_process_id,
            capture_lineage={
                key: current_observation[key]
                for key in ("capture_id", "screenshot_sha256", "viewport_size")
            },
        )
        capture = _json_mapping(bundle.text_capture_json)
        rect = tuple(capture["window_rect"][key] for key in ("x", "y", "width", "height"))
        target_bbox = tuple(bbox[key] for key in ("x", "y", "w", "h"))
        click_point = tuple(point[key] for key in ("x", "y"))
        if self._text_field_reader is None:
            from app.agent.windows_text_field_reader import WindowsTextFieldReader

            self._text_field_reader = WindowsTextFieldReader(
                window_manager=self._window_manager,
                native_identity_reader=self._native_identity_reader,
            )
        actual = self._text_field_reader.read_field(
            target_field_id=target_field_id,
            capture_id=bundle.capture_id,
            target_window_handle=bundle.target_window_handle,
            target_process_id=bundle.target_process_id,
            process_create_time=capture["native_identity"]["process_create_time"],
            window_rect=rect,
            target_bbox=target_bbox,
            click_point=click_point,
        )
        if (
            type(actual) is not TextFieldSnapshot
            or actual.capture_id != bundle.capture_id
            or actual.observed_at_ns <= capture["captured_at_ns"]
            or actual.identity.target_field_id != target_field_id
            or actual.identity.window_handle != bundle.target_window_handle
            or actual.identity.process_id != bundle.target_process_id
            or actual.identity.process_create_time != capture["native_identity"]["process_create_time"]
            or actual.identity.window_rect != rect
        ):
            raise ValueError("post text field result differs from the current capture binding")
        x, y, width, height = actual.identity.control_bbox
        if not (
            x <= target_bbox[0]
            and y <= target_bbox[1]
            and target_bbox[0] + target_bbox[2] <= x + width
            and target_bbox[1] + target_bbox[3] <= y + height
        ):
            raise ValueError("post text field geometry differs from the current target")
        return actual

    def read_cached_grounded_image(
        self,
        *,
        session_id: str,
        asset_id: str,
        asset_content_sha256: str,
        target_window_handle: int,
        target_process_id: int,
        capture_lineage: Mapping[str, Any],
    ) -> bytes:
        """只读返回与完整 grounded 绑定一致的缓存 PNG，不触发新 capture。"""
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(asset_id, str)
            or not asset_id
            or not isinstance(asset_content_sha256, str)
            or len(asset_content_sha256) != 64
            or type(target_window_handle) is not int
            or target_window_handle <= 0
            or type(target_process_id) is not int
            or target_process_id <= 0
            or not isinstance(capture_lineage, Mapping)
            or set(capture_lineage) != {
                "capture_id",
                "screenshot_sha256",
                "viewport_size",
            }
        ):
            raise ValueError("cached grounded image binding is invalid")
        capture_id = capture_lineage.get("capture_id")
        screenshot_digest = capture_lineage.get("screenshot_sha256")
        viewport = capture_lineage.get("viewport_size")
        if (
            not isinstance(capture_id, str)
            or not capture_id
            or not isinstance(screenshot_digest, str)
            or len(screenshot_digest) != 64
            or not isinstance(viewport, Mapping)
            or set(viewport) != {"width", "height"}
            or type(viewport.get("width")) is not int
            or type(viewport.get("height")) is not int
            or viewport["width"] <= 0
            or viewport["height"] <= 0
        ):
            raise ValueError("cached grounded image lineage is invalid")
        key = (session_id, capture_id, screenshot_digest)
        with self._lock:
            bundle = self._cache.get(key)
        if (
            bundle is None
            or bundle.asset_content_sha256 != asset_content_sha256
            or bundle.target_window_handle != target_window_handle
            or bundle.target_process_id != target_process_id
            or bundle.viewport_size != (viewport["width"], viewport["height"])
        ):
            raise ValueError("cached grounded image is unavailable")
        try:
            asset = _json_mapping(bundle.asset_json)
            if (
                asset.get("asset_id") != asset_id
                or content_sha256(asset) != asset_content_sha256
                or _json_bytes(asset) != bundle.asset_json
            ):
                raise ValueError("cached grounded image asset binding changed")
            image_bytes = Path(bundle.image_path).read_bytes()
            if sha256(image_bytes).hexdigest() != screenshot_digest:
                raise ValueError("cached grounded image hash changed")
            from PIL import Image

            with Image.open(BytesIO(image_bytes)) as image:
                actual_size = (int(image.width), int(image.height))
                if image.format != "PNG":
                    raise ValueError("cached grounded image is not PNG")
                image.verify()
            if actual_size != bundle.viewport_size:
                raise ValueError("cached grounded image viewport changed")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("cached grounded image is unreadable") from exc
        with self._lock:
            if self._cache.get(key) != bundle:
                raise ValueError("cached grounded image binding changed")
        return bytes(image_bytes)

    def _bundle_for_projected(
        self,
        *,
        session_id: str,
        current_observation: Mapping[str, Any],
    ) -> _CurrentEvidenceBundle:
        capture_id = current_observation.get("capture_id")
        screenshot_digest = current_observation.get("screenshot_sha256")
        with self._lock:
            bundle = self._cache.get((session_id, capture_id, screenshot_digest))
        if (
            bundle is None
            or bundle.current_observation_json != _json_bytes(current_observation)
        ):
            raise ValueError("projected current evidence bundle is unavailable")
        return bundle

    def _find_bundle(
        self,
        *,
        session_id: str,
        selection: Mapping[str, Any],
        current_observation: Mapping[str, Any],
    ) -> _CurrentEvidenceBundle | None:
        lineage = selection.get("capture_lineage")
        if not isinstance(lineage, Mapping):
            return None
        capture_id = lineage.get("capture_id")
        screenshot_digest = lineage.get("screenshot_sha256")
        expected_asset_hash = selection.get("asset_content_sha256")
        if (
            current_observation.get("capture_id") != capture_id
            or current_observation.get("screenshot_sha256") != screenshot_digest
            or current_observation.get("viewport_size") != lineage.get("viewport_size")
            or current_observation.get("expected_asset_content_sha256") != expected_asset_hash
        ):
            return None
        try:
            current_bytes = _json_bytes(current_observation)
        except ValueError:
            return None
        with self._lock:
            item = self._cache.get((session_id, capture_id, screenshot_digest))
        if (
            item is None
            or item.asset_content_sha256 != expected_asset_hash
            or item.current_observation_json != current_bytes
        ):
            return None
        return item

    def _find_bundle_for_visibility(
        self,
        *,
        session_id: str,
        capture_lineage: Mapping[str, Any],
    ) -> _CurrentEvidenceBundle | None:
        if set(capture_lineage) != {"capture_id", "screenshot_sha256", "viewport_size"}:
            return None
        capture_id = capture_lineage.get("capture_id")
        screenshot_digest = capture_lineage.get("screenshot_sha256")
        viewport = capture_lineage.get("viewport_size")
        if (
            not isinstance(capture_id, str)
            or not isinstance(screenshot_digest, str)
            or not isinstance(viewport, Mapping)
            or set(viewport) != {"width", "height"}
        ):
            return None
        with self._lock:
            bundle = self._cache.get((session_id, capture_id, screenshot_digest))
        if bundle is None or viewport != {
            "width": bundle.viewport_size[0],
            "height": bundle.viewport_size[1],
        }:
            return None
        return bundle


class ExistingWindowsCurrentEvidenceVisibilityChecker:
    """在底层 dispatch 前证明当前像素仍属于同一份 evidence。"""

    def __init__(
        self,
        *,
        evidence_adapter: ExistingWindowsCurrentEvidenceAdapter,
        delegate: Any | None = None,
    ) -> None:
        self._evidence_adapter = evidence_adapter
        self._screenshot_service = evidence_adapter._screenshot_service
        self._window_manager = evidence_adapter._window_manager
        self._delegate = delegate or ExistingWindowManagerVisibilityChecker(
            window_manager=self._window_manager
        )

    def check(
        self,
        *,
        session_id: str,
        capture_lineage: Mapping[str, Any],
        target_window_handle: int,
        click_point: tuple[float, float],
        target_bbox: tuple[float, float, float, float],
    ) -> Mapping[str, Any]:
        bundle = self._evidence_adapter._find_bundle_for_visibility(
            session_id=session_id,
            capture_lineage=capture_lineage,
        )
        if bundle is None:
            return self._blocked("current_evidence_missing")
        expected_identity = (
            bundle.target_window_handle,
            bundle.target_process_id,
            bundle.viewport_size,
        )
        expected_native_identity: dict[str, object] | None = None
        if bundle.native_identity_json is not None:
            try:
                expected_native_identity = _json_mapping(bundle.native_identity_json)
                before_native_identity = _validated_native_identity(
                    self._evidence_adapter._native_identity_reader.read_identity(
                        target_window_handle
                    ),
                    target_window_handle=target_window_handle,
                    process_id=bundle.target_process_id,
                    expected_executable_path=str(
                        expected_native_identity["executable_path"]
                    ),
                )
            except Exception:
                return self._blocked("native_identity_changed")
            if before_native_identity != expected_native_identity:
                return self._blocked("native_identity_changed")
        try:
            before = _bound_identity(
                self._window_manager.get_bound_window(),
                target_window_handle=target_window_handle,
            )
            if before != expected_identity:
                return self._blocked(
                    "bound_window_changed",
                    bound_window_handle=before[0],
                )
            capture = self._screenshot_service.capture_window(
                save_image=True,
                focus_window=False,
                purpose="runtime-pre-dispatch-freshness",
            )
            after = _bound_identity(
                self._window_manager.get_bound_window(),
                target_window_handle=target_window_handle,
            )
            if after != expected_identity:
                return self._blocked(
                    "bound_window_changed",
                    bound_window_handle=after[0],
                )
            if expected_native_identity is not None:
                after_native_identity = _validated_native_identity(
                    self._evidence_adapter._native_identity_reader.read_identity(
                        target_window_handle
                    ),
                    target_window_handle=target_window_handle,
                    process_id=bundle.target_process_id,
                    expected_executable_path=str(
                        expected_native_identity["executable_path"]
                    ),
                )
                if after_native_identity != expected_native_identity:
                    return self._blocked("native_identity_changed")
            _, image_bytes, viewport = _validated_saved_capture(
                capture,
                expected_size=bundle.viewport_size,
            )
        except Exception:
            return self._blocked("fresh_capture_failed")
        if viewport != {
            "width": bundle.viewport_size[0],
            "height": bundle.viewport_size[1],
        }:
            return self._blocked(
                "viewport_changed",
                bound_window_handle=target_window_handle,
            )
        fresh_screenshot_sha256 = sha256(image_bytes).hexdigest()
        try:
            cached_image_bytes = Path(bundle.image_path).read_bytes()
            if sha256(cached_image_bytes).hexdigest() != bundle.screenshot_sha256:
                return self._blocked(
                    "cached_capture_changed",
                    bound_window_handle=target_window_handle,
                )
            cached_target_region_sha256 = _target_region_sha256(
                cached_image_bytes,
                click_point=click_point,
                target_bbox=target_bbox,
            )
            fresh_target_region_sha256 = _target_region_sha256(
                image_bytes,
                click_point=click_point,
                target_bbox=target_bbox,
            )
        except Exception:
            return self._blocked(
                "target_region_unavailable",
                bound_window_handle=target_window_handle,
            )
        if fresh_target_region_sha256 != cached_target_region_sha256:
            return self._blocked(
                "target_region_changed",
                bound_window_handle=target_window_handle,
            )
        result = dict(
            self._delegate.check(
                session_id=session_id,
                capture_lineage=capture_lineage,
                target_window_handle=target_window_handle,
                click_point=click_point,
                target_bbox=target_bbox,
            )
        )
        result["freshness"] = {
            "status": "allowed",
            "reason": "target_region_unchanged",
            "full_frame_status": (
                "unchanged"
                if fresh_screenshot_sha256 == bundle.screenshot_sha256
                else "changed"
            ),
        }
        return result

    @staticmethod
    def _blocked(
        reason: str,
        *,
        bound_window_handle: int | None = None,
    ) -> dict[str, Any]:
        return {
            "bound_window_handle": bound_window_handle,
            "point_visibility": {"allowed": False},
            "freshness": {"status": "blocked", "reason": reason},
        }


def _bound_identity(bound: Any, *, target_window_handle: int) -> tuple[int, int, tuple[int, int]]:
    if bound is None:
        raise ValueError("no server-owned bound window is available")
    try:
        handle = int(bound.handle)
        process_id = int(bound.process_id)
        width = int(bound.rect.right) - int(bound.rect.left)
        height = int(bound.rect.bottom) - int(bound.rect.top)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("bound window identity is unavailable") from exc
    if handle != target_window_handle or process_id <= 0 or width <= 0 or height <= 0:
        raise ValueError("bound window does not match the server target")
    return handle, process_id, (width, height)


def _validated_saved_capture(
    capture: Any,
    *,
    expected_size: tuple[int, int],
) -> tuple[Path, bytes, dict[str, int]]:
    if not isinstance(capture, Mapping):
        raise ValueError("passive screenshot result is malformed")
    image_path_value = capture.get("image_path")
    if not isinstance(image_path_value, str) or not image_path_value.strip():
        raise ValueError("passive screenshot did not persist current evidence")
    image_path = Path(image_path_value).resolve()
    try:
        image_bytes = image_path.read_bytes()
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as image:
            actual_size = (int(image.width), int(image.height))
    except Exception as exc:
        raise ValueError("persisted passive screenshot is unreadable") from exc
    reported_size = (capture.get("image_width"), capture.get("image_height"))
    window_size = capture.get("window_size")
    if not isinstance(window_size, Mapping):
        raise ValueError("passive screenshot viewport metadata is malformed")
    reported_window_size = (window_size.get("width"), window_size.get("height"))
    if (
        not image_bytes
        or capture.get("roi") is not None
        or actual_size != expected_size
        or reported_size != actual_size
        or reported_window_size != actual_size
    ):
        raise ValueError("passive screenshot viewport does not match the bound window")
    return image_path, image_bytes, {"width": actual_size[0], "height": actual_size[1]}


def _target_region_sha256(
    image_bytes: bytes,
    *,
    click_point: tuple[float, float],
    target_bbox: tuple[float, float, float, float],
    margin: int = 8,
) -> str:
    """比较完整目标框及少量边缘，允许无关区域发生动态变化。"""
    from PIL import Image

    with Image.open(BytesIO(image_bytes)) as image:
        width, height = int(image.width), int(image.height)
        x, y = int(click_point[0]), int(click_point[1])
        bbox_x, bbox_y, bbox_w, bbox_h = target_bbox
        values = (bbox_x, bbox_y, bbox_w, bbox_h)
        if (
            any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in values
            )
            or any(not math.isfinite(float(value)) for value in values)
            or bbox_w <= 0
            or bbox_h <= 0
            or not (
                0 <= bbox_x < width
                and 0 <= bbox_y < height
                and bbox_x + bbox_w <= width
                and bbox_y + bbox_h <= height
            )
            or not (bbox_x <= x <= bbox_x + bbox_w)
            or not (bbox_y <= y <= bbox_y + bbox_h)
        ):
            raise ValueError("target bbox does not contain the click point in the viewport")
        box = (
            max(0, math.floor(bbox_x) - margin),
            max(0, math.floor(bbox_y) - margin),
            min(width, math.ceil(bbox_x + bbox_w) + margin),
            min(height, math.ceil(bbox_y + bbox_h) + margin),
        )
        region = image.convert("RGB").crop(box)
        encoded = (
            f"{box[0]},{box[1]},{box[2]},{box[3]}:".encode("ascii")
            + region.tobytes()
        )
    return sha256(encoded).hexdigest()


def _require_unchanged_screenshot(image_path: Path, *, expected_sha256: str) -> None:
    try:
        current_sha256 = sha256(image_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("persisted runtime screenshot changed during recognition") from exc
    if current_sha256 != expected_sha256:
        raise ValueError("persisted runtime screenshot changed during recognition")


def _validated_uia_snapshot(
    snapshot: Any,
    *,
    expected_identity: tuple[int, int, tuple[int, int]],
) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping) or snapshot.get("status") != "ok":
        raise ValueError("current UIA snapshot is unavailable")
    window = snapshot.get("window")
    if not isinstance(window, Mapping):
        raise ValueError("current UIA snapshot window identity is unavailable")
    bbox = window.get("bbox")
    try:
        identity = (
            int(window["handle"]),
            int(window["process_id"]),
            (int(bbox["w"]), int(bbox["h"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("current UIA snapshot window identity is malformed") from exc
    if identity != expected_identity:
        raise ValueError("current UIA snapshot does not match the bound capture epoch")
    return deepcopy(dict(snapshot))


def _validated_origin_fact(
    fact: Any,
    *,
    target_window_handle: int,
    process_id: int,
) -> str | None:
    if not isinstance(fact, Mapping) or fact.get("status") != "observed":
        return None
    if fact.get("target_window_handle") != target_window_handle:
        return None
    if fact.get("bound_process_id") != process_id:
        return None
    origin = fact.get("origin")
    return origin if isinstance(origin, str) and origin.strip() else None


def _validated_native_identity(
    fact: Any,
    *,
    target_window_handle: int,
    process_id: int,
    expected_executable_path: str | None,
) -> dict[str, object]:
    identity = validate_native_identity_fact(
        fact,
        target_window_handle=target_window_handle,
        expected_process_id=process_id,
        expected_executable_path=expected_executable_path,
    )
    if identity is None:
        raise ValueError("current native process identity is unavailable or mismatched")
    return identity


def _all_unique_anchors(asset: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    anchors: dict[str, Mapping[str, Any]] = {}
    for state in asset.get("states", []):
        if not isinstance(state, Mapping):
            continue
        for anchor in state.get("identity_anchors", []):
            if not isinstance(anchor, Mapping):
                continue
            anchor_id = str(anchor.get("anchor_id") or "")
            if anchor_id and anchor_id not in anchors:
                anchors[anchor_id] = anchor
    return list(anchors.values())


def _unique_anchor(asset: Mapping[str, Any], anchor_id: str) -> Mapping[str, Any]:
    matches = [
        anchor
        for state in asset.get("states", [])
        if isinstance(state, Mapping)
        for anchor in state.get("identity_anchors", [])
        if isinstance(anchor, Mapping) and anchor.get("anchor_id") == anchor_id
    ]
    if len(matches) != 1:
        raise ValueError("reviewed target anchor must exist exactly once")
    return matches[0]


def _matching_pairs(
    candidates: CandidateRankResult,
    local: LocalGroundingResult,
    anchor: Mapping[str, Any],
    *,
    contextual_apply_alias: bool = False,
    allow_text_identity_on_interactive_role: bool = False,
) -> list[tuple[RecognitionCandidate, LocalGroundingCandidateResult]]:
    expected_goal = _normalized_text(str(anchor.get("label") or ""))
    if (
        not expected_goal
        or _normalized_text(candidates.goal) != expected_goal
        or _normalized_text(local.goal) != expected_goal
    ):
        return []
    local_by_id = {item.candidate_id: item for item in local.results}
    matches: list[tuple[RecognitionCandidate, LocalGroundingCandidateResult]] = []
    for candidate in candidates.candidates:
        grounded = local_by_id.get(candidate.candidate_id)
        if (
            candidate.eligible
            and grounded is not None
            and grounded.status == "grounded"
            and grounded.confidence >= 0.0
            and _label_matches(
                candidate,
                str(anchor.get("label") or ""),
                contextual_apply_alias=contextual_apply_alias,
            )
            and _role_matches(
                candidate.role,
                str(anchor.get("kind") or ""),
                allow_text_identity_on_interactive_role=allow_text_identity_on_interactive_role,
                allow_text_field_role=isinstance(anchor.get("text_field_id"), str)
                and bool(anchor["text_field_id"].strip()),
            )
        ):
            matches.append((candidate, grounded))
    return matches


def _label_matches(
    candidate: RecognitionCandidate,
    label: str,
    *,
    contextual_apply_alias: bool = False,
) -> bool:
    expected = _normalized_text(label)
    if not expected:
        return False
    if expected in {
        _normalized_text(candidate.label),
        _normalized_text(candidate.text),
        _normalized_text(candidate.element.label),
        _normalized_text(candidate.element.text),
    }:
        return True
    return (
        contextual_apply_alias
        and expected.split()[-1:] == ["apply"]
        and any(
            value.startswith("apply for ")
            for value in (
                _normalized_text(candidate.label),
                _normalized_text(candidate.element.label),
            )
        )
    )


def _anchor_allows_contextual_apply_alias(
    asset: Mapping[str, Any],
    anchor: Mapping[str, Any],
) -> bool:
    anchor_id = str(anchor.get("anchor_id") or "")
    return any(
        _selected_transition_allows_contextual_apply_alias(
            transition,
            anchor_id=anchor_id,
            element_ref=anchor_id,
        )
        for transition in asset.get("transitions", [])
    )


def _selected_transition_allows_contextual_apply_alias(
    transition: Any,
    *,
    anchor_id: str,
    element_ref: str,
) -> bool:
    return (
        isinstance(transition, Mapping)
        and bool(anchor_id)
        and element_ref == anchor_id
        and str(transition.get("element_ref") or "") == anchor_id
        and str(transition.get("semantic_action") or "").casefold() == "open_apply_flow"
    )


def _role_matches(
    role: str,
    anchor_kind: str,
    *,
    allow_text_identity_on_interactive_role: bool = False,
    allow_text_field_role: bool = False,
) -> bool:
    normalized_role = _normalized_text(role)
    normalized_kind = _normalized_text(anchor_kind)
    # 输入角色只匹配显式审核的文字字段，不扩大普通点击或文本锚点。
    if normalized_role == "input" and normalized_kind in {"control", "region"}:
        return allow_text_field_role
    interactive_roles = {
        "button",
        "card",
        "checkbox",
        "combobox",
        "control",
        "link",
        "list item",
        "listitem",
        "menuitem",
        "radio",
        "tab",
        "toggle",
    }
    if normalized_kind == "control":
        return normalized_role in interactive_roles
    if normalized_kind == "text":
        return normalized_role in {"heading", "label", "text"} or (
            allow_text_identity_on_interactive_role and normalized_role in interactive_roles
        )
    if normalized_kind == "region":
        return normalized_role in {"group", "list", "pane", "region", "section"}
    return normalized_role == normalized_kind


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())


def _candidate_bbox(candidate: RecognitionCandidate) -> dict[str, int]:
    if candidate.refined_bbox is not None:
        return {
            "x": int(candidate.refined_bbox["x"]),
            "y": int(candidate.refined_bbox["y"]),
            "w": int(candidate.refined_bbox.get("w", candidate.refined_bbox.get("width", 0))),
            "h": int(candidate.refined_bbox.get("h", candidate.refined_bbox.get("height", 0))),
        }
    return candidate.element.bbox.to_dict()


def _rank_margin(candidates: list[RecognitionCandidate]) -> float:
    if not candidates:
        return 0.0
    if len(candidates) == 1:
        return round(float(candidates[0].score), 4)
    return round(float(candidates[0].score) - float(candidates[1].score), 4)


def _validate_ranked_candidates(
    candidates: list[RecognitionCandidate],
    *,
    expected_eligible: bool,
) -> None:
    if [item.rank for item in candidates] != list(range(1, len(candidates) + 1)):
        raise ValueError("candidate ranks are not contiguous")
    if any(item.eligible is not expected_eligible for item in candidates):
        raise ValueError("candidate eligibility does not match its ranking collection")
    if any(left.score < right.score for left, right in zip(candidates, candidates[1:])):
        raise ValueError("candidate ranking order is inconsistent")


def _parse_recognition(payload: Mapping[str, Any]) -> tuple[CandidateRankResult, LocalGroundingResult]:
    if payload.get("contract_version") != "recognition_plan_v1":
        raise ValueError("current recognition contract mismatch")
    candidates = _parse_candidate_result(_strict_mapping(payload.get("candidate_result")))
    local = _parse_local_grounding(_strict_mapping(payload.get("narrow_search_result")))
    if len({item.candidate_id for item in candidates.candidates}) != len(candidates.candidates):
        raise ValueError("current recognition candidate identities are ambiguous")
    if len({item.candidate_id for item in local.results}) != len(local.results):
        raise ValueError("current grounding candidate identities are ambiguous")
    candidate_by_id = {item.candidate_id: item for item in candidates.candidates}
    for grounded in local.results:
        candidate = candidate_by_id.get(grounded.candidate_id)
        if candidate is None or candidate.element_id != grounded.element_id:
            raise ValueError("current grounding identities do not match ranked candidates")
    return candidates, local


def _parse_candidate_result(value: Mapping[str, Any]) -> CandidateRankResult:
    required = {
        "contract_version",
        "goal",
        "top_k",
        "candidates",
        "rejected",
        "recommended_candidate_id",
        "margin_to_second",
        "summary",
    }
    if set(value) != required or value.get("contract_version") != "candidate_rank_v1":
        raise ValueError("candidate result is malformed")
    candidates = [_parse_candidate(_strict_mapping(item)) for item in _strict_list(value["candidates"])]
    rejected = [_parse_candidate(_strict_mapping(item)) for item in _strict_list(value["rejected"])]
    serialized_margin = value["margin_to_second"]
    if serialized_margin is not None:
        _number(serialized_margin, minimum=0.0, maximum=1.0)
    all_candidate_ids = [item.candidate_id for item in [*candidates, *rejected]]
    if len(set(all_candidate_ids)) != len(all_candidate_ids):
        raise ValueError("candidate identities are ambiguous")
    all_element_ids = [item.element_id for item in [*candidates, *rejected]]
    if len(set(all_element_ids)) != len(all_element_ids):
        raise ValueError("candidate element identities are ambiguous")
    _validate_ranked_candidates(candidates, expected_eligible=True)
    _validate_ranked_candidates(rejected, expected_eligible=False)
    recommended = candidates[0].candidate_id if candidates else None
    if _optional_text(value["recommended_candidate_id"]) != recommended:
        raise ValueError("candidate recommendation is inconsistent")
    return CandidateRankResult(
        contract_version="candidate_rank_v1",
        goal=_text(value["goal"]),
        top_k=_integer(value["top_k"], minimum=1),
        candidates=candidates,
        rejected=rejected,
        recommended_candidate_id=recommended,
        margin_to_second=_rank_margin(candidates) if candidates else None,
        summary=dict(_strict_mapping(value["summary"])),
    )


def _parse_candidate(value: Mapping[str, Any]) -> RecognitionCandidate:
    required = {
        "candidate_id",
        "rank",
        "element_id",
        "label",
        "role",
        "text",
        "score",
        "eligible",
        "reasons",
        "score_breakdown",
        "element",
        "refined_bbox",
        "bbox_refine_reason",
    }
    if set(value) != required or type(value["eligible"]) is not bool:
        raise ValueError("candidate is malformed")
    breakdown_value = _strict_mapping(value["score_breakdown"])
    breakdown_keys = {
        "text_similarity",
        "role_score",
        "policy_score",
        "confidence_score",
        "state_score",
        "screen_reading_score",
        "ad_penalty",
        "blocked_penalty",
        "total",
    }
    if set(breakdown_value) != breakdown_keys:
        raise ValueError("candidate score breakdown is malformed")
    breakdown = ScoreBreakdown(
        **{
            key: _number(breakdown_value[key], minimum=0.0, maximum=1.0)
            for key in breakdown_keys - {"total"}
        }
    )
    if abs(breakdown.total() - _number(breakdown_value["total"], minimum=0.0, maximum=1.0)) > 0.001:
        raise ValueError("candidate score total is inconsistent")
    score = _number(value["score"], minimum=0.0, maximum=1.0)
    if breakdown.total() != round(score, 4):
        raise ValueError("candidate score does not match its breakdown")
    refined = value["refined_bbox"]
    refined_bbox = _parse_bbox_mapping(_strict_mapping(refined)) if refined is not None else None
    element = _parse_page_element(_strict_mapping(value["element"]))
    element_id = _text(value["element_id"])
    if element.element_id != element_id:
        raise ValueError("candidate element identity is inconsistent")
    return RecognitionCandidate(
        candidate_id=_text(value["candidate_id"]),
        rank=_integer(value["rank"], minimum=1),
        element_id=element_id,
        label=_text(value["label"], allow_empty=True),
        role=_text(value["role"], allow_empty=True),
        text=_text(value["text"], allow_empty=True),
        score=score,
        eligible=value["eligible"],
        reasons=[_text(item, allow_empty=True) for item in _strict_list(value["reasons"])],
        score_breakdown=breakdown,
        element=element,
        refined_bbox=refined_bbox,
        bbox_refine_reason=_optional_text(value["bbox_refine_reason"]),
    )


def _parse_page_element(value: Mapping[str, Any]) -> PageElement:
    required = {
        "element_id",
        "label",
        "role",
        "interaction_type",
        "description",
        "text",
        "bbox",
        "semantic_bbox",
        "click_point",
        "click_strategy",
        "possible_destinations",
        "verification_hints",
        "interaction_policy",
        "fusion_confidence",
        "coordinate_confidence",
        "memory_key",
        "sources",
        "source_region_ids",
        "source_text_ids",
        "evidence",
    }
    if set(value) != required:
        raise ValueError("page element is malformed")
    semantic = value["semantic_bbox"]
    verification = _strict_mapping(value["verification_hints"])
    policy = _strict_mapping(value["interaction_policy"])
    if set(verification) != {"expected_changes", "target_scope"}:
        raise ValueError("verification hints are malformed")
    if set(policy) != {"allowed", "zone_type", "priority", "ad_risk", "reasons"}:
        raise ValueError("interaction policy is malformed")
    if type(policy["allowed"]) is not bool:
        raise ValueError("interaction policy allowed flag is malformed")
    point = _parse_point(_strict_mapping(value["click_point"]))
    return PageElement(
        element_id=_text(value["element_id"]),
        label=_text(value["label"], allow_empty=True),
        role=_text(value["role"], allow_empty=True),
        interaction_type=_text(value["interaction_type"], allow_empty=True),
        description=_text(value["description"], allow_empty=True),
        text=_text(value["text"], allow_empty=True),
        bbox=BBox(**_parse_bbox_mapping(_strict_mapping(value["bbox"]))),
        semantic_bbox=(
            BBox(**_parse_bbox_mapping(_strict_mapping(semantic)))
            if semantic is not None
            else None
        ),
        click_point=point,
        click_strategy=_text(value["click_strategy"], allow_empty=True),
        possible_destinations=[
            _text(item, allow_empty=True) for item in _strict_list(value["possible_destinations"])
        ],
        verification_hints=VerificationHints(
            expected_changes=[
                _text(item, allow_empty=True)
                for item in _strict_list(verification["expected_changes"])
            ],
            target_scope=_text(verification["target_scope"], allow_empty=True),
        ),
        interaction_policy=InteractionPolicy(
            allowed=policy["allowed"],
            zone_type=_text(policy["zone_type"], allow_empty=True),
            priority=_text(policy["priority"], allow_empty=True),
            ad_risk=_number(policy["ad_risk"], minimum=0.0, maximum=1.0),
            reasons=[_text(item, allow_empty=True) for item in _strict_list(policy["reasons"])],
        ),
        fusion_confidence=_number(value["fusion_confidence"], minimum=0.0, maximum=1.0),
        coordinate_confidence=_text(value["coordinate_confidence"], allow_empty=True),
        memory_key=_text(value["memory_key"], allow_empty=True),
        sources=[_text(item, allow_empty=True) for item in _strict_list(value["sources"])],
        source_region_ids=[
            _text(item, allow_empty=True) for item in _strict_list(value["source_region_ids"])
        ],
        source_text_ids=[
            _text(item, allow_empty=True) for item in _strict_list(value["source_text_ids"])
        ],
        evidence=dict(_strict_mapping(value["evidence"])),
    )


def _parse_local_grounding(value: Mapping[str, Any]) -> LocalGroundingResult:
    required = {"contract_version", "goal", "results", "recommended_candidate_id", "summary"}
    if set(value) != required or value.get("contract_version") != "narrow_search_v1":
        raise ValueError("local grounding result is malformed")
    results = [_parse_local_result(_strict_mapping(item)) for item in _strict_list(value["results"])]
    successful = [item for item in results if item.status == "grounded"]
    recommended = successful[0].candidate_id if successful else (results[0].candidate_id if results else None)
    if _optional_text(value["recommended_candidate_id"]) != recommended:
        raise ValueError("local grounding recommendation is inconsistent")
    return LocalGroundingResult(
        contract_version="narrow_search_v1",
        goal=_text(value["goal"]),
        results=results,
        recommended_candidate_id=recommended,
        summary=dict(_strict_mapping(value["summary"])),
    )


def _parse_local_result(value: Mapping[str, Any]) -> LocalGroundingCandidateResult:
    required = {
        "candidate_id",
        "element_id",
        "status",
        "crop_path",
        "crop_bbox",
        "refined_click_point",
        "coordinate_source",
        "confidence",
        "matched_text",
        "matched_text_bbox",
        "reasons",
    }
    if set(value) != required:
        raise ValueError("local grounding candidate is malformed")
    crop = value["crop_bbox"]
    point = value["refined_click_point"]
    matched_bbox = value["matched_text_bbox"]
    return LocalGroundingCandidateResult(
        candidate_id=_text(value["candidate_id"]),
        element_id=_text(value["element_id"]),
        status=_text(value["status"]),
        crop_path=_optional_text(value["crop_path"]),
        crop_bbox=_parse_bbox_mapping(_strict_mapping(crop)) if crop is not None else None,
        refined_click_point=_parse_point(_strict_mapping(point)) if point is not None else None,
        coordinate_source=_text(value["coordinate_source"], allow_empty=True),
        confidence=_number(value["confidence"], minimum=0.0, maximum=1.0),
        matched_text=_optional_text(value["matched_text"]),
        matched_text_bbox=(
            _parse_bbox_mapping(_strict_mapping(matched_bbox))
            if matched_bbox is not None
            else None
        ),
        reasons=[_text(item, allow_empty=True) for item in _strict_list(value["reasons"])],
    )


def _parse_bbox_mapping(value: Mapping[str, Any]) -> dict[str, int]:
    if set(value) != {"x", "y", "w", "h"}:
        raise ValueError("bbox is malformed")
    result = {key: _integer(value[key], minimum=0) for key in ("x", "y", "w", "h")}
    if result["w"] <= 0 or result["h"] <= 0:
        raise ValueError("bbox size is invalid")
    return result


def _parse_point(value: Mapping[str, Any]) -> dict[str, int]:
    if set(value) != {"x", "y"}:
        raise ValueError("point is malformed")
    return {key: _integer(value[key], minimum=0) for key in ("x", "y")}


def _strict_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("current recognition value must be an object")
    return value


def _strict_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("current recognition value must be an array")
    return value


def _text(value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError("current recognition text is invalid")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _text(value)


def _integer(value: Any, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError("current recognition integer is invalid")
    return value


def _number(value: Any, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("current recognition number is invalid")
    number = float(value)
    if number < minimum or number > maximum:
        raise ValueError("current recognition number is out of range")
    return number


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("current evidence serialization failed") from exc


def _json_mapping(value: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("current evidence cache is malformed") from exc
    if not isinstance(decoded, dict):
        raise ValueError("current evidence cache must contain an object")
    return decoded


def _run_existing_read_only_recognition(
    *,
    image_path: str,
    goal: str,
    provider_mode: str | None,
    uia_snapshot: Mapping[str, Any],
    vision_configuration: VisionConfigurationSnapshot | None = None,
    semantic_action: str | None = None,
    control_target: dict | None = None,
    scroll_parameters: dict | None = None,
) -> Mapping[str, Any]:
    if semantic_action == "scroll_region":
        from app.operation.recognition.scroll_grounding import recognize_current_scroll
        if control_target is not None:
            raise ValueError("scroll region cannot use a button identity target")
        return recognize_current_scroll(image_path=image_path, goal=goal,
            uia_snapshot=dict(uia_snapshot), scroll_parameters=scroll_parameters)
    configuration = vision_configuration or load_formal_vision_configuration(resolve_vision_config_path(), provider_mode=provider_mode)
    if provider_mode is not None and provider_mode.strip().lower() != configuration.mode:
        raise ValueError("vision provider mode differs from the owned configuration")
    from app.api.models.request import VisionRecognitionPlanRequestModel
    from app.api.vision import recognition_plan
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot

    metadata = {"semantic_action": semantic_action} if semantic_action is not None else {}
    if control_target is not None:
        from app.operation.recognition.control_target import validate_control_target
        metadata["control_target"] = validate_control_target(control_target)
    request = VisionRecognitionPlanRequestModel(
        image_path=image_path,
        task="locate_element",
        goal=goal,
        provider_mode=configuration.mode,
        agent_mode="execute",
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata=metadata,
        observe_trace_path=None,
    )
    with pinned_uia_snapshot(uia_snapshot), pinned_vision_configuration(configuration):
        response = recognition_plan(request).model_dump(mode="json")
    from app.vision.request_control import ModelRequestError, current_model_request

    context = current_model_request()
    if response.get("success") is not True:
        error = response.get("error")
        code = error.get("code") if isinstance(error, Mapping) else None
        if isinstance(code, str) and code.startswith(("model_request_", "model_service_", "model_response_")):
            failure = ModelRequestError(code)
            proof = response.get("data")
            failure.computation_stopped = (
                code == "model_request_cancelled" and isinstance(proof, Mapping)
                and proof.get("computation_stopped") is True
            )
            raise failure
        if context is not None:
            context.check_cancelled()
        raise ValueError("read-only current recognition failed")
    if context is not None:
        context.check_cancelled()
    data = response.get("data")
    result = data.get("result") if isinstance(data, Mapping) else None
    if not isinstance(result, Mapping):
        raise ValueError("read-only current recognition returned no result")
    result_image_path = result.get("image_path")
    if not isinstance(result_image_path, str) or Path(result_image_path).resolve() != Path(image_path).resolve():
        raise ValueError("read-only current recognition image lineage mismatch")
    return dict(result)


def build_existing_windows_live_controller(
    project_root: str | Path,
    binding: ServerWorkflowBinding,
    provider_mode: str | None = None,
    grounding_policy: Mapping[str, Any] | None = None,
    *,
    intent_claim_store: RuntimeIntentClaimStore | None = None,
    action_learning_recorder: ActionLearningRecorder | None = None,
    vision_configuration: VisionConfigurationSnapshot | None = None,
) -> LiveController:
    project_root = Path(project_root).resolve()
    if intent_claim_store is not None and not isinstance(
        intent_claim_store,
        RuntimeIntentClaimStore,
    ):
        raise TypeError("intent_claim_store must be RuntimeIntentClaimStore or None")
    if (
        intent_claim_store is not None
        and intent_claim_store.project_root != project_root
    ):
        raise ValueError("intent_claim_store must use the same project root")
    if action_learning_recorder is not None and not isinstance(
        action_learning_recorder, ActionLearningRecorder,
    ):
        raise TypeError(
            "action_learning_recorder must be ActionLearningRecorder or None"
        )
    if (
        action_learning_recorder is not None
        and action_learning_recorder.project_root != project_root
    ):
        raise ValueError("action_learning_recorder must use the same project root")
    policy = dict(_DEFAULT_GROUNDING_POLICY if grounding_policy is None else grounding_policy)
    evidence = ExistingWindowsCurrentEvidenceAdapter(
        project_root=project_root,
        application_identity_key=binding.application_identity_key,
        provider_mode=provider_mode,
        grounding_policy=policy,
        vision_configuration=vision_configuration,
        capture_archive=(
            ActionLearningCaptureArchive(recorder=action_learning_recorder)
            if action_learning_recorder is not None
            else None
        ),
    )
    if intent_claim_store is None:
        receipt_store = RuntimeReceiptStore(project_root=project_root)
        claim_store = RuntimeIntentClaimStore(
            project_root=project_root,
            receipt_store=receipt_store,
        )
    else:
        claim_store = intent_claim_store
    return LiveController(
        binding=binding,
        asset_loader=ReviewedWorkflowAssetStore(project_root=project_root),
        observation_source=evidence,
        target_resolver=evidence,
        gate=ReviewedWorkflowGateAdapter(
            min_candidate_score=float(policy["minimum_confidence"]),
            min_margin=float(policy["minimum_score_margin"]),
        ),
        window_visibility_checker=ExistingWindowsCurrentEvidenceVisibilityChecker(
            evidence_adapter=evidence,
            delegate=ExistingWindowManagerVisibilityChecker(),
        ),
        backend=ExistingWindowsBackendAdapter(),
        intent_claim_store=claim_store,
        action_learning_recorder=action_learning_recorder,
        grounding_policy=policy,
    )


__all__ = [
    "ExistingWindowsCurrentEvidenceAdapter",
    "ExistingWindowsCurrentEvidenceVisibilityChecker",
    "build_existing_windows_live_controller",
]
