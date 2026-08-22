from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1
from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.agent.live_controller import (
    ExistingWindowManagerVisibilityChecker,
    LiveController,
    ServerWorkflowBinding,
)
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.windows_uia_origin_reader import WindowsUIAOriginReader
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
    image_path: str
    asset_json: bytes
    current_observation_json: bytes
    recognition_by_anchor: tuple[tuple[str, bytes], ...]


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
        window_manager: Any | None = None,
        recognition_runner: Callable[..., Mapping[str, Any]] | None = None,
        cache_limit: int = 8,
    ) -> None:
        if screenshot_service is None:
            from app.core.screenshot import screenshot_service as active_screenshot_service

            screenshot_service = active_screenshot_service
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        self._project_root = Path(project_root)
        self._application_identity_key = application_identity_key
        self._provider_mode = provider_mode
        self._screenshot_service = screenshot_service
        self._window_manager = window_manager
        self._origin_reader = origin_reader or WindowsUIAOriginReader(window_manager=window_manager)
        self._recognition_runner = recognition_runner or _run_existing_read_only_recognition
        self._cache_limit = max(1, int(cache_limit))
        self._cache: OrderedDict[tuple[str, str, str], _CurrentEvidenceBundle] = OrderedDict()
        self._lock = RLock()

    def create_initial(
        self,
        *,
        session_id: str,
        workflow: dict[str, Any],
        asset: dict[str, Any],
        target_window_handle: int,
    ):
        current = self._capture_current(
            session_id=session_id,
            asset=asset,
            target_window_handle=target_window_handle,
        )
        state_resolution = resolve_current_state(asset, current)
        return adapt_reviewed_context_to_agent_observation_v1(
            observation_id=f"observation.{uuid4().hex}",
            session_id=session_id,
            workflow_id=str(workflow["workflow_id"]),
            reviewed_asset=asset,
            current_observation=current,
            state_resolution=state_resolution,
            project_root=self._project_root,
            application_identity_key=self._application_identity_key,
        )

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

    def resolve(
        self,
        *,
        selection: dict[str, Any],
        current_observation: dict[str, Any],
    ) -> Mapping[str, Any]:
        bundle = self._find_bundle(selection=selection, current_observation=current_observation)
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
        matches = _matching_pairs(candidates, local_grounding, anchor)
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
            candidates=[
                projected_candidate if item.candidate_id == candidate.candidate_id else item
                for item in candidates.candidates
            ],
        )
        projected_local = replace(
            local_grounding,
            results=[
                replace(item, element_id=element_ref)
                if item.candidate_id == candidate.candidate_id
                else item
                for item in local_grounding.results
            ],
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
        margin = candidates.margin_to_second
        if margin is None:
            margin = 1.0 if len(candidates.candidates) == 1 else 0.0
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
        }
        transition = next(
            (
                item
                for item in asset.get("transitions", [])
                if item.get("transition_id") == selection.get("transition_id")
            ),
            None,
        )
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
        before = _bound_identity(
            self._window_manager.get_bound_window(),
            target_window_handle=target_window_handle,
        )
        capture = self._screenshot_service.capture_window(
            save_image=True,
            focus_window=False,
            purpose="runtime-observation",
        )
        after = _bound_identity(
            self._window_manager.get_bound_window(),
            target_window_handle=target_window_handle,
        )
        if before != after:
            raise ValueError("bound window binding drift detected during passive capture")
        image_path, image_bytes, viewport = _validated_saved_capture(capture, expected_size=before[2])
        screenshot_digest = sha256(image_bytes).hexdigest()
        capture_id = f"runtime-capture.{uuid4().hex}"
        origin_fact = self._origin_reader.read_origin(target_window_handle)
        observed_origin = _validated_origin_fact(
            origin_fact,
            target_window_handle=target_window_handle,
            process_id=before[1],
        )
        asset_hash = content_sha256(asset)
        application = asset.get("application") if isinstance(asset.get("application"), Mapping) else {}
        canonical_origin = str(application.get("canonical_origin") or "")
        recognition_by_anchor: list[tuple[str, bytes]] = []
        anchor_evidence: list[dict[str, object]] = []
        if observed_origin and observed_origin == canonical_origin:
            for anchor in _all_unique_anchors(asset):
                try:
                    raw = self._recognition_runner(
                        image_path=str(image_path),
                        goal=str(anchor["label"]),
                        provider_mode=self._provider_mode,
                    )
                    raw_bytes = _json_bytes(raw)
                except Exception as exc:
                    raise ValueError("current recognition failed for a reviewed anchor") from exc
                recognition_by_anchor.append((str(anchor["anchor_id"]), raw_bytes))
                try:
                    candidates, local = _parse_recognition(_json_mapping(raw_bytes))
                except ValueError:
                    continue
                matches = _matching_pairs(candidates, local, anchor)
                if len(matches) != 1:
                    continue
                candidate, grounded = matches[0]
                anchor_evidence.append(
                    {
                        "anchor_id": anchor["anchor_id"],
                        "matched": True,
                        "confidence": min(float(candidate.score), float(grounded.confidence)),
                        "evidence_ref": (
                            f"current-recognition:{capture_id}:{screenshot_digest[:16]}:"
                            f"{anchor['anchor_id']}:{candidate.candidate_id}"
                        ),
                    }
                )
        current = {
            "contract_version": "reviewed_workflow_current_observation_v1",
            "asset_id": asset["asset_id"],
            "expected_asset_content_sha256": asset_hash,
            "capture_id": capture_id,
            "screenshot_sha256": screenshot_digest,
            "viewport_size": viewport,
            "origin": observed_origin or "",
            "observed_anchor_evidence": anchor_evidence,
        }
        bundle = _CurrentEvidenceBundle(
            session_id=session_id,
            capture_id=capture_id,
            screenshot_sha256=screenshot_digest,
            asset_content_sha256=asset_hash,
            image_path=str(image_path),
            asset_json=_json_bytes(asset),
            current_observation_json=_json_bytes(current),
            recognition_by_anchor=tuple(recognition_by_anchor),
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

    def _find_bundle(
        self,
        *,
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
            matches = [
                item
                for (session_id, cached_capture, cached_sha), item in self._cache.items()
                if session_id
                and cached_capture == capture_id
                and cached_sha == screenshot_digest
                and item.asset_content_sha256 == expected_asset_hash
                and item.current_observation_json == current_bytes
            ]
        return matches[0] if len(matches) == 1 else None


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

        with Image.open(image_path) as image:
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
            and _label_matches(candidate, str(anchor.get("label") or ""))
            and _role_matches(candidate.role, str(anchor.get("kind") or ""))
        ):
            matches.append((candidate, grounded))
    return matches


def _label_matches(candidate: RecognitionCandidate, label: str) -> bool:
    expected = _normalized_text(label)
    return bool(expected) and expected in {
        _normalized_text(candidate.label),
        _normalized_text(candidate.text),
        _normalized_text(candidate.element.label),
        _normalized_text(candidate.element.text),
    }


def _role_matches(role: str, anchor_kind: str) -> bool:
    normalized_role = _normalized_text(role)
    normalized_kind = _normalized_text(anchor_kind)
    if normalized_kind == "control":
        return normalized_role in {
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
    if normalized_kind == "text":
        return normalized_role in {"heading", "label", "text"}
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


def _parse_recognition(payload: Mapping[str, Any]) -> tuple[CandidateRankResult, LocalGroundingResult]:
    if payload.get("contract_version") != "recognition_plan_v1":
        raise ValueError("current recognition contract mismatch")
    candidates = _parse_candidate_result(_strict_mapping(payload.get("candidate_result")))
    local = _parse_local_grounding(_strict_mapping(payload.get("narrow_search_result")))
    if len({item.candidate_id for item in candidates.candidates}) != len(candidates.candidates):
        raise ValueError("current recognition candidate identities are ambiguous")
    if len({item.candidate_id for item in local.results}) != len(local.results):
        raise ValueError("current grounding candidate identities are ambiguous")
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
    margin = value["margin_to_second"]
    if margin is not None:
        margin = _number(margin, minimum=0.0, maximum=1.0)
    return CandidateRankResult(
        contract_version="candidate_rank_v1",
        goal=_text(value["goal"]),
        top_k=_integer(value["top_k"], minimum=1),
        candidates=candidates,
        rejected=rejected,
        recommended_candidate_id=_optional_text(value["recommended_candidate_id"]),
        margin_to_second=margin,
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
    refined = value["refined_bbox"]
    refined_bbox = _parse_bbox_mapping(_strict_mapping(refined)) if refined is not None else None
    return RecognitionCandidate(
        candidate_id=_text(value["candidate_id"]),
        rank=_integer(value["rank"], minimum=1),
        element_id=_text(value["element_id"]),
        label=_text(value["label"], allow_empty=True),
        role=_text(value["role"], allow_empty=True),
        text=_text(value["text"], allow_empty=True),
        score=_number(value["score"], minimum=0.0, maximum=1.0),
        eligible=value["eligible"],
        reasons=[_text(item, allow_empty=True) for item in _strict_list(value["reasons"])],
        score_breakdown=breakdown,
        element=_parse_page_element(_strict_mapping(value["element"])),
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
    return LocalGroundingResult(
        contract_version="narrow_search_v1",
        goal=_text(value["goal"]),
        results=[
            _parse_local_result(_strict_mapping(item)) for item in _strict_list(value["results"])
        ],
        recommended_candidate_id=_optional_text(value["recommended_candidate_id"]),
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
) -> Mapping[str, Any]:
    from app.api.models.request import VisionRecognitionPlanRequestModel
    from app.api.vision import recognition_plan

    request = VisionRecognitionPlanRequestModel(
        image_path=image_path,
        task="locate_element",
        goal=goal,
        provider_mode=provider_mode,
        agent_mode="execute",
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={},
        observe_trace_path=None,
    )
    response = recognition_plan(request).model_dump(mode="json")
    if response.get("success") is not True:
        raise ValueError("read-only current recognition failed")
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
) -> LiveController:
    project_root = Path(project_root)
    policy = dict(_DEFAULT_GROUNDING_POLICY if grounding_policy is None else grounding_policy)
    evidence = ExistingWindowsCurrentEvidenceAdapter(
        project_root=project_root,
        application_identity_key=binding.application_identity_key,
        provider_mode=provider_mode,
    )
    receipt_store = RuntimeReceiptStore(project_root=project_root)
    claim_store = RuntimeIntentClaimStore(project_root=project_root, receipt_store=receipt_store)
    return LiveController(
        binding=binding,
        asset_loader=ReviewedWorkflowAssetStore(project_root=project_root),
        observation_source=evidence,
        target_resolver=evidence,
        gate=ReviewedWorkflowGateAdapter(
            min_candidate_score=float(policy["minimum_confidence"]),
            min_margin=float(policy["minimum_score_margin"]),
        ),
        window_visibility_checker=ExistingWindowManagerVisibilityChecker(),
        backend=ExistingWindowsBackendAdapter(),
        intent_claim_store=claim_store,
        grounding_policy=policy,
    )


__all__ = [
    "ExistingWindowsCurrentEvidenceAdapter",
    "build_existing_windows_live_controller",
]
