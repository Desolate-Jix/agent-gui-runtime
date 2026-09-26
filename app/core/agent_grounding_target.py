"""Agent 候选的内部执行适配；只生成现有计划，不建立新输入后端。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import get_ident
import time

from PIL import Image, ImageChops

from app.vision.grounding_contract import validate_grounding_result


_SCOPE = ContextVar("agent_grounding_target", default=None)


class AgentGroundingTarget:
    def __init__(self, state):
        self._state = deepcopy(state)
        if state.get("phase") != "executing":
            raise ValueError("agent_grounding_execution_not_claimed")
        capture = self._state["capture"]
        self._result = validate_grounding_result(self._state["result"],
            request_id=state["request_id"], capture_id=capture["capture_id"],
            image_size=(capture["image_size"]["width"], capture["image_size"]["height"]))
        if self._result.status != "found":
            raise ValueError("agent_grounding_target_not_found")
        self._candidate = next(c for c in self._result.candidates if c.id == self._result.selected_candidate_id)
        self._planned = False
        self._claimed = False

    @property
    def goal(self):
        return self._state["goal"]

    @property
    def input_claimed(self):
        return self._claimed

    def _identity(self, identity):
        expected = self._state["capture"]["window_identity"]
        if (identity.get("target_window_handle") != expected["handle"]
                or identity.get("process_id") != expected["process_id"]
                or identity.get("process_create_time") != expected["process_create_time"]):
            raise ValueError("agent_grounding_identity_changed")
        if time.time() >= self._state["expires_at"]:
            raise ValueError("agent_grounding_request_expired")

    def plan(self, *, image_path, goal, identity):
        self._identity(identity)
        if goal != self.goal:
            raise ValueError("agent_grounding_goal_mismatch")
        capture = self._state["capture"]
        original = Path(capture["image_path"]).read_bytes()
        if sha256(original).hexdigest() != capture["sha256"]:
            raise ValueError("agent_grounding_source_hash_mismatch")
        with Image.open(BytesIO(original)) as source, Image.open(image_path) as current:
            expected_size = (self._result.image_size.width, self._result.image_size.height)
            if source.size != expected_size or current.size != expected_size:
                raise ValueError("agent_grounding_viewport_changed")
            box = self._candidate.bbox
            region = (max(0, box.x-8), max(0, box.y-8),
                      min(current.width, box.x+box.width+8), min(current.height, box.y+box.height+8))
            before, after = source.crop(region).convert("RGB"), current.crop(region).convert("RGB")
            difference = ImageChops.difference(before, after)
            channels = difference.split()
            maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            histogram = maximum.histogram()
            changed = sum(histogram[13:]) / (before.width * before.height)
            # 只容忍局部少量光标/抗锯齿变化；这是新鲜度启发式，不是语义命中证明。
            if changed > .02:
                raise ValueError("agent_grounding_target_region_changed")
        point = self._candidate.click_point.model_dump()
        bbox = {"x": box.x, "y": box.y, "w": box.width, "h": box.height}
        element_id = "agent-" + self._candidate.id
        candidate = {"candidate_id": self._candidate.id, "element_id": element_id,
            "text": self._candidate.label, "score": self._candidate.confidence,
            "bbox_refine_reason": "agent_visual_bbox", "refined_bbox": bbox,
            "element": {"element_id": element_id, "text": self._candidate.label, "bbox": bbox}}
        pre_click = {"allowed": True, "selected_candidate_id": self._candidate.id,
            "selected_element_id": element_id, "selected_click_point": point,
            "reasons": ["agent_selected_target", "current_region_consistent"],
            "validation_scope": "identity_geometry_and_region_consistency_not_semantic_hit"}
        self._planned = True
        return {"image_path": str(image_path), "goal": goal, "target_text": self._candidate.label,
            "parse_result": {"vision_regions": {"image_size": self._result.image_size.model_dump()}},
            "candidate_result": {"recommended_candidate_id": self._candidate.id, "candidates": [candidate]},
            "recommended_target": candidate, "pre_click_decision": pre_click,
            "narrow_search_result": {"results": [{"candidate_id": self._candidate.id,
                "element_id": element_id, "status": "agent_proposed", "refined_click_point": point,
                "coordinate_source": "agent_visual", "reasons": ["not_local_ocr_corroborated"]}]},
            "grounding_evidence": {"request_id": self._state["request_id"], "capture_id": capture["capture_id"],
                "source_sha256": capture["sha256"], "region_changed_fraction": changed,
                "source": self._state["configuration"]["source"], "target_hit_verified": None,
                "task_effect_verified": None},
            "execution_path": {"vision_model_used": False, "local_model_used": False,
                "external_grounding_used": True, "action_executed": False}}

    def before_dispatch(self, point, identity):
        self._identity(identity)
        if not self._planned:
            raise ValueError("agent_grounding_plan_required")
        if self._claimed:
            raise ValueError("agent_grounding_already_claimed")
        if point != self._candidate.click_point.model_dump():
            raise ValueError("agent_grounding_point_mismatch")
        self._claimed = True


def current_agent_grounding():
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not scope["active"] or scope["owner"] != get_ident():
        raise ValueError("agent_grounding_scope_revoked")
    return scope["target"]


@contextmanager
def agent_grounding_scope(target):
    if target is None:
        yield
        return
    if type(target) is not AgentGroundingTarget or _SCOPE.get() is not None:
        raise ValueError("agent_grounding_scope_invalid")
    scope = {"target": target, "owner": get_ident(), "active": True}
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope["active"] = False
        _SCOPE.reset(token)
