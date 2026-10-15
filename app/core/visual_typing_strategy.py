"""只读认证视觉输入策略；返回实际回执验证参数，不授予输入权限。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validated_effective_typing_request(result, request):
    """旧回执保持原义；新策略必须同时通过原焦点结果及本地账本认证。"""
    effective = deepcopy(request)
    if not isinstance(result, dict) or not ({"typing_strategy", "typing_strategy_evidence"} & result.keys()):
        return effective
    service = None
    try:
        from app.agent.native_identity import validate_native_identity_fact
        from app.judgment import DecisionProfile, DecisionService
        from app.judgment.ordinary_review import effective_choice
        strategy, evidence = result["typing_strategy"], result["typing_strategy_evidence"]
        if (type(strategy) is not dict or set(strategy) != {"schema", "requested_clear_existing",
                "effective_clear_existing", "reason", "focus_request_sha256"}
                or strategy["schema"] not in {"visual_typing_strategy.v1", "visual_typing_strategy.v2"}
                or type(strategy["requested_clear_existing"]) is not bool
                or type(strategy["effective_clear_existing"]) is not bool
                or strategy["requested_clear_existing"] is not request["clear_existing"]
                or type(evidence) is not dict or set(evidence) != {"session_directory", "profile", "request", "assessment"}
                or type(evidence["session_directory"]) is not str
                or not Path(evidence["session_directory"]).is_absolute()
                or not Path(evidence["session_directory"]).is_dir()):
            raise ValueError("visual_typing_strategy_invalid")
        focus_request, assessment = evidence["request"], evidence["assessment"]
        action = focus_request["action"]
        ocr = strategy["schema"] == "visual_typing_strategy.v2"
        if ocr:
            from app.execution.visual_field_proof import _ocr_content_state
            state = _ocr_content_state(focus_request)
            if action["field_content_ocr"]["clear_existing"] is not request["clear_existing"]:
                raise ValueError("visual_typing_strategy_ocr_request_invalid")
        else:
            if ("field_content_ocr" in action or action.get("field_content_check") != {
                    "schema": "visual_field_content.v1", "clear_existing": request["clear_existing"]}):
                raise ValueError("visual_typing_strategy_legacy_request_invalid")
            state = assessment["field_content_result"]["choice"]
        field = action["field"]
        rows, proofs = result["steps"], result["field_proofs"]
        focus = rows[0]["receipt"]
        reference = proofs[0]
        native = validate_native_identity_fact(focus["target_identity"],
            target_window_handle=result["target"]["handle"], expected_process_id=result["target"]["process_id"])
        if native is None:
            raise ValueError("visual_typing_strategy_identity_invalid")
        identity = {"handle": native["target_window_handle"], "process_id": native["process_id"],
            "process_create_time": native["process_create_time"]}
        geometry = focus["target_window_geometry"]
        left, top, right, bottom = geometry["rect"]
        data = focus["response"]["data"]
        data = data.get("result", data)
        if (focus_request["mode"] != "execution" or focus_request["phase"] != "after_action"
                or focus_request["step_id"] != focus["step_id"]
                or action["operation"] != "visual_field_check" or action["field_phase"] != "focus"
                or action["focus_stage"] != "after_click"
                or action.get("actual_text") is not None or action.get("value_reading") is not None
                or action.get("input_receipt_sha256") is not None
                or "focus_value_snapshot" in action or "field_freshness_context" in action
                or action["focus_receipt_sha256"] != _digest(focus)
                or field["field_goal"] != request["field_goal"] or field["expected_text"] != request["text"]
                or field["window_identity"] != identity
                or geometry["coordinate_space"] != "screen_pixels" or geometry["rect_format"] != "ltrb"
                or field["window_rect"] != [left, top, right-left, bottom-top]
                or focus["request"]["goal"] != request["field_goal"]
                or rows[0]["name"] != "focus" or rows[0]["operation"] != "execute_recognition_plan"
                or rows[0]["status"] != "returned" or rows[0]["action_executed"] is not True
                or focus["phase"] != "returned" or focus["local_input_scope_closed"] is not True
                or focus["response"]["success"] is not True or data["click_result"]["clicked"] is not True
                or data["selected_click_point_coordinate_space"] != "capture_image_pixels"
                or data["selected_click_point"] != field["click_point"]
                or data["recognition_plan"]["recommended_target"]["bbox"] != field["bbox"]):
            raise ValueError("visual_typing_strategy_focus_binding_invalid")
        frames = focus_request["frames"]
        if (type(frames) is not list or not frames
                or any(frame["window_identity"] != identity for frame in frames)
                or reference["schema"] != "visual_field_proof.v1" or reference["phase"] != "focus"
                or reference["focus_stage"] != "after_click" or reference["source"] != "decision_visual"
                or reference["artifact_is_authorization"] is not False
                or reference["field"] != field or reference["frames"] != frames or reference["frame"] != frames[-1]
                or reference["focus_receipt_sha256"] != action["focus_receipt_sha256"]
                or reference["request_sha256"] != strategy["focus_request_sha256"]
                or assessment["request_sha256"] != strategy["focus_request_sha256"]
                or assessment["decision_format"] != "choice" or assessment["status"] != "completed"
                or assessment["adopted"] is not True or assessment["verdict"] != "success"
                or assessment["disposition"] != "continue"):
            raise ValueError("visual_typing_strategy_proof_invalid")
        if ocr:
            if (reference.get("field_content_ocr") != action["field_content_ocr"]
                    or "field_content_result" in assessment or "field_content_result" in reference):
                raise ValueError("visual_typing_strategy_ocr_proof_invalid")
        elif (reference["field_content_result"] != assessment["field_content_result"]
                or assessment["field_content_result"]["name"] != "field_content"):
            raise ValueError("visual_typing_strategy_legacy_proof_invalid")
        if not ((strategy["reason"] == "verified_empty" and state == "empty"
                    and strategy["effective_clear_existing"] is False)
                or (strategy["reason"] == "replace_existing" and state == "nonempty"
                    and request["clear_existing"] is True and strategy["effective_clear_existing"] is True)
                or (ocr and strategy["reason"] == "ocr_uncertain_replace" and state == "uncertain"
                    and request["clear_existing"] is True and strategy["effective_clear_existing"] is True)):
            raise ValueError("visual_typing_strategy_content_invalid")
        profile = DecisionProfile.model_validate(evidence["profile"])
        if profile.contract_version != "decision_profile.v2" or profile.decision_format != "choice" or profile.mode != "auto":
            raise ValueError("visual_typing_strategy_profile_invalid")
        service = DecisionService(evidence["session_directory"], profile=profile)
        if (service.validate_result(assessment, **focus_request) is not True
                or effective_choice(assessment) != "condition_met"):
            raise ValueError("visual_typing_strategy_authentication_failed")
        effective["clear_existing"] = strategy["effective_clear_existing"]
        return effective
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
        raise ValueError("visual_typing_strategy_invalid") from error
    finally:
        if service is not None:
            service.close()
