"""将已核验的当前记忆目标适配到公共执行计划，不派发输入。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import get_ident
from time import monotonic

from PIL import Image


_SCOPE = ContextVar("memory_grounding_target", default=None)


class MemoryGroundingTarget:
    def __init__(self, reference, resolution, *, read_current, selection_request=None, selection_bindings=None):
        if (not isinstance(resolution, dict) or resolution.get("status") != "matched"
                or resolution.get("context_verified") is not True
                or resolution.get("reference") != reference or not callable(read_current)):
            raise ValueError("memory_grounding_verified_resolution_required")
        self.reference = deepcopy(reference)
        self._resolution = deepcopy(resolution)
        self._read_current = read_current
        self._expires = monotonic() + 180
        self._planned = False
        self._claimed = False
        self.selection_request = deepcopy(selection_request)
        self.selection_bindings = deepcopy(selection_bindings)
        self._selection_before = None

    @property
    def selection_enabled(self):
        return self.selection_request is not None

    def selection_preflight(self):
        from app.learning_memory.selection_satisfaction import validate_selection_state
        if not self.selection_enabled or self.input_claimed or monotonic() >= self._expires:
            raise ValueError('selection_context_required')
        current = self._read_current()
        state = validate_selection_state(current, self._resolution.get('row_selection'))
        if current.get('reference') != self.reference or current['frame']['window_identity'] != self._resolution['frame']['window_identity']:
            raise ValueError('selection_current_identity_changed')
        self._selection_before = deepcopy(current)
        return state

    def selection_effect(self, *, action_executed):
        from app.learning_memory.selection_satisfaction import selection_proof
        after = self._read_current()
        return selection_proof(self.selection_request, self.selection_bindings,
                               self._selection_before, after, action_executed=action_executed)

    def selection_control(self):
        from app.core.local_control_target import LocalControlTarget
        from app.learning_memory.selection_satisfaction import validate_selection_state
        def read():
            current = self._read_current()
            state = validate_selection_state(current, self._selection_before['row_selection'])
            # 使用当前截图与原生窗口屏幕原点转换，不引入应用偏移常量。
            rect = current['frame']['window_rect']
            native = state['window_rect']
            state['bbox']['x'] += native[0] - rect[0]
            state['bbox']['y'] += native[1] - rect[1]
            state['window_rect'] = [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]]
            return state
        expected = read()
        return LocalControlTarget(read, expected)

    @property
    def goal(self):
        return self._resolution["goal"]

    @property
    def input_claimed(self):
        return self._claimed

    def _identity(self, identity):
        expected = self._resolution["frame"]["window_identity"]
        if (not isinstance(identity, dict)
                or identity.get("target_window_handle") != expected["handle"]
                or identity.get("process_id") != expected["process_id"]
                or identity.get("process_create_time") != expected["process_create_time"]):
            raise ValueError("memory_grounding_identity_changed")
        if monotonic() >= self._expires:
            raise ValueError("memory_grounding_expired")

    def plan(self, *, image_path, goal, identity):
        self._identity(identity)
        if goal != self.goal:
            raise ValueError("memory_grounding_goal_changed")
        original = self._resolution["frame"]
        if sha256(Path(original["image_path"]).read_bytes()).hexdigest() != original["sha256"]:
            raise ValueError("memory_grounding_source_hash_changed")
        current = self._read_current(image_path)
        if (not isinstance(current, dict) or current.get("status") != "matched"
                or current.get("context_verified") is not True
                or current.get("reference") != self.reference or current.get("goal") != self.goal):
            raise ValueError("memory_grounding_current_target_unverified")
        frame, candidate = current["frame"], current["candidate"]
        if frame["window_identity"] != original["window_identity"]:
            raise ValueError("memory_grounding_identity_changed")
        if Path(frame["image_path"]).resolve() != Path(image_path).resolve():
            raise ValueError("memory_grounding_current_capture_mismatch")
        digest = sha256(Path(image_path).read_bytes()).hexdigest()
        if digest != frame["sha256"]:
            raise ValueError("memory_grounding_current_hash_changed")
        with Image.open(image_path) as image:
            size = {"width": image.width, "height": image.height}
        old = self._resolution["candidate"]
        if (size != candidate["viewport_size"] or size != old["viewport_size"]
                or candidate["capture_id"] != frame["capture_id"]
                or candidate["bbox"] != old["bbox"] or candidate["click_point"] != old["click_point"]):
            raise ValueError("memory_grounding_geometry_changed")
        point, box = candidate["click_point"], candidate["bbox"]
        if (any(type(box.get(key)) is not int for key in ("x", "y", "w", "h"))
                or any(type(point.get(key)) is not int for key in ("x", "y"))
                or not (0 <= box["x"] <= point["x"] < box["x"] + box["w"] <= size["width"])
                or not (0 <= box["y"] <= point["y"] < box["y"] + box["h"] <= size["height"])):
            raise ValueError("memory_grounding_geometry_invalid")
        source = candidate.get("source", "")
        if not source.startswith("memory_"):
            raise ValueError("memory_grounding_source_invalid")
        identity_key = self.reference["recipe_id"]
        label = candidate.get("label", self.goal)
        row = {**deepcopy(candidate), "candidate_id": identity_key, "element_id": identity_key,
               "eligible": True, "text": label, "refined_bbox": deepcopy(box),
               "bbox_refine_reason": source,
               "freshness": {"status": "current_recipe_revalidated", "current_sha256": digest},
               "element": {"element_id": identity_key, "text": label, "bbox": deepcopy(box),
                           "role": candidate.get("role", "control")}}
        self._planned = True
        return {"contract_version": "memory_recognition_plan_v1", "goal": goal,
                "image_path": str(image_path), "target_text": label,
                "parse_result": {"vision_regions": {"image_size": size}},
                "candidate_result": {"recommended_candidate_id": identity_key, "candidates": [row]},
                "recommended_target": row,
                "narrow_search_result": {"results": [{"candidate_id": identity_key,
                    "element_id": identity_key, "status": "grounded", "refined_click_point": deepcopy(point),
                    "coordinate_source": source, "reasons": ["current_context_and_target_matched"]}]},
                "pre_click_decision": {"allowed": True, "selected_candidate_id": identity_key,
                    "selected_element_id": identity_key, "selected_click_point": deepcopy(point),
                    "reasons": ["current_context_and_target_matched"],
                    "validation_scope": "memory_context_and_geometry_common_gate_still_required"},
                "memory_evidence": {"reference": deepcopy(self.reference), "context_verified": True,
                    "capture_id": frame["capture_id"], "sha256": digest,
                    "evidence": deepcopy(current.get("evidence", {})), "task_effect_verified": None},
                "execution_path": {"vision_model_used": False, "local_model_used": False,
                                   "memory_grounding_used": True, "action_executed": False}}

    def before_dispatch(self, point, *, identity):
        self._identity(identity)
        if not self._planned:
            raise ValueError("memory_grounding_plan_required")
        if self._claimed:
            raise ValueError("memory_grounding_already_claimed")
        if point != self._resolution["candidate"]["click_point"]:
            raise ValueError("memory_grounding_point_mismatch")
        if self.selection_enabled:
            from app.learning_memory.selection_satisfaction import validate_selection_state
            state = validate_selection_state(self._read_current(), self._selection_before['row_selection'])
            if state['selected'] is not False:
                raise ValueError('selection_already_selected_before_dispatch')
        self._claimed = True


def current_memory_grounding():
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not scope["active"] or scope["owner"] != get_ident():
        raise ValueError("memory_grounding_scope_revoked")
    return scope["target"]


@contextmanager
def memory_grounding_scope(target):
    if target is None:
        yield
        return
    if type(target) is not MemoryGroundingTarget or _SCOPE.get() is not None:
        raise ValueError("memory_grounding_scope_invalid")
    scope = {"target": target, "owner": get_ident(), "active": True}
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope["active"] = False
        _SCOPE.reset(token)
