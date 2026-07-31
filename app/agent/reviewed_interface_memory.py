from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


MEMORY_CONTRACT = "reviewed_interface_memory_v1"
REGISTRY_CONTRACT = "reviewed_interface_memory_registry_v1"
MEMORY_ROOT = Path("artifacts") / "agent-memory"
EXECUTION_FEEDBACK_CONTRACT = "operational_memory_execution_feedback_v1"
_REGISTRY_LOCK = threading.RLock()
_INTERFACE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")


def validate_current_surface_text_anchors(
    *,
    seed: dict[str, Any],
    observed_texts: list[str],
) -> dict[str, Any]:
    locator_evidence = seed.get("locator_evidence") if isinstance(seed.get("locator_evidence"), dict) else {}
    required_anchors = [
        str(value).strip()
        for value in locator_evidence.get("text_anchors") or []
        if str(value).strip()
    ]
    normalized_observed = [_normalize_surface_text(value) for value in observed_texts]
    combined_observed = " ".join(value for value in normalized_observed if value)
    matched_anchors = [
        anchor
        for anchor in required_anchors
        if _surface_anchor_matches(_normalize_surface_text(anchor), combined_observed)
    ]
    if not required_anchors:
        return {
            "contract_version": "operational_memory_surface_validation_v1",
            "allowed": False,
            "reason": "operational_memory_surface_anchor_missing",
            "required_text_anchors": [],
            "matched_text_anchors": [],
            "observed_text_count": len(normalized_observed),
        }
    return {
        "contract_version": "operational_memory_surface_validation_v1",
        "allowed": bool(matched_anchors),
        "reason": "current_surface_text_anchor_matched" if matched_anchors else "current_surface_text_anchor_missing",
        "required_text_anchors": required_anchors,
        "matched_text_anchors": matched_anchors,
        "observed_text_count": len(normalized_observed),
    }


def validate_current_target_text_anchor(
    *,
    seed: dict[str, Any],
    selected_point: dict[str, Any],
    observed_matches: list[Any],
) -> dict[str, Any]:
    locator_evidence = seed.get("locator_evidence") if isinstance(seed.get("locator_evidence"), dict) else {}
    required_anchors = [
        str(value).strip()
        for value in locator_evidence.get("text_anchors") or []
        if str(value).strip()
    ]
    point = _point_coordinates(selected_point)
    matched_without_bbox = 0
    evidence: list[dict[str, Any]] = []
    ocr_lines: list[dict[str, Any]] = []

    for match in observed_matches:
        text = str(_match_value(match, "text") or "").strip()
        score = float(_match_value(match, "score") or 0.0)
        if not text or score < 0.45:
            continue
        bbox = _match_bbox(match)
        if bbox is None:
            if _matching_local_anchor(required_anchors, text):
                matched_without_bbox += 1
            continue
        ocr_lines.append({"text": text, "score": score, "bbox": bbox})

    evidence_candidates = [
        {**line, "evidence_source": "single_ocr_line"}
        for line in ocr_lines
    ]
    evidence_candidates.extend(_adjacent_ocr_line_candidates(ocr_lines))
    seen_evidence: set[tuple[str, int, int, int, int]] = set()
    seed_bbox = _seed_bbox(seed)
    for candidate in evidence_candidates:
        matched_anchor = _matching_local_anchor(required_anchors, candidate["text"])
        if not matched_anchor:
            continue
        bbox = candidate["bbox"]
        evidence_key = (
            matched_anchor,
            bbox["x"],
            bbox["y"],
            bbox["width"],
            bbox["height"],
        )
        if evidence_key in seen_evidence:
            continue
        seen_evidence.add(evidence_key)
        evidence.append(
            {
                "anchor": matched_anchor,
                "observed_text": candidate["text"],
                "score": candidate["score"],
                "bbox": bbox,
                "evidence_source": candidate["evidence_source"],
                "inside_seed_neighborhood": (
                    _bbox_intersects(bbox, _expanded_bbox(seed_bbox, 0.25))
                    if seed_bbox is not None
                    else None
                ),
                "distance_to_selected_point": _point_to_bbox_distance(point, bbox),
            }
        )

    anchor_heights = [item["bbox"]["height"] for item in evidence]
    max_local_distance = max(96.0, min(220.0, 6.0 * max(anchor_heights, default=16)))
    if seed_bbox is not None and str(seed.get("role") or "").casefold() in {"card", "row", "listitem", "list_item"}:
        max_local_distance = max(max_local_distance, min(420.0, seed_bbox["height"] * 0.9))
    eligible_evidence = [
        item
        for item in evidence
        if item["inside_seed_neighborhood"] is not False
    ]
    nearest_distance = min(
        (
            float(item["distance_to_selected_point"])
            for item in eligible_evidence
            if item["distance_to_selected_point"] is not None
        ),
        default=None,
    )
    allowed = nearest_distance is not None and nearest_distance <= max_local_distance

    if not required_anchors:
        reason = "operational_memory_surface_anchor_missing"
    elif point is None:
        reason = "selected_click_point_missing"
    elif not evidence and matched_without_bbox:
        reason = "current_target_text_anchor_bbox_missing"
    elif not evidence:
        reason = "current_target_text_anchor_missing"
    elif not eligible_evidence:
        reason = "current_target_text_anchor_outside_seed_neighborhood"
    elif allowed:
        reason = "current_target_text_anchor_locally_matched"
    else:
        reason = "current_target_text_anchor_not_local_to_selected_point"

    return {
        "contract_version": "operational_memory_local_target_validation_v1",
        "allowed": allowed,
        "reason": reason,
        "selected_point": point,
        "required_text_anchors": required_anchors,
        "matched_anchor_evidence": evidence,
        "matched_without_bbox_count": matched_without_bbox,
        "nearest_anchor_distance": nearest_distance,
        "max_local_distance": max_local_distance,
        "historical_coordinates_used": False,
    }


def _match_value(match: Any, name: str) -> Any:
    if isinstance(match, dict):
        return match.get(name)
    return getattr(match, name, None)


def _match_bbox(match: Any) -> dict[str, int] | None:
    raw = _match_value(match, "bbox")
    if raw is None:
        return None
    values = {
        key: raw.get(key) if isinstance(raw, dict) else getattr(raw, key, None)
        for key in ("x", "y", "width", "height")
    }
    if any(value is None for value in values.values()):
        return None
    bbox = {key: int(value) for key, value in values.items()}
    if bbox["width"] <= 0 or bbox["height"] <= 0:
        return None
    return bbox


def _matching_local_anchor(required_anchors: list[str], observed_text: str) -> str | None:
    normalized_observed = _normalize_surface_text(observed_text)
    return next(
        (
            anchor
            for anchor in required_anchors
            if _local_surface_anchor_matches(_normalize_surface_text(anchor), normalized_observed)
        ),
        None,
    )


def _adjacent_ocr_line_candidates(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(lines, key=lambda item: (item["bbox"]["y"], item["bbox"]["x"]))
    candidates: list[dict[str, Any]] = []
    for start in range(len(ordered)):
        group = [ordered[start]]
        for end in range(start + 1, min(len(ordered), start + 3)):
            previous = group[-1]["bbox"]
            current = ordered[end]["bbox"]
            vertical_gap = current["y"] - (previous["y"] + previous["height"])
            if vertical_gap > max(24, int(max(previous["height"], current["height"]) * 1.25)):
                break
            if not _bbox_columns_overlap(previous, current):
                continue
            group.append(ordered[end])
            combined_bbox = _bbox_union([item["bbox"] for item in group])
            candidates.append(
                {
                    "text": " ".join(item["text"] for item in group),
                    "score": min(float(item["score"]) for item in group),
                    "bbox": combined_bbox,
                    "evidence_source": "adjacent_ocr_lines",
                }
            )
    return candidates


def _bbox_columns_overlap(first: dict[str, int], second: dict[str, int]) -> bool:
    overlap = min(first["x"] + first["width"], second["x"] + second["width"]) - max(first["x"], second["x"])
    return overlap > 0


def _bbox_union(boxes: list[dict[str, int]]) -> dict[str, int]:
    left = min(box["x"] for box in boxes)
    top = min(box["y"] for box in boxes)
    right = max(box["x"] + box["width"] for box in boxes)
    bottom = max(box["y"] + box["height"] for box in boxes)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _seed_bbox(seed: dict[str, Any]) -> dict[str, int] | None:
    raw = seed.get("bbox")
    if not isinstance(raw, dict):
        return None
    width = raw.get("width", raw.get("w"))
    height = raw.get("height", raw.get("h"))
    if raw.get("x") is None or raw.get("y") is None or width is None or height is None:
        return None
    bbox = {"x": int(raw["x"]), "y": int(raw["y"]), "width": int(width), "height": int(height)}
    return bbox if bbox["width"] > 0 and bbox["height"] > 0 else None


def _expanded_bbox(bbox: dict[str, int], ratio: float) -> dict[str, int]:
    pad_x = int(round(bbox["width"] * ratio))
    pad_y = int(round(bbox["height"] * ratio))
    return {
        "x": bbox["x"] - pad_x,
        "y": bbox["y"] - pad_y,
        "width": bbox["width"] + pad_x * 2,
        "height": bbox["height"] + pad_y * 2,
    }


def _bbox_intersects(first: dict[str, int], second: dict[str, int]) -> bool:
    return not (
        first["x"] + first["width"] < second["x"]
        or second["x"] + second["width"] < first["x"]
        or first["y"] + first["height"] < second["y"]
        or second["y"] + second["height"] < first["y"]
    )


def _point_coordinates(point: Any) -> dict[str, int] | None:
    if not isinstance(point, dict) or point.get("x") is None or point.get("y") is None:
        return None
    return {"x": int(point["x"]), "y": int(point["y"])}


def _point_to_bbox_distance(point: dict[str, int] | None, bbox: dict[str, int]) -> float | None:
    if point is None:
        return None
    left = bbox["x"]
    top = bbox["y"]
    right = left + bbox["width"]
    bottom = top + bbox["height"]
    dx = max(left - point["x"], 0, point["x"] - right)
    dy = max(top - point["y"], 0, point["y"] - bottom)
    return float((dx * dx + dy * dy) ** 0.5)


def _normalize_surface_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())


def _surface_anchor_matches(anchor: str, observed: str) -> bool:
    if not anchor or not observed:
        return False
    if anchor in observed:
        return True
    tokens = [token for token in anchor.split() if len(token) >= 2]
    return len(tokens) >= 2 and all(re.search(rf"(?<!\w){re.escape(token)}(?!\w)", observed) for token in tokens)


def _local_surface_anchor_matches(anchor: str, observed: str) -> bool:
    if not anchor or not observed:
        return False
    return anchor in observed


def _semantic_tokens(value: Any) -> set[str]:
    normalized = _normalize_surface_text(value)
    return {
        token
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized)
        if token not in {"a", "an", "the", "to", "in", "on", "into", "please"}
    }


def _action_intent(value: Any) -> str | None:
    normalized = _normalize_surface_text(value)
    if any(term in normalized for term in ("fill_field", "type", "input", "fill", "enter", "输入", "填写")):
        return "fill"
    if any(term in normalized for term in ("open_detail", "open", "click", "select", "press", "点击", "打开", "选择")):
        return "click"
    if any(term in normalized for term in ("read", "inspect", "view", "读取", "查看")):
        return "read"
    return None


class ReviewedInterfaceMemoryStore:
    """保存和加载经过人工审核的 Agent 界面操作记忆。"""

    def __init__(self, *, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.memory_root = self.project_root / MEMORY_ROOT
        self.objects_root = self.memory_root / "objects"
        self.registry_path = self.memory_root / "registry.json"

    def publish(
        self,
        *,
        source_path: str | Path,
        interface_id: str,
        expected_registry_revision: int,
    ) -> dict[str, Any]:
        interface_id = _validated_interface_id(interface_id)
        candidate_path = self._resolve_file(source_path)
        candidate_bytes = candidate_path.read_bytes()
        candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
        candidate = json.loads(candidate_bytes.decode("utf-8-sig"))
        memory = self._compile_memory(
            candidate=candidate,
            candidate_path=candidate_path,
            candidate_sha256=candidate_sha256,
            interface_id=interface_id,
        )
        object_bytes = _canonical_json_bytes(memory)
        object_sha256 = hashlib.sha256(object_bytes).hexdigest()
        object_path = self.objects_root / f"{object_sha256}.json"

        with _REGISTRY_LOCK:
            registry = self._load_registry()
            revision = int(registry.get("registry_revision") or 0)
            if revision != int(expected_registry_revision):
                raise ValueError(
                    f"registry revision mismatch: expected {expected_registry_revision}, actual {revision}"
                )
            if not object_path.exists():
                _atomic_write(object_path, object_bytes)
            elif hashlib.sha256(object_path.read_bytes()).hexdigest() != object_sha256:
                raise ValueError("reviewed interface memory object hash collision")

            next_revision = revision + 1
            event = {
                "event_id": f"publish_{next_revision}",
                "event_type": "publish",
                "registry_revision": next_revision,
                "interface_id": interface_id,
                "object_sha256": object_sha256,
                "source_candidate_sha256": candidate_sha256,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "active": True,
                "artifact_is_authorization": False,
            }
            registry["registry_revision"] = next_revision
            registry.setdefault("objects", {})[object_sha256] = {
                "object_path": self._relative_path(object_path),
                "interface_id": interface_id,
                "source_candidate_path": self._relative_path(candidate_path),
                "source_candidate_sha256": candidate_sha256,
                "active": True,
            }
            registry.setdefault("active_by_interface", {})[interface_id] = object_sha256
            registry.setdefault("events", []).append(event)
            _atomic_write(self.registry_path, _canonical_json_bytes(registry))

        return {
            "contract_version": "reviewed_interface_memory_publish_v1",
            "status": "published",
            "interface_id": interface_id,
            "object_sha256": object_sha256,
            "object_path": self._relative_path(object_path),
            "registry_path": self._relative_path(self.registry_path),
            "registry_revision": next_revision,
            "active": True,
            "agent_consumable": True,
            "runtime_resolution_enabled": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    def load_active(self, interface_id: str) -> dict[str, Any]:
        interface_id = _validated_interface_id(interface_id)
        registry = self._load_registry()
        object_sha256 = str(registry.get("active_by_interface", {}).get(interface_id) or "")
        if not object_sha256:
            raise ValueError(f"active reviewed interface memory not found: {interface_id}")
        record = registry.get("objects", {}).get(object_sha256)
        if not isinstance(record, dict):
            raise ValueError("active reviewed interface memory registry record is missing")
        object_path = self._resolve_file(str(record.get("object_path") or ""))
        actual_sha256 = hashlib.sha256(object_path.read_bytes()).hexdigest()
        if actual_sha256 != object_sha256:
            raise ValueError("reviewed interface memory object checksum mismatch")
        payload = json.loads(object_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("contract_version") != MEMORY_CONTRACT:
            raise ValueError("reviewed interface memory object has an invalid contract")
        if payload.get("interface_id") != interface_id:
            raise ValueError("reviewed interface memory interface identity mismatch")
        return payload

    def registry(self) -> dict[str, Any]:
        return deepcopy(self._load_registry())

    def agent_context(self, interface_id: str) -> dict[str, Any]:
        memory = self.load_active(interface_id)
        return {
            "contract_version": "agent_operational_memory_context_v1",
            "interface_id": memory["interface_id"],
            "states": deepcopy(memory.get("states") or []),
            "elements": deepcopy(memory.get("elements") or []),
            "available_actions": deepcopy(memory.get("actions") or []),
            "verification_rules": deepcopy(memory.get("verification_rules") or []),
            "blockers": deepcopy(memory.get("blockers") or []),
            "execution_contract": {
                "current_capture_required": True,
                "current_target_resolution_required": True,
                "historical_coordinates_forbidden": True,
                "gate_required": True,
                "post_action_verification_required": True,
                "artifact_is_authorization": False,
            },
        }

    def resolve_action_for_goal(self, *, interface_id: str, goal: str) -> dict[str, Any]:
        """把自然语言任务解析为唯一的低风险记忆动作。"""
        memory = self.load_active(interface_id)
        normalized_goal = _normalize_surface_text(goal)
        if not normalized_goal:
            raise ValueError("operational memory action goal is empty")
        goal_tokens = _semantic_tokens(normalized_goal)
        goal_intent = _action_intent(normalized_goal)
        elements = {
            str(item.get("element_id") or ""): item
            for item in _dict_items(memory.get("elements"))
        }
        scored: list[dict[str, Any]] = []
        for action in _dict_items(memory.get("actions")):
            element = elements.get(str(action.get("target_element_id") or "")) or {}
            action_text = _normalize_surface_text(
                " ".join(
                    [
                        str(action.get("label") or ""),
                        str(action.get("source_action_template_id") or ""),
                        str(action.get("semantic_action") or ""),
                        str(element.get("label") or ""),
                        str(element.get("source_region_id") or ""),
                        str(element.get("role") or ""),
                    ]
                )
            )
            overlap = goal_tokens & _semantic_tokens(action_text)
            semantic_intent = _action_intent(action.get("semantic_action"))
            score = min(0.4, 0.12 * len(overlap))
            target_label = _normalize_surface_text(element.get("label"))
            target_role = _normalize_surface_text(element.get("role"))
            if target_label and target_label in normalized_goal:
                score += 0.3
            if target_role and target_role in normalized_goal:
                score += 0.15
            if goal_intent and semantic_intent == goal_intent:
                score += 0.5
            elif goal_intent and semantic_intent and semantic_intent != goal_intent:
                score -= 0.35
            if _normalize_surface_text(action.get("label")) == normalized_goal:
                score += 0.2
            scored.append(
                {
                    "action_id": action.get("action_id"),
                    "label": action.get("label"),
                    "semantic_action": action.get("semantic_action"),
                    "target_element_id": action.get("target_element_id"),
                    "target_label": element.get("label"),
                    "target_role": element.get("role"),
                    "danger_class": action.get("danger_class"),
                    "automatic_execution_allowed": action.get("automatic_execution_allowed") is True,
                    "score": round(max(0.0, score), 4),
                    "matched_tokens": sorted(overlap),
                    "intent_match": bool(goal_intent and semantic_intent == goal_intent),
                }
            )
        scored.sort(key=lambda item: (-float(item["score"]), str(item.get("action_id") or "")))
        allowed = [item for item in scored if item["automatic_execution_allowed"]]
        selected = allowed[0] if allowed else None
        runner_up = allowed[1] if len(allowed) > 1 else None
        selected_score = float(selected.get("score") or 0.0) if selected else 0.0
        margin = selected_score - float(runner_up.get("score") or 0.0) if runner_up else selected_score
        status = "selected"
        if selected is None or selected_score < 0.4:
            blocked_match = next((item for item in scored if float(item["score"]) >= 0.4), None)
            status = "blocked_high_risk" if blocked_match and not blocked_match["automatic_execution_allowed"] else "no_match"
            selected = None
        elif runner_up is not None and margin < 0.12:
            status = "ambiguous"
            selected = None
        return {
            "contract_version": "operational_memory_action_resolution_v1",
            "interface_id": memory["interface_id"],
            "goal": goal,
            "normalized_goal": normalized_goal,
            "goal_intent": goal_intent,
            "status": status,
            "action_id": selected.get("action_id") if selected else None,
            "automatic_execution_allowed": bool(selected),
            "confidence": round(selected_score, 4) if selected else 0.0,
            "score_margin": round(max(0.0, margin), 4) if selected else 0.0,
            "resolution_source": "deterministic_semantic_memory_match",
            "candidate_scores": scored,
        }

    def record_execution_feedback(
        self,
        *,
        interface_id: str,
        action_id: str | None,
        goal: str,
        failure_category: str,
        failure_details: Any,
        trace_path: str | None,
    ) -> dict[str, Any]:
        """把执行失败持久化为可返回人工修订的学习反馈。"""
        memory = self.load_active(interface_id)
        action = next(
            (
                item
                for item in _dict_items(memory.get("actions"))
                if item.get("action_id") == action_id
            ),
            None,
        )
        element = next(
            (
                item
                for item in _dict_items(memory.get("elements"))
                if action and item.get("element_id") == action.get("target_element_id")
            ),
            None,
        )
        created_at = datetime.now(timezone.utc).isoformat()
        fingerprint = hashlib.sha256(
            _canonical_json_bytes(
                {
                    "interface_id": interface_id,
                    "action_id": action_id,
                    "goal": goal,
                    "failure_category": failure_category,
                    "trace_path": trace_path,
                    "created_at": created_at,
                }
            )
        ).hexdigest()[:16]
        feedback_id = f"feedback_{created_at.replace(':', '').replace('-', '').replace('+00:00', 'Z')}_{fingerprint}"
        payload = {
            "contract_version": EXECUTION_FEEDBACK_CONTRACT,
            "feedback_id": feedback_id,
            "created_at": created_at,
            "interface_id": interface_id,
            "action_id": action_id,
            "goal": goal,
            "outcome": "execution_failed",
            "review_status": "needs_human_review",
            "failure": {
                "category": str(failure_category or "unknown_execution_failure"),
                "details": deepcopy(failure_details),
            },
            "trace_path": trace_path,
            "review_target": {
                "reviewed_candidate_path": memory["source"]["reviewed_candidate_path"],
                "human_review_patch_path": memory["review"].get("human_review_patch_path"),
                "source_action_template_id": action.get("source_action_template_id") if action else None,
                "source_region_id": element.get("source_region_id") if element else None,
                "stable_element_id": element.get("element_id") if element else None,
            },
            "safety": {
                "action_executed": False,
                "artifact_is_authorization": False,
                "requires_human_review": True,
            },
        }
        feedback_path = self.memory_root / "execution-feedback" / interface_id / f"{feedback_id}.json"
        _atomic_write(feedback_path, _canonical_json_bytes(payload))
        return {
            "contract_version": "operational_memory_execution_feedback_record_v1",
            "feedback_id": feedback_id,
            "feedback_path": self._relative_path(feedback_path),
            "review_status": "needs_human_review",
            "review_target": deepcopy(payload["review_target"]),
        }

    def build_current_capture_action_seed(
        self,
        *,
        interface_id: str,
        action_id: str,
        image_path: str | Path,
    ) -> dict[str, Any]:
        memory = self.load_active(interface_id)
        action = next(
            (item for item in _dict_items(memory.get("actions")) if item.get("action_id") == action_id),
            None,
        )
        if action is None:
            raise ValueError(f"reviewed interface memory action not found: {action_id}")
        if action.get("danger_class") != "low_risk" or action.get("automatic_execution_allowed") is not True:
            raise ValueError(f"reviewed interface memory action is blocked high-risk: {action_id}")

        element_id = str(action.get("target_element_id") or "")
        element = next(
            (item for item in _dict_items(memory.get("elements")) if item.get("element_id") == element_id),
            None,
        )
        if element is None:
            raise ValueError(f"reviewed interface memory target element not found: {element_id}")
        capture_path = self._resolve_file(image_path)
        with Image.open(capture_path) as image:
            viewport = {"width": int(image.width), "height": int(image.height)}
        locator = element.get("locator_profile") if isinstance(element.get("locator_profile"), dict) else {}
        normalized_bbox = locator.get("normalized_bbox") if isinstance(locator.get("normalized_bbox"), dict) else {}
        bbox = _bbox_from_normalized(normalized_bbox, viewport=viewport)
        click_point = {
            "x": int(round(bbox["x"] + bbox["w"] / 2)),
            "y": int(round(bbox["y"] + bbox["h"] / 2)),
        }
        capture_sha256 = hashlib.sha256(capture_path.read_bytes()).hexdigest()
        semantic_action = str(action.get("semantic_action") or "click")
        role = str(element.get("role") or "button")
        return {
            "contract_version": "seeded_candidate_v1",
            "candidate_id": f"memory::{action_id}",
            "source": MEMORY_CONTRACT,
            "stable_element_id": element_id,
            "action_id": action_id,
            "label": str(element.get("label") or action.get("label") or element_id),
            "role": role,
            "bbox": bbox,
            "click_point": click_point,
            "score": 0.82,
            "risk_class": "safe_click_allowed",
            "expected_effect": semantic_action,
            "require_current_grounding": True,
            "historical_click_point_reused": False,
            "locator_evidence": {
                "text_anchors": list(locator.get("text_anchors") or []),
                "role_anchor": locator.get("role_anchor"),
                "reference_bbox_is_prior_only": True,
            },
            "current_capture": {
                "screenshot_path": str(capture_path),
                "screenshot_sha256": capture_sha256,
                "capture_id": capture_sha256,
                "viewport_size": viewport,
                "freshness": "current_capture",
            },
        }

    def _compile_memory(
        self,
        *,
        candidate: dict[str, Any],
        candidate_path: Path,
        candidate_sha256: str,
        interface_id: str,
    ) -> dict[str, Any]:
        if not isinstance(candidate, dict) or candidate.get("contract_version") != "reviewed_template_candidate_v1":
            raise ValueError("reviewed interface memory requires reviewed_template_candidate_v1")
        if candidate.get("reviewed_by_human") is not True or candidate.get("review_status") != "approved_as_assisted_template":
            raise ValueError("reviewed interface memory requires approved human review")
        if candidate.get("artifact_is_authorization") is not False:
            raise ValueError("reviewed candidate must not be action authorization")

        draft = candidate.get("draft") if isinstance(candidate.get("draft"), dict) else {}
        screen = _screen_details(draft)
        screenshot_path = self._resolve_file(str(screen.get("source_image_path") or screen.get("image_path") or ""))
        expected_screenshot_sha256 = str(screen.get("source_image_sha256") or "").strip().lower()
        actual_screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
        if not expected_screenshot_sha256 or expected_screenshot_sha256 != actual_screenshot_sha256:
            raise ValueError("reviewed candidate screenshot checksum mismatch")
        viewport = _reference_viewport(screen)

        elements = [
            _compile_element(interface_id=interface_id, region=region, viewport=viewport)
            for region in _dict_items(draft.get("regions"))
        ]
        element_ids_by_source = {
            item["source_region_id"]: item["element_id"]
            for item in elements
        }
        actions = [
            _compile_action(
                interface_id=interface_id,
                action=action,
                element_ids_by_source=element_ids_by_source,
            )
            for action in _dict_items(draft.get("action_templates"))
        ]
        states = [
            _compile_state(interface_id=interface_id, state=state)
            for state in _dict_items(draft.get("states"))
        ]
        if not elements:
            raise ValueError("reviewed candidate has no interface elements")
        if not states:
            raise ValueError("reviewed candidate has no interface states")

        audit = candidate.get("audit") if isinstance(candidate.get("audit"), dict) else {}
        return {
            "contract_version": MEMORY_CONTRACT,
            "interface_id": interface_id,
            "source": {
                "reviewed_candidate_path": self._relative_path(candidate_path),
                "reviewed_candidate_sha256": candidate_sha256,
                "screenshot_path": self._relative_path(screenshot_path),
                "screenshot_sha256": actual_screenshot_sha256,
                "reference_viewport": viewport,
            },
            "review": {
                "reviewed_by_human": True,
                "review_status": candidate.get("review_status"),
                "human_review_patch_revision": audit.get("human_review_patch_revision"),
                "human_review_patch_path": audit.get("human_review_patch_path"),
            },
            "states": states,
            "elements": elements,
            "actions": actions,
            "verification_rules": deepcopy(_dict_items(draft.get("verification_rules"))),
            "blockers": deepcopy(_dict_items(draft.get("blockers"))),
            "agent_usage": {
                "agent_consumable": True,
                "runtime_resolution_enabled": True,
                "target_reference": "stable_element_id",
                "historical_coordinates_are_execution_forbidden": True,
            },
            "safety": {
                "final_submit_forbidden": True,
                "real_action_requires_gate": True,
                "current_capture_required": True,
                "current_target_resolution_required": True,
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {
                "contract_version": REGISTRY_CONTRACT,
                "registry_revision": 0,
                "objects": {},
                "active_by_interface": {},
                "events": [],
            }
        payload = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("contract_version") != REGISTRY_CONTRACT:
            raise ValueError("reviewed interface memory registry has an invalid contract")
        return payload

    def _resolve_file(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("reviewed interface memory path escapes project root") from exc
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(str(resolved))
        return resolved

    def _relative_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.project_root).as_posix()


def _compile_element(
    *,
    interface_id: str,
    region: dict[str, Any],
    viewport: dict[str, int],
) -> dict[str, Any]:
    source_region_id = str(region.get("region_id") or "").strip()
    if not source_region_id:
        raise ValueError("reviewed candidate region is missing region_id")
    bbox = _bbox(region.get("bbox"))
    normalized_bbox = {
        "x": round(bbox["x"] / viewport["width"], 6),
        "y": round(bbox["y"] / viewport["height"], 6),
        "w": round(bbox["w"] / viewport["width"], 6),
        "h": round(bbox["h"] / viewport["height"], 6),
    }
    label = str(region.get("label") or region.get("name") or source_region_id).strip()
    role = str(region.get("role") or region.get("kind") or "unknown").strip()
    return {
        "element_id": f"{interface_id}::element::{source_region_id}",
        "source_region_id": source_region_id,
        "label": label,
        "role": role,
        "parent_element_id": (
            f"{interface_id}::element::{region.get('parent_region_id')}"
            if region.get("parent_region_id")
            else None
        ),
        "state_ref": region.get("source_section_id") or region.get("state_id"),
        "locator_profile": {
            "reference_bbox": bbox,
            "reference_viewport": dict(viewport),
            "normalized_bbox": normalized_bbox,
            "text_anchors": [label] if label else [],
            "role_anchor": role,
            "strategies": ["current_screen_recognition", "uia", "ocr", "vision_grounding"],
            "source_capture_required": True,
        },
    }


def _compile_action(
    *,
    interface_id: str,
    action: dict[str, Any],
    element_ids_by_source: dict[str, str],
) -> dict[str, Any]:
    source_action_id = str(action.get("action_template_id") or action.get("action_id") or "").strip()
    if not source_action_id:
        raise ValueError("reviewed candidate action is missing action_template_id")
    target_region_id = str(
        action.get("target_region_id")
        or action.get("region_id")
        or action.get("target_id")
        or ""
    ).strip()
    target_element_id = element_ids_by_source.get(target_region_id)
    if not target_element_id:
        raise ValueError(f"reviewed candidate action target is missing: {source_action_id}")
    semantic_action = str(
        action.get("semantic_action")
        or action.get("action_type")
        or action.get("low_level_action_type")
        or "unknown"
    ).strip()
    danger_class = _danger_class(semantic_action, str(action.get("label") or source_action_id))
    return {
        "action_id": f"{interface_id}::action::{source_action_id}",
        "source_action_template_id": source_action_id,
        "label": str(action.get("label") or source_action_id),
        "semantic_action": semantic_action,
        "target_element_id": target_element_id,
        "danger_class": danger_class,
        "requires_current_resolution": True,
        "requires_gate": True,
        "automatic_execution_allowed": danger_class == "low_risk",
    }


def _compile_state(*, interface_id: str, state: dict[str, Any]) -> dict[str, Any]:
    source_state_id = str(state.get("state_id") or "").strip()
    if not source_state_id:
        raise ValueError("reviewed candidate state is missing state_id")
    return {
        "state_id": f"{interface_id}::state::{source_state_id}",
        "source_state_id": source_state_id,
        "name": str(state.get("name") or state.get("label") or source_state_id),
        "screen_summary": str(state.get("screen_summary") or state.get("description") or ""),
    }


def _danger_class(semantic_action: str, label: str) -> str:
    semantic = semantic_action.casefold().strip()
    normalized_label = " ".join(label.casefold().split())
    if semantic == "submit_search":
        return "low_risk"
    dangerous_semantics = {
        "final_submit",
        "send_message",
        "send_application",
        "submit_application",
        "complete_application",
        "confirm_application",
        "confirm_order",
        "payment",
        "purchase",
        "delete",
    }
    if semantic in dangerous_semantics:
        return "blocked_high_risk"
    dangerous_label_phrases = (
        "submit application",
        "send application",
        "review and submit",
        "complete application",
        "confirm application",
        "confirm order",
        "make payment",
        "purchase",
        "delete",
        "提交申请",
        "发送申请",
        "确认提交",
        "删除",
        "付款",
        "支付",
    )
    if normalized_label in {"submit", "send", "complete", "confirm"}:
        return "blocked_high_risk"
    return (
        "blocked_high_risk"
        if any(term in normalized_label for term in dangerous_label_phrases)
        else "low_risk"
    )


def _screen_details(draft: dict[str, Any]) -> dict[str, Any]:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    if not screen:
        raise ValueError("reviewed candidate is missing source screen details")
    return screen


def _reference_viewport(screen: dict[str, Any]) -> dict[str, int]:
    screen_size = screen.get("screen_size") if isinstance(screen.get("screen_size"), dict) else {}
    screen_bbox = screen.get("bbox") if isinstance(screen.get("bbox"), dict) else {}
    width = int(
        screen.get("width")
        or screen.get("image_width")
        or screen_size.get("width")
        or screen_bbox.get("w")
        or screen_bbox.get("width")
        or 0
    )
    height = int(
        screen.get("height")
        or screen.get("image_height")
        or screen_size.get("height")
        or screen_bbox.get("h")
        or screen_bbox.get("height")
        or 0
    )
    if width <= 0 or height <= 0:
        raise ValueError("reviewed candidate is missing reference viewport")
    return {"width": width, "height": height}


def _bbox(value: Any) -> dict[str, int]:
    payload = value if isinstance(value, dict) else {}
    bbox = {
        "x": int(payload.get("x") or 0),
        "y": int(payload.get("y") or 0),
        "w": int(payload.get("w") or payload.get("width") or 0),
        "h": int(payload.get("h") or payload.get("height") or 0),
    }
    if bbox["x"] < 0 or bbox["y"] < 0 or bbox["w"] <= 0 or bbox["h"] <= 0:
        raise ValueError("reviewed candidate region has an invalid bbox")
    return bbox


def _bbox_from_normalized(value: dict[str, Any], *, viewport: dict[str, int]) -> dict[str, int]:
    bbox = {
        "x": int(round(float(value.get("x") or 0) * viewport["width"])),
        "y": int(round(float(value.get("y") or 0) * viewport["height"])),
        "w": int(round(float(value.get("w") or 0) * viewport["width"])),
        "h": int(round(float(value.get("h") or 0) * viewport["height"])),
    }
    if bbox["x"] < 0 or bbox["y"] < 0 or bbox["w"] <= 0 or bbox["h"] <= 0:
        raise ValueError("reviewed interface memory normalized bbox is invalid for current capture")
    if bbox["x"] + bbox["w"] > viewport["width"] or bbox["y"] + bbox["h"] > viewport["height"]:
        raise ValueError("reviewed interface memory current-capture ROI is outside the viewport")
    return bbox


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def _validated_interface_id(value: str) -> str:
    interface_id = str(value or "").strip().casefold()
    if not _INTERFACE_ID_PATTERN.fullmatch(interface_id):
        raise ValueError("interface_id must use 2-80 lowercase letters, digits, dot, underscore, or hyphen")
    return interface_id


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
