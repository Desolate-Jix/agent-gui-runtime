from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any


OBSERVATION_RECORD_CONTRACT = "navigation_runtime_observation_record_v1"
OPERATION_RESULT_CONTRACT = "navigation_reading_operation_result_v1"
REPLAY_EXECUTION_CONTEXT_CONTRACT = "reviewed_workflow_replay_execution_context_v1"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class BufferedNavigationRuntimeObserver:
    """缓存 Operation 后的新观察，避免 Controller 立刻重复截图。"""

    def __init__(self, *, capture_current: Callable[[], dict[str, Any]]) -> None:
        self._capture_current = capture_current
        self._latest: dict[str, Any] | None = None
        self._prefetched: dict[str, Any] | None = None

    def observe_current(self) -> dict[str, Any]:
        if self._prefetched is not None:
            record = self._prefetched
            self._prefetched = None
        else:
            record = _validated_record(self._capture_current())
        self._latest = record
        return deepcopy(record["observation"])

    def capture_initial(self) -> dict[str, Any]:
        if self._latest is not None or self._prefetched is not None:
            raise RuntimeError("initial observation has already been captured")
        record = _validated_record(self._capture_current())
        self._latest = record
        self._prefetched = record
        return deepcopy(record)

    def latest_record(self) -> dict[str, Any]:
        if self._latest is None:
            raise RuntimeError("current observation must be captured before Operation")
        return deepcopy(self._latest)

    def capture_after_operation(
        self,
        *,
        expected_interface_id: str | None = None,
    ) -> dict[str, Any]:
        if expected_interface_id:
            record = _validated_record(
                self._capture_current(
                    expected_interface_id=expected_interface_id,
                )
            )
        else:
            record = _validated_record(self._capture_current())
        self._latest = record
        self._prefetched = record
        return deepcopy(record)


class RuntimeNavigationOperationAdapter:
    """把语义计划映射到现有受控 API，不从学习资产复用坐标。"""

    def __init__(
        self,
        *,
        post_json: Callable[[str, dict[str, Any]], dict[str, Any]],
        observer: BufferedNavigationRuntimeObserver,
        app_name: str,
    ) -> None:
        self._post_json = post_json
        self._observer = observer
        self._app_name = _required_text(app_name, "app_name")
        self._captures_by_content: dict[str, list[dict[str, Any]]] = {}

    def execute(
        self,
        plan: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        action = _required_text(plan.get("semantic_action"), "semantic_action")
        replay_context = _validated_replay_context(plan.get("replay_context"))
        if replay_context is not None and action in {"read", "scroll"}:
            return {
                "contract_version": OPERATION_RESULT_CONTRACT,
                "action_type": action,
                "gate_result": {
                    "allowed": False,
                    "reason": "unsupported_reviewed_workflow_replay_action",
                    "details": {"semantic_action": action},
                },
                "action_dispatched": False,
                "action_executed": False,
                "effect_verified": False,
                "post_action_verified": False,
                "replay_context": deepcopy(replay_context),
                "evidence_refs": [],
            }
        if action == "read":
            return self._read(plan=plan, context=context)
        if action == "scroll":
            return self._scroll(plan=plan, context=context)
        return self._transition(
            plan=plan,
            context=context,
            replay_context=replay_context,
        )

    def _read(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        record = self._fresh_record(plan)
        content_id = _required_text(plan.get("content_id"), "content_id")
        target = _read_target(record, content_id)
        self._append_capture(content_id, record)
        report = self._merge_read_report(
            content_id=content_id,
            target=target,
            context=context,
        )
        effect_verified = (
            report.get("wrong_scope_detected") is not True
            and (
                int(report.get("unique_line_count") or 0) > 0
                or report.get("reached_bottom") is True
            )
        )
        return {
            "contract_version": OPERATION_RESULT_CONTRACT,
            "action_type": "read",
            "gate_result": {
                "allowed": True,
                "reason": "read_only_operation",
            },
            "action_dispatched": True,
            "effect_verified": effect_verified,
            "read_report": report,
            "source_freshness": deepcopy(plan["freshness"]),
        }

    def _scroll(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        record = self._fresh_record(plan)
        read_state = (
            context.get("read_state")
            if isinstance(context.get("read_state"), dict)
            else {}
        )
        content_id = _required_text(read_state.get("content_id"), "read_state.content_id")
        target = _read_target(record, content_id)
        bbox = _bbox(target.get("bbox"))
        scroll_bbox = {
            "x": bbox["x"],
            "y": bbox["y"],
            "width": bbox["w"],
            "height": bbox["h"],
        }
        scroll_scope = str(target.get("scroll_scope") or "page").strip()
        payload: dict[str, Any] = {
            "contract_version": "navigation_reading_scroll_request_v1",
            "source_trace_path": plan["freshness"]["trace_path"],
            "scroll_scope": scroll_scope,
            "target_pane": str(target.get("target_pane") or "page"),
            "container_bbox": scroll_bbox,
            "coordinate_window_size": deepcopy(record["window_size"]),
            "direction": "down",
            "wheel_clicks": int(target.get("wheel_clicks") or 5),
            "reason": "Continue the current reviewed read region.",
            "expected_effect": {
                "target_content_must_change_or_reach_bottom": True,
                "non_target_panes_must_remain_stable": True,
            },
            "metadata": {
                "source": "navigation_reading_controller",
                "artifact_is_authorization": False,
            },
            "dry_run": False,
            "enable_verification": True,
        }
        if scroll_scope == "container":
            payload["target_container_id"] = _required_text(
                target.get("target_container_id"),
                "target_container_id",
            )
        response = self._post_json("/action/scroll", payload)
        result = _required_api_result(response, "scroll")
        precondition = (
            result.get("precondition_decision")
            if isinstance(result.get("precondition_decision"), dict)
            else {}
        )
        if precondition.get("decision") != "ALLOW":
            return {
                "contract_version": OPERATION_RESULT_CONTRACT,
                "action_type": "scroll",
                "gate_result": {
                    "allowed": False,
                    "reason": "scroll_precondition_rejected",
                    "details": deepcopy(precondition),
                },
                "action_dispatched": False,
                "effect_verified": False,
                "read_report": _empty_read_report("scroll_precondition_rejected"),
                "source_freshness": deepcopy(plan["freshness"]),
            }

        effect = (
            result.get("scroll_effect_validation")
            if isinstance(result.get("scroll_effect_validation"), dict)
            else {}
        )
        action_dispatched = bool(
            (result.get("execution_path") or {}).get("action_executed")
        )
        expected_interface_id = None
        if action_dispatched and effect.get("wrong_scope_detected") is not True:
            expected_interface_id = str(
                record["observation"].get("interface_id") or ""
            ).strip()
        after_record = self._observer.capture_after_operation(
            expected_interface_id=expected_interface_id,
        )
        self._append_capture(content_id, after_record, scroll_result=result)
        report = self._merge_read_report(
            content_id=content_id,
            target=_read_target(after_record, content_id),
            context=context,
        )
        wrong_scope = bool(
            effect.get("wrong_scope_detected")
            or report.get("wrong_scope_detected")
        )
        reached_bottom = report.get("reached_bottom") is True
        report_captures = [
            item
            for item in report.get("captures") or []
            if isinstance(item, dict)
        ]
        latest_capture = report_captures[-1] if report_captures else {}
        scroll_effect_success = bool(
            action_dispatched
            and not wrong_scope
            and (
                latest_capture.get("scroll_effect_success") is True
                or reached_bottom
            )
        )
        return {
            "contract_version": OPERATION_RESULT_CONTRACT,
            "action_type": "scroll",
            "gate_result": {
                "allowed": True,
                "reason": "scroll_precondition_allowed",
                "details": deepcopy(precondition),
            },
            "action_dispatched": action_dispatched,
            "effect_verified": scroll_effect_success,
            "scroll_dispatch_success": action_dispatched,
            "scroll_effect_success": scroll_effect_success,
            "read_report": report,
            "scroll_effect_validation": deepcopy(effect),
            "source_freshness": deepcopy(plan["freshness"]),
        }

    def _transition(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
        replay_context: dict[str, str] | None,
    ) -> dict[str, Any]:
        current_record = self._fresh_record(plan)
        source_freshness = _normalized_transition_source_freshness(
            plan=plan,
            current_record=current_record,
        )

        def result_lineage(*responses: Any) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "source_freshness": deepcopy(source_freshness),
                "evidence_refs": _response_evidence_refs(*responses),
            }
            if replay_context is not None:
                payload["replay_context"] = deepcopy(replay_context)
            return payload

        interface = (
            context.get("interface")
            if isinstance(context.get("interface"), dict)
            else {}
        )
        surface_context = str(
            plan.get("surface_context")
            or interface.get("surface_context")
            or interface.get("surface_type")
            or interface.get("interface_id")
            or plan.get("semantic_action")
            or ""
        ).strip()
        capture_lineage = {
            "capture_id": source_freshness["capture_id"],
            "screenshot_sha256": source_freshness["screenshot_sha256"],
            "viewport": deepcopy(source_freshness["viewport_size"]),
        }
        body = {
            "agent_mode": "execute",
            "goal": _required_text(plan.get("operation_goal"), "operation_goal"),
            "app_name": self._app_name,
            "capture_live": True,
            "enable_post_click_verification": True,
            "max_execution_attempts": 2,
            "dry_run": True,
            "metadata": {
                "forbid_final_submit": True,
                "artifact_is_authorization": False,
                "require_current_grounding": True,
                "capture_lineage": capture_lineage,
                "semantic_action": plan.get("semantic_action"),
                "surface_context": surface_context,
                "source_interface_id": interface.get("interface_id"),
                "active_flow_started": bool(
                    plan.get("active_flow_started")
                    or context.get("active_flow_started")
                    or interface.get("active_flow_started")
                ),
                "expected_target_interface_id": plan.get(
                    "expected_target_interface_id"
                ),
                **(
                    {"replay_context": deepcopy(replay_context)}
                    if replay_context is not None
                    else {}
                ),
            },
            "write_policy": {
                "path_graph": False,
                "element_memory": True,
                "trace": True,
            },
        }
        dry_response = self._post_json("/action/execute_recognition_plan", body)
        rejection = _pre_click_rejection(dry_response)
        if rejection is not None:
            return {
                "contract_version": OPERATION_RESULT_CONTRACT,
                "action_type": plan.get("semantic_action"),
                "gate_result": {
                    "allowed": False,
                    "reason": rejection["code"],
                    "details": rejection["details"],
                },
                "action_executed": False,
                "post_action_verified": False,
                **result_lineage(dry_response),
            }
        dry_result = _required_api_result(dry_response, "recognition dry-run")
        pre_click = (
            dry_result.get("pre_click_decision")
            if isinstance(dry_result.get("pre_click_decision"), dict)
            else {}
        )
        approved_plan_id = str(dry_result.get("approved_plan_id") or "").strip()
        if pre_click.get("allowed") is not True or not approved_plan_id:
            return {
                "contract_version": OPERATION_RESULT_CONTRACT,
                "action_type": plan.get("semantic_action"),
                "gate_result": {
                    "allowed": False,
                    "reason": str(
                        pre_click.get("reason")
                        or "recognition_plan_not_approved"
                    ),
                    "details": deepcopy(pre_click),
                },
                "action_executed": False,
                "post_action_verified": False,
                **result_lineage(dry_response),
            }

        real_body = deepcopy(body)
        real_body["approved_plan_id"] = approved_plan_id
        real_body["dry_run"] = False
        real_response = self._post_json(
            "/action/execute_recognition_plan",
            real_body,
        )
        safety_rejection = _execution_safety_rejection(real_response)
        if safety_rejection is not None:
            return {
                "contract_version": OPERATION_RESULT_CONTRACT,
                "action_type": plan.get("semantic_action"),
                "gate_result": {
                    "allowed": False,
                    "reason": safety_rejection["reason"],
                    "details": safety_rejection["details"],
                },
                "action_executed": False,
                "post_action_verified": False,
                "approved_plan_id": approved_plan_id,
                **result_lineage(dry_response, real_response),
            }
        real_result = _required_api_result(
            real_response,
            "recognition execution",
        )
        execution_path = (
            real_result.get("execution_path")
            if isinstance(real_result.get("execution_path"), dict)
            else {}
        )
        post_click = (
            real_result.get("post_click_verification")
            if isinstance(real_result.get("post_click_verification"), dict)
            else {}
        )
        action_executed = bool(execution_path.get("action_executed"))
        post_action_verified = bool(post_click.get("verified"))
        if action_executed:
            self._observer.capture_after_operation(
                expected_interface_id=str(
                    plan.get("expected_target_interface_id") or ""
                ).strip()
                or None,
            )
        return {
            "contract_version": OPERATION_RESULT_CONTRACT,
            "action_type": plan.get("semantic_action"),
            "gate_result": {
                "allowed": True,
                "reason": str(pre_click.get("reason") or "approved_plan"),
                "details": deepcopy(pre_click),
            },
            "action_executed": action_executed,
            "post_action_verified": post_action_verified,
            "approved_plan_id": approved_plan_id,
            **result_lineage(dry_response, real_response),
        }

    def _fresh_record(self, plan: dict[str, Any]) -> dict[str, Any]:
        record = self._observer.latest_record()
        observation = record["observation"]
        expected = (
            plan.get("freshness")
            if isinstance(plan.get("freshness"), dict)
            else {}
        )
        if any(
            str(observation.get(key) or "") != str(expected.get(key) or "")
            for key in ("capture_id", "screenshot_sha256", "trace_path")
        ):
            raise RuntimeError("Operation source does not match the current capture")
        return record

    def _append_capture(
        self,
        content_id: str,
        record: dict[str, Any],
        *,
        scroll_result: dict[str, Any] | None = None,
    ) -> None:
        captures = self._captures_by_content.setdefault(content_id, [])
        capture_id = record["observation"]["capture_id"]
        if any(item.get("capture_id") == capture_id for item in captures):
            return
        effect = (
            (scroll_result or {}).get("scroll_effect_validation")
            if isinstance((scroll_result or {}).get("scroll_effect_validation"), dict)
            else {}
        )
        execution_path = (
            (scroll_result or {}).get("execution_path")
            if isinstance((scroll_result or {}).get("execution_path"), dict)
            else {}
        )
        captures.append(
            {
                "capture_id": capture_id,
                "image_path": record["image_path"],
                "trace_path": record["observation"]["trace_path"],
                "ocr_result": deepcopy(record.get("ocr_result") or {}),
                "item_fingerprints": deepcopy(
                    record.get("item_fingerprints")
                    if isinstance(record.get("item_fingerprints"), list)
                    else None
                ),
                "reached_bottom": record.get("reached_bottom") is True,
                "scroll_trace_path": (scroll_result or {}).get("trace_path"),
                "scroll_wheel_clicks": (scroll_result or {}).get("wheel_clicks"),
                "scroll_effect_status": effect.get("status"),
                "scroll_dispatched": (
                    bool(execution_path.get("action_executed"))
                    if scroll_result is not None
                    else None
                ),
                "target_fingerprint_changed": bool(
                    effect.get("target_container_content_changed")
                ),
                "wrong_scope_detected": bool(
                    effect.get("wrong_scope_detected")
                ),
            }
        )

    def _merge_read_report(
        self,
        *,
        content_id: str,
        target: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        selected = next(
            (
                choice
                for choice in context.get("choices") or []
                if isinstance(choice, dict)
                and choice.get("content_id") == content_id
            ),
            {},
        )
        max_scrolls = int(
            selected.get("max_scrolls")
            or (context.get("read_state") or {}).get("max_scrolls")
            or 6
        )
        response = self._post_json(
            "/execute/read_region_batch",
            {
                "target_container_id": str(
                    target.get("target_container_id") or content_id
                ),
                "target_bbox": _bbox(target.get("bbox")),
                "captures": deepcopy(self._captures_by_content[content_id]),
                "max_captures": max(1, min(20, max_scrolls + 1)),
                "stop_after_no_new_content": 2,
                "wrong_scope_detected": False,
                "metadata": {
                    "source": "navigation_reading_controller",
                    "artifact_is_authorization": False,
                },
            },
        )
        return _required_api_data(response, "read region batch")



def _validated_replay_context(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "contract_version",
        "asset_content_sha256",
        "transition_id",
        "selection_sha256",
    }:
        raise ValueError("invalid reviewed workflow replay context")
    asset_content_sha256 = str(value.get("asset_content_sha256") or "").strip()
    transition_id = str(value.get("transition_id") or "").strip()
    selection_sha256 = str(value.get("selection_sha256") or "").strip()
    if (
        value.get("contract_version") != REPLAY_EXECUTION_CONTEXT_CONTRACT
        or not _SHA256_RE.fullmatch(asset_content_sha256)
        or not transition_id
        or not _SHA256_RE.fullmatch(selection_sha256)
    ):
        raise ValueError("invalid reviewed workflow replay context")
    return {
        "contract_version": REPLAY_EXECUTION_CONTEXT_CONTRACT,
        "asset_content_sha256": asset_content_sha256.lower(),
        "transition_id": transition_id,
        "selection_sha256": selection_sha256.lower(),
    }


def _normalized_transition_source_freshness(
    *,
    plan: dict[str, Any],
    current_record: dict[str, Any],
) -> dict[str, Any]:
    observation = current_record.get("observation")
    freshness = plan.get("freshness")
    if not isinstance(observation, dict) or not isinstance(freshness, dict):
        raise ValueError("Operation source freshness is required")
    current_viewport = _normalized_viewport_size(current_record.get("window_size"))
    planned_viewport = freshness.get("viewport_size")
    if planned_viewport is None:
        planned_viewport = freshness.get("viewport")
    viewport_size = (
        _normalized_viewport_size(planned_viewport)
        if planned_viewport is not None
        else current_viewport
    )
    if viewport_size != current_viewport:
        raise ValueError("Operation source viewport does not match the current capture")
    source_freshness = {
        "capture_id": _required_text(observation.get("capture_id"), "capture_id"),
        "screenshot_sha256": _required_text(
            observation.get("screenshot_sha256"),
            "screenshot_sha256",
        ),
        "viewport_size": viewport_size,
    }
    trace_path = str(observation.get("trace_path") or "").strip()
    if trace_path:
        source_freshness["trace_path"] = trace_path
    return source_freshness


def _normalized_viewport_size(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("viewport_size is required")
    width, height = value.get("width"), value.get("height")
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or width <= 0
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height <= 0
    ):
        raise ValueError("viewport_size must be positive")
    return {"width": width, "height": height}


def _response_evidence_refs(*responses: Any) -> list[str]:
    refs: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            refs.add(value.strip())
        elif isinstance(value, list):
            for item in value:
                add(item)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {
                    "trace_path",
                    "trace_paths",
                    "evidence_path",
                    "evidence_paths",
                }:
                    add(child)
                visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for response in responses:
        visit(response)
    return sorted(refs)

def _validated_record(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != OBSERVATION_RECORD_CONTRACT
    ):
        raise ValueError(f"{OBSERVATION_RECORD_CONTRACT} is required")
    observation = (
        value.get("observation")
        if isinstance(value.get("observation"), dict)
        else {}
    )
    if observation.get("contract_version") != "current_interface_observation_v1":
        raise ValueError("current_interface_observation_v1 is required")
    for field in (
        "interface_id",
        "surface_type",
        "capture_id",
        "screenshot_sha256",
        "trace_path",
    ):
        _required_text(observation.get(field), field)
    _required_text(value.get("image_path"), "image_path")
    window_size = value.get("window_size")
    if not isinstance(window_size, dict):
        raise ValueError("window_size is required")
    if int(window_size.get("width") or 0) <= 0 or int(
        window_size.get("height") or 0
    ) <= 0:
        raise ValueError("window_size must be positive")
    targets = value.get("resolved_read_targets")
    if not isinstance(targets, dict):
        raise ValueError("resolved_read_targets is required")
    return deepcopy(value)


def _read_target(record: dict[str, Any], content_id: str) -> dict[str, Any]:
    targets = record.get("resolved_read_targets")
    target = targets.get(content_id) if isinstance(targets, dict) else None
    if not isinstance(target, dict):
        raise RuntimeError(
            f"current observation did not resolve read target: {content_id}"
        )
    _bbox(target.get("bbox"))
    return deepcopy(target)


def _required_api_data(
    response: dict[str, Any],
    operation_name: str,
) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("success") is not True:
        raise RuntimeError(
            f"{operation_name} failed: "
            f"{(response or {}).get('error') if isinstance(response, dict) else response}"
        )
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{operation_name} returned no data")
    return deepcopy(data)


def _required_api_result(
    response: dict[str, Any],
    operation_name: str,
) -> dict[str, Any]:
    data = _required_api_data(response, operation_name)
    result = data.get("result")
    return deepcopy(result) if isinstance(result, dict) else data


def _pre_click_rejection(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict) or response.get("success") is True:
        return None
    error = response.get("error")
    if not isinstance(error, dict) or error.get("code") != "pre_click_rejected":
        return None
    details = error.get("details")
    return {
        "code": "pre_click_rejected",
        "details": deepcopy(details if isinstance(details, list) else []),
    }


def _execution_safety_rejection(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict) or response.get("success") is True:
        return None
    error = response.get("error")
    if not isinstance(error, dict):
        return None
    code = str(error.get("code") or "")
    if code in {"stale_approved_plan", "capture_lineage_mismatch"}:
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        return {
            "reason": code,
            "details": {
                "code": code,
                "message": str(error.get("details") or ""),
                "capture_lineage_validation": data.get("capture_lineage_validation"),
                "trace_path": data.get("trace_path"),
            },
        }
    if code != "recognition_plan_click_failed":
        return None
    message = str(error.get("details") or "")
    if not message.startswith("Bound window foreground verification failed:"):
        return None
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    return {
        "reason": "foreground_window_changed",
        "details": {
            "code": "recognition_plan_click_failed",
            "message": message,
            "trace_path": data.get("trace_path"),
        },
    }


def _bbox(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("current target bbox is required")
    try:
        x = int(value.get("x") or 0)
        y = int(value.get("y") or 0)
        w = int(
            value.get("w")
            if value.get("w") is not None
            else value.get("width")
        )
        h = int(
            value.get("h")
            if value.get("h") is not None
            else value.get("height")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("current target bbox is invalid") from exc
    if w <= 0 or h <= 0:
        raise ValueError("current target bbox must be positive")
    return {"x": x, "y": y, "w": w, "h": h}


def _empty_read_report(reason: str) -> dict[str, Any]:
    return {
        "contract_version": "read_region_batch_v1",
        "stop_reason": reason,
        "completion_status": "blocked",
        "reached_bottom": False,
        "wrong_scope_detected": False,
        "unique_line_count": 0,
    }


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
