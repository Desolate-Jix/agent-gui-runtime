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
        self._source = self._candidate.evidence_source
        self._planned = False
        self._claimed = False
        self._pending_review = None
        self._pre_action_source = None
        self._main_pre_action = None
        self._main_fresh = None

    @property
    def goal(self):
        return self._state["goal"]

    @property
    def input_claimed(self):
        return self._claimed

    def review_target_identity(self, action):
        """保留旧内部接口；定位备选不再自动变成身份类别。"""
        if current_agent_grounding() is not self or action.get("field_goal", action.get("goal")) != self.goal:
            raise ValueError("agent_grounding_identity_goal_mismatch")
        return None

    def review_target_check(self, action):
        """原目标决定核验对象，当前定位只提供尚未核实的外观和容器描述。"""
        from app.judgment.target_check import grounding_target_check
        if current_agent_grounding() is not self or action.get("field_goal", action.get("goal")) != self.goal:
            raise ValueError("agent_grounding_target_check_goal_mismatch")
        if self._state["configuration"].get("source") != "external_api" or self._source != "api_visual":
            return None
        capture = self._state["capture"]
        current = validate_grounding_result(self._state["result"], request_id=self._state["request_id"],
            capture_id=capture["capture_id"], image_size=(capture["image_size"]["width"], capture["image_size"]["height"]))
        if current.model_dump() != self._result.model_dump():
            raise ValueError("agent_grounding_target_description_changed")
        if current.target_description is None:
            return None
        return grounding_target_check(self.goal, current.target_description.model_dump(),
            input_field=action.get("kind") == "input_sequence")

    def _identity(self, identity):
        expected = self._state["capture"]["window_identity"]
        if (identity.get("target_window_handle") != expected["handle"]
                or identity.get("process_id") != expected["process_id"]
                or identity.get("process_create_time") != expected["process_create_time"]):
            raise ValueError("agent_grounding_identity_changed")
        if self._main_pre_action is not None:
            self._main_pre_action.validate()
        elif time.time() >= self._state["expires_at"]:
            raise ValueError("agent_grounding_request_expired")

    def _resume_main_pre_action(self, approval):
        from app.execution.main_pre_action_approval import MainPreActionApproval
        if (type(approval) is not MainPreActionApproval or approval.source is not self._pre_action_source
                or approval.source.target is not self or self._claimed or self._main_pre_action is not None):
            raise ValueError('main_pre_action_target_binding_invalid')
        approval.validate()
        self._main_pre_action = approval
        self._planned = False
        self._pending_review = None

    def _eligible_review(self):
        from app.execution.action_review import (current_action_review, normalize_action_review_context,
            review_preflight)
        from app.judgment.service import DecisionService
        try:
            scope = current_action_review()
            if scope is None or current_agent_grounding() is not self:
                return None
            service = scope["service"]
            if (not isinstance(service, DecisionService) or service.profile.decision_format != "choice"
                    or time.perf_counter_ns() >= scope["deadline_ns"]
                    or scope["cancelled"] and scope["cancelled"]()):
                return None
            context = normalize_action_review_context(scope["context"])
            step = next(row for row in context["plan"]["steps"] if row["step_id"] == context["step_id"])
            if (step["action"].get("field_goal", step["action"].get("goal")) != self.goal
                    or review_preflight(service)["ready"] is not True):
                return None
            return scope
        except (KeyError, TypeError, ValueError, OSError, RuntimeError):
            return None

    def _validate_pending_review(self, identity):
        from app.execution.action_review import (build_action_review, current_action_review,
            validate_assessment)
        from app.judgment.service import decision_profile_sha256
        pending = self._pending_review
        scope = current_action_review()
        if (current_agent_grounding() is not self or scope is not pending["scope"]
                or scope["service"] is not pending["service"]
                or scope["context"] != pending["context"] or scope["deadline_ns"] != pending["deadline_ns"]
                or scope["cancelled"] is not pending["cancelled"]
                or self._state != pending["state"] or self._candidate.model_dump() != pending["original_candidate"]
                or self._source != pending["candidate"]["source"]):
            raise ValueError("agent_grounding_candidate_review_binding_invalid")
        envelope = scope["envelope"]
        if not isinstance(envelope, dict):
            raise ValueError("agent_grounding_candidate_review_required")
        frame, action = envelope["frame"], envelope["action"]
        context, service = pending["context"], pending["service"]
        step = next(row for row in context["plan"]["steps"] if row["step_id"] == context["step_id"])
        original = Path(self._state["capture"]["image_path"]).read_bytes()
        if sha256(original).hexdigest() != self._state["capture"]["sha256"]:
            raise ValueError("agent_grounding_source_hash_mismatch")
        if (Path(frame["image_path"]).resolve() != pending["image_path"] or frame["sha256"] != pending["sha256"]
                or action.get("operation") != "execute_recognition_plan" or action.get("goal") != self.goal
                or action.get("source_candidate") != pending["candidate"]
                or action.get("permitted_action") != step["action"]
                or action.get("click_kind") != step["action"].get("click_kind", "single")
                or decision_profile_sha256(service.profile) != pending["profile_sha256"]):
            raise ValueError("agent_grounding_candidate_review_binding_invalid")
        with Image.open(frame["image_path"]) as image:
            if image.size != pending["dimensions"]:
                raise ValueError("agent_grounding_viewport_changed")
        selected = {**deepcopy(pending["candidate"]), "capture_id": frame["capture_id"]}
        expected = build_action_review(scope="candidate", plan=context["plan"], step=step,
            run_id=context["run_id"], attempt_id=context["attempt_id"], capture=frame, identity=identity,
            candidate=selected, action=action, profile_sha256=pending["profile_sha256"],
            deadline_ns=pending["deadline_ns"])
        if (envelope != expected or not validate_assessment(service, scope["assessment"],
                envelope=envelope, cancelled=scope["cancelled"])
                or current_action_review() is not scope or current_agent_grounding() is not self):
            raise ValueError("agent_grounding_candidate_review_required")
        if (time.perf_counter_ns() >= pending["deadline_ns"]
                or pending["cancelled"] and pending["cancelled"]()):
            raise ValueError("agent_grounding_candidate_review_required")
        self._identity(identity)

    def plan(self, *, image_path, goal, identity, main_capture_completed_ns=None):
        self._identity(identity)
        if self._main_pre_action is not None and self._main_fresh is not None:
            raise ValueError('main_pre_action_fresh_capture_already_bound')
        if goal != self.goal:
            raise ValueError("agent_grounding_goal_mismatch")
        capture = self._state["capture"]
        baseline = (self._main_pre_action.source.envelope['frame']
            if self._main_pre_action is not None else capture)
        original = Path(baseline["image_path"]).read_bytes()
        if sha256(original).hexdigest() != baseline["sha256"]:
            raise ValueError("agent_grounding_source_hash_mismatch")
        current_bytes = Path(image_path).read_bytes()
        review_scope = None
        with Image.open(BytesIO(original)) as source, Image.open(BytesIO(current_bytes)) as current:
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
                if self._main_pre_action is not None:
                    raise ValueError('main_pre_action_target_region_changed')
                review_scope = self._eligible_review()
                if review_scope is None:
                    raise ValueError("agent_grounding_target_region_changed")
        point = self._candidate.click_point.model_dump()
        bbox = {"x": box.x, "y": box.y, "w": box.width, "h": box.height}
        element_id = "agent-" + self._candidate.id
        candidate = {"candidate_id": self._candidate.id, "element_id": element_id,
            "text": self._candidate.label, "score": self._candidate.confidence,
            "capture_id": capture["capture_id"], "viewport_size": self._result.image_size.model_dump(),
            "source": self._source, "bbox": bbox, "click_point": point,
            "freshness": {"status": "pending_semantic_review" if review_scope is not None else "revalidated",
                "source_sha256": capture["sha256"], "current_sha256": sha256(current_bytes).hexdigest(),
                "expires_at": self._state["expires_at"], "region_changed_fraction": changed},
            "bbox_refine_reason": self._source + "_bbox", "refined_bbox": bbox,
            "element": {"element_id": element_id, "text": self._candidate.label, "bbox": bbox}}
        pre_click = {"allowed": True, "selected_candidate_id": self._candidate.id,
            "selected_element_id": element_id, "selected_click_point": point,
            "reasons": ["agent_selected_target", "candidate_semantic_review_pending" if review_scope is not None else "current_region_consistent"],
            "validation_scope": "identity_geometry_pending_semantic_review" if review_scope is not None else
                "identity_geometry_and_region_consistency_not_semantic_hit"}
        self._pending_review = None
        if review_scope is not None:
            from app.execution.decision_check import _candidate
            from app.judgment.service import decision_profile_sha256
            self._pending_review = {"scope": review_scope, "service": review_scope["service"],
                "context": deepcopy(review_scope["context"]), "deadline_ns": review_scope["deadline_ns"],
                "cancelled": review_scope["cancelled"],
                "profile_sha256": decision_profile_sha256(review_scope["service"].profile),
                "state": deepcopy(self._state), "original_candidate": self._candidate.model_dump(),
                "candidate": _candidate(candidate, point), "image_path": Path(image_path).resolve(),
                "sha256": sha256(current_bytes).hexdigest(), "dimensions": expected_size}
        self._planned = True
        if self._main_pre_action is not None and main_capture_completed_ns is not None:
            if (type(main_capture_completed_ns) is not int
                    or main_capture_completed_ns < self._main_pre_action.issued_ns
                    or not main_capture_completed_ns <= time.perf_counter_ns()
                    or time.perf_counter_ns() - main_capture_completed_ns >= 2_000_000_000):
                raise ValueError('main_pre_action_fresh_capture_expired')
            self._main_fresh = {'image_path': str(Path(image_path).resolve()),
                'sha256': sha256(current_bytes).hexdigest(), 'checked_ns': main_capture_completed_ns,
                'region_changed_fraction': changed}
        return {"image_path": str(image_path), "goal": goal, "target_text": self._candidate.label,
            "parse_result": {"vision_regions": {"image_size": self._result.image_size.model_dump()}},
            "candidate_result": {"recommended_candidate_id": self._candidate.id, "candidates": [candidate]},
            "recommended_target": candidate, "pre_click_decision": pre_click,
            "narrow_search_result": {"results": [{"candidate_id": self._candidate.id,
                "element_id": element_id, "status": "agent_proposed", "refined_click_point": point,
                "coordinate_source": self._source, "reasons": ["not_local_ocr_corroborated"]}]},
            "grounding_evidence": {"request_id": self._state["request_id"], "capture_id": capture["capture_id"],
                "source_sha256": capture["sha256"], "region_changed_fraction": changed,
                "source": self._state["configuration"]["source"], "evidence_source": self._source,
                "target_hit_verified": None,
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
        if self._pending_review is not None:
            self._validate_pending_review(identity)
        if self._main_pre_action is not None:
            self._validate_main_fresh()
            self._main_pre_action.consume()
        self._claimed = True

    def _validate_main_fresh(self):
        self._main_pre_action.validate()
        fresh = self._main_fresh
        if (fresh is None or time.perf_counter_ns() - fresh['checked_ns'] >= 2_000_000_000
                or sha256(Path(fresh['image_path']).read_bytes()).hexdigest() != fresh['sha256']):
            raise ValueError('main_pre_action_fresh_capture_expired')
        return True


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
    from .visual_submit_target import VisualSubmitTarget
    if type(target) not in {AgentGroundingTarget, VisualSubmitTarget} or _SCOPE.get() is not None:
        raise ValueError("agent_grounding_scope_invalid")
    scope = {"target": target, "owner": get_ident(), "active": True}
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope["active"] = False
        _SCOPE.reset(token)
