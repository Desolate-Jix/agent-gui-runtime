"""当前字段的受审提交；值证明只授权 Enter，新点击另行认证。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import get_ident
from weakref import WeakKeyDictionary

from PIL import Image


_ISSUED = WeakKeyDictionary()


class VisualSubmitTarget:
    def __init__(self, keyboard_target, *, action_review):
        from .local_keyboard_target import VisualKeyboardTarget
        from app.execution.action_review import normalize_action_review_context
        from app.execution.task_plan_contract import resolve_action_text
        from app.execution.visual_field_proof import _checked_proof
        if (type(keyboard_target) is not VisualKeyboardTarget or keyboard_target.operation != "press_key"
                or keyboard_target.submit_search is not True or keyboard_target._consumed):
            raise ValueError("visual_submit_keyboard_target_invalid")
        value = _checked_proof(keyboard_target.proof)
        action = value["request"]["action"]
        self._field = deepcopy(action["field"])
        self._context = normalize_action_review_context(action_review)
        if self._context is None:
            raise ValueError("visual_submit_action_review_required")
        permitted = next(row["action"] for row in self._context["plan"]["steps"]
            if row["step_id"] == self._context["step_id"])
        if (action["field_phase"] != "value" or action.get("value_verification") != "visual"
                or action.get("value_reading") is not None or self._field["field_kind"] not in {"search", "address_bar"}
                or permitted.get("kind") != "input_sequence" or permitted.get("submit_search") is not True
                or permitted.get("clear_existing", True) is not True
                or permitted.get("field_goal") != self._field["field_goal"]
                or resolve_action_text(permitted.get("text"), self._context["plan"]["inputs"]) != self._field["expected_text"]):
            raise ValueError("visual_submit_original_action_mismatch")
        self._target_identity = None
        if "target_identity_binding" in action:
            from app.judgment.target_identity import normalize_target_identity
            from app.execution.visual_field_proof import _digest
            binding = action["target_identity_binding"]
            required = {"schema", "goal", "target_identity", "focus_receipt_sha256", "action_review_sha256",
                "source_request_sha256", "source_assessment_sha256"}
            if (type(binding) is not dict or set(binding) != required
                    or binding["schema"] != "target_identity_binding.v1" or binding["goal"] != self.goal
                    or binding["focus_receipt_sha256"] != action["focus_receipt_sha256"]
                    or binding["action_review_sha256"] != _digest(self._context)
                    or any(type(binding[key]) is not str or len(binding[key]) != 64
                        or any(char not in "0123456789abcdef" for char in binding[key]) for key in
                        ("focus_receipt_sha256", "action_review_sha256", "source_request_sha256", "source_assessment_sha256"))):
                raise ValueError("visual_submit_target_identity_binding_invalid")
            self._target_identity = normalize_target_identity(binding["target_identity"])
            if ("target_identity" not in permitted and next(row["description"] for row in
                    self._target_identity["choices"] if row["value"] == self._target_identity["expected"]) != self.goal):
                raise ValueError("visual_submit_target_identity_goal_mismatch")
        self._target_check = None
        if "target_check_binding" in action:
            from app.judgment.target_check import normalize_target_check
            from app.execution.visual_field_proof import _digest
            binding = action["target_check_binding"]
            required = {"schema", "goal", "target_check", "focus_receipt_sha256", "action_review_sha256",
                "source_request_sha256", "source_assessment_sha256"}
            if (type(binding) is not dict or set(binding) != required
                    or binding["schema"] != "target_check_binding.v1" or binding["goal"] != self.goal
                    or binding["focus_receipt_sha256"] != action["focus_receipt_sha256"]
                    or binding["action_review_sha256"] != _digest(self._context)
                    or any(type(binding[key]) is not str or len(binding[key]) != 64
                        or any(char not in "0123456789abcdef" for char in binding[key]) for key in
                        ("focus_receipt_sha256", "action_review_sha256", "source_request_sha256", "source_assessment_sha256"))):
                raise ValueError("visual_submit_target_check_binding_invalid")
            self._target_check = normalize_target_check(binding["target_check"])
            if (self._target_check["target"] != self.goal or self._target_check["kind"] != "input_field"
                    or self._target_identity is not None):
                raise ValueError("visual_submit_target_check_goal_mismatch")
        issued = _ISSUED.setdefault(keyboard_target.proof._service, set())
        binding = value["assessment"]["request_sha256"]
        if binding in issued:
            raise ValueError("visual_submit_already_issued")
        issued.add(binding)
        self.keyboard_target = keyboard_target
        self._value = value
        self._owner = get_ident()
        self._planned = None
        self._claimed = False
        self._prepared = None
        self._performed = False

    @property
    def goal(self):
        return self._field["field_goal"]

    @property
    def input_claimed(self):
        return self._claimed

    def review_target_identity(self, action):
        """回锚只复用当前值证明认证的原定位身份，不追加定位调用。"""
        from .agent_grounding_target import current_agent_grounding
        from app.execution.visual_field_proof import _checked_proof
        from app.judgment.target_identity import normalize_target_identity
        if (current_agent_grounding() is not self or action.get("field_goal", action.get("goal")) != self.goal
                or _checked_proof(self.keyboard_target.proof) != self._value):
            raise ValueError("visual_submit_target_identity_binding_invalid")
        binding = self._value["request"]["action"].get("target_identity_binding")
        expected = None if binding is None else normalize_target_identity(binding["target_identity"])
        if self._target_identity != expected:
            raise ValueError("visual_submit_target_identity_binding_invalid")
        return deepcopy(self._target_identity)

    def review_target_check(self, action):
        """回锚复用已认证原检查，不能把缓存改写为另一个目标。"""
        from .agent_grounding_target import current_agent_grounding
        from app.execution.visual_field_proof import _checked_proof
        from app.judgment.target_check import normalize_target_check
        if (current_agent_grounding() is not self or action.get("field_goal", action.get("goal")) != self.goal
                or _checked_proof(self.keyboard_target.proof) != self._value):
            raise ValueError("visual_submit_target_check_binding_invalid")
        binding = self._value["request"]["action"].get("target_check_binding")
        expected = None if binding is None else normalize_target_check(binding["target_check"])
        if self._target_check != expected:
            raise ValueError("visual_submit_target_check_binding_invalid")
        return deepcopy(self._target_check)

    def _identity(self, identity):
        from app.execution.decision_check import _identity
        from app.execution.visual_field_proof import _checked_proof
        if (get_ident() != self._owner or self.keyboard_target._consumed
                or _identity(identity) != self._field["window_identity"]):
            raise ValueError("visual_submit_identity_changed")
        if _checked_proof(self.keyboard_target.proof) != self._value:
            raise ValueError("visual_submit_value_proof_changed")

    def plan(self, *, image_path, goal, identity):
        self._identity(identity)
        if self._claimed or goal != self.goal:
            raise ValueError("visual_submit_consumed_or_goal_changed")
        source = self._value["request"]["frames"][-1]
        if sha256(Path(source["image_path"]).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("visual_submit_source_changed")
        current = Path(image_path).resolve(strict=True)
        digest = sha256(current.read_bytes()).hexdigest()
        with Image.open(current) as image:
            size = {"width": image.width, "height": image.height}
        rect, box, point = self._field["window_rect"], self._field["bbox"], self._field["click_point"]
        if (size != {"width": rect[2], "height": rect[3]}
                or not 0 <= box["x"] <= point["x"] < box["x"]+box["w"] <= size["width"]
                or not 0 <= box["y"] <= point["y"] < box["y"]+box["h"] <= size["height"]):
            raise ValueError("visual_submit_geometry_changed")
        identifier = "verified-field-" + self._value["assessment"]["request_sha256"][:24]
        candidate = {"candidate_id": identifier, "element_id": identifier, "text": self.goal,
            "capture_id": digest, "viewport_size": size, "source": "verified_visual_field",
            "bbox": deepcopy(box), "click_point": deepcopy(point), "eligible": True,
            "refined_bbox": deepcopy(box), "bbox_refine_reason": "authenticated_field_geometry",
            "freshness": {"status": "pending_semantic_review", "current_sha256": digest,
                "source_sha256": source["sha256"]},
            "element": {"element_id": identifier, "text": self.goal, "bbox": deepcopy(box)}}
        self._planned = {"path": current, "sha256": digest, "candidate": candidate}
        return {"image_path": str(current), "goal": goal, "target_text": self.goal,
            "parse_result": {"vision_regions": {"image_size": size}},
            "candidate_result": {"recommended_candidate_id": identifier, "candidates": [candidate]},
            "recommended_target": candidate,
            "pre_click_decision": {"allowed": True, "selected_candidate_id": identifier,
                "selected_element_id": identifier, "selected_click_point": deepcopy(point),
                "reasons": ["current_target_choice_required"], "validation_scope": "pending_semantic_review"},
            "narrow_search_result": {"results": [{"candidate_id": identifier, "element_id": identifier,
                "status": "verified_field_proposed", "refined_click_point": deepcopy(point),
                "coordinate_source": "verified_visual_field", "reasons": ["new_click_review_required"]}]},
            "grounding_evidence": {"evidence_source": "verified_visual_field", "source_sha256": source["sha256"],
                "capture_id": digest, "region_changed_fraction": None, "target_hit_verified": None,
                "task_effect_verified": None},
            "execution_path": {"vision_model_used": False, "local_model_used": False,
                "external_grounding_used": False, "verified_field_grounding_used": True, "action_executed": False}}

    def _review(self, point, identity):
        from .agent_grounding_target import current_agent_grounding
        from app.execution.action_review import current_action_review, validate_assessment
        from app.execution.decision_check import _candidate
        self._identity(identity)
        scope = current_action_review()
        if (current_agent_grounding() is not self or self._planned is None or point != self._field["click_point"]
                or scope is None or scope["context"] != self._context
                or scope["service"] is not self.keyboard_target.proof._service):
            raise ValueError("visual_submit_candidate_review_required")
        envelope = scope["envelope"]
        if (not isinstance(envelope, dict)
                or Path(envelope["frame"]["image_path"]).resolve() != self._planned["path"]
                or envelope["frame"]["sha256"] != self._planned["sha256"]
                or envelope["action"].get("visual_submit_phase") != "reanchor_enter"
                or envelope["action"].get("source_candidate") != _candidate(self._planned["candidate"], point)
                or not validate_assessment(scope["service"], scope["assessment"],
                    envelope=envelope, cancelled=scope["cancelled"])):
            raise ValueError("visual_submit_candidate_review_invalid")
        return scope

    def before_dispatch(self, point, identity):
        if self._claimed:
            raise ValueError("visual_submit_already_claimed")
        self._review(point, identity)
        self._claimed = True


def _current():
    from .agent_grounding_target import current_agent_grounding
    target = current_agent_grounding()
    return target if type(target) is VisualSubmitTarget else None


def prepare_visual_submit(manager, point, review):
    target = _current()
    if target is None:
        return
    from .local_input_policy import current_local_operator_identity
    from app.execution.visual_field_proof import revalidate_visual_field
    scope = target._review(point, current_local_operator_identity(manager))
    if (not target._claimed or target._prepared is not None or target._performed
            or not isinstance(review, dict) or review.get("scope") is not scope):
        raise ValueError("visual_submit_unreviewed_or_consumed")
    review["validate"]()
    revalidate_visual_field(target.keyboard_target.proof, manager)
    target._prepared = review


def perform_visual_submit(controller, manager, point, click_result, *, output):
    target = _current()
    if target is None:
        return
    from .local_keyboard_target import local_keyboard_target_scope
    from .local_input_policy import current_local_operator_identity
    from .key_dispatch import key_dispatch_scope, create_key_dispatch, key_dispatch_from_error
    from .input_sequence_partial import _digest
    if target._prepared is None or target._performed:
        raise ValueError("visual_submit_unprepared_or_consumed")
    target._performed = True
    field, value = target._field, target._value
    rect = field["window_rect"]
    fact = {"schema": "visual_submit.v1", "field_goal": field["field_goal"], "point": deepcopy(point),
        "window_identity": deepcopy(field["window_identity"]),
        "window_rect": [rect[0], rect[1], rect[0]+rect[2], rect[1]+rect[3]],
        "execution_request_id": value["request"]["execution_request_id"],
        "value_request_sha256": value["assessment"]["request_sha256"],
        "input_receipt_sha256": value["request"]["action"]["input_receipt_sha256"],
        "click_result_sha256": _digest(click_result), "key_result": None,
        "key_dispatch": create_key_dispatch("Enter", **point).reference()}
    output["visual_submit"] = fact
    entered = False
    with key_dispatch_scope():
        try:
            if (point != field["click_point"] or not isinstance(click_result, dict)
                    or click_result.get("clicked") is not True or click_result.get("window_point") != point
                    or click_result.get("window_handle") != field["window_identity"]["handle"]):
                raise ValueError("visual_submit_click_binding_changed")
            target._identity(current_local_operator_identity(manager))
            with local_keyboard_target_scope(target.keyboard_target):
                entered = True
                result = controller.press_key("Enter", **point)
            fact["key_result"] = deepcopy(result)
            fact["key_dispatch"] = deepcopy(result.get("key_dispatch"))
            if result.get("pressed") is not True or (fact["key_dispatch"] or {}).get("dispatch") != "completed":
                raise ValueError("visual_submit_key_unconfirmed")
        except Exception as error:
            dispatch = key_dispatch_from_error(error)
            if dispatch is not None or entered:
                fact["key_dispatch"] = dispatch
            fact["error"] = {"type": type(error).__name__, "code": str(error)}
            raise
