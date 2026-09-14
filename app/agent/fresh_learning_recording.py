"""从同库首次动作 consume 生成非授权记录，不伪造已审核工作流。"""

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.fresh_learning_action_preview import _parse_projected_recognition
from app.agent.automatic_safety_policy import preview_action_selection


BEFORE_CONTRACT_VERSION = "action_learning_before_v2"
_KEYS = {"contract_version", "runtime_session_id", "observation_id", "intent_id",
         "intent_sha256", "source_lineage", "action", "capture", "geometry",
         "candidate_ref", "gate_decision_ref", "artifact_is_authorization",
         "execute_binding_enabled", "content_sha256"}


def fresh_preview_geometry(preview):
    data = preview.to_dict()
    candidates, _local = _parse_projected_recognition(data["observation_evidence"]["recognition"]["result"])
    decision = preview_action_selection(data)
    selected = [candidate for candidate in candidates.candidates
                if candidate.candidate_id == decision["selected_candidate_id"]]
    if len(selected) != 1:
        raise ValueError("fresh recording requires one verified candidate")
    candidate = selected[0]
    point = decision["selected_click_point"]
    target = data["observation_evidence"]["target"]
    return {
        "bbox": (data["risk"]["scroll_target"]["bbox"] if data["intent"]["semantic_action"] == "scroll_region"
                 else candidate.refined_bbox or candidate.element.bbox.to_dict()),
        "viewport_size": data["observation_evidence"]["capture"]["viewport_size"],
        "click_point": [point["x"], point["y"]],
        "target_window_handle": target["window_handle"],
        "target_process_id": target["process_id"],
    }


def fresh_recording_lineage(claim):
    consume = claim.grounded_consume
    if consume is None or claim.grounded_confirmation is None:
        raise ValueError("fresh recording requires durable consume evidence")
    return {"source_kind": "fresh_learning", "source_sha256": consume.source_sha256,
            "approved_preview_sha256": consume.approved_preview_sha256,
            "fresh_preview_sha256": consume.fresh_preview_sha256,
            "confirmation_id": consume.confirmation_id,
            "consume_content_sha256": consume.content_sha256}


def fresh_target_observation(preview):
    """只取本次已核验候选及其局部识别，不从 Agent 目标生成控件文字。"""
    data = preview.to_dict()
    evidence = data["observation_evidence"]
    candidates, local = _parse_projected_recognition(evidence["recognition"]["result"])
    candidate_id = preview_action_selection(data)["selected_candidate_id"]
    chosen = [item for item in candidates.candidates if item.candidate_id == candidate_id]
    grounded = [item for item in local.results if item.candidate_id == candidate_id]
    if len(chosen) != 1 or len(grounded) != 1 or chosen[0].element_id != grounded[0].element_id:
        raise ValueError("fresh target observation requires the exact selected candidate")
    candidate, result = chosen[0], grounded[0]
    capture = evidence["capture"]
    return {"contract_version": "action_learning_target_observation_v1",
            "capture_id": capture["capture_id"], "screenshot_sha256": capture["screenshot_sha256"],
            "candidate_id": candidate_id, "element_id": candidate.element_id,
            "label": candidate.label, "text": result.matched_text or "", "role": candidate.role}


def build_fresh_learning_before(claim):
    lineage = fresh_recording_lineage(claim)
    preview = claim.grounded_consume.fresh_preview
    data = preview.to_dict()
    capture = data["observation_evidence"]["capture"]
    intent = claim.intent
    result = {
        "contract_version": BEFORE_CONTRACT_VERSION,
        "runtime_session_id": intent.session_id, "observation_id": intent.observation_id,
        "intent_id": intent.intent_id, "intent_sha256": payload_sha256(intent.to_dict()),
        "source_lineage": lineage,
        "action": {"action_id": intent.action_id, "semantic_action": intent.semantic_action},
        "target_observation": fresh_target_observation(preview),
        "capture": {"capture_id": capture["capture_id"], "screenshot_sha256": capture["screenshot_sha256"],
                    "evidence_ref": "fresh-capture:" + data["capture_source"]["source_id"]},
        "geometry": fresh_preview_geometry(preview),
        "candidate_ref": "candidate:" + capture["capture_id"] + ":" + preview_action_selection(data)["selected_candidate_id"],
        "gate_decision_ref": "gate:" + payload_sha256(data["pre_click_decision"]),
        "artifact_is_authorization": False, "execute_binding_enabled": False,
    }
    if intent.semantic_action == "fill_field":
        result["text_parameters_ref"] = intent.text_parameters_ref
        result["text_field_expectation_ref"] = data["text_field_expectation_ref"]
    if intent.semantic_action == "scroll_region":
        result["scroll_parameters"] = intent.scroll_parameters
    return result


def validate_fresh_before_shape(before):
    from app.agent.desktop_backend import FreshExecutionSourceLineage

    extra = ({"text_parameters_ref", "text_field_expectation_ref"}
        if before.get("action", {}).get("semantic_action") == "fill_field" else set())
    if before.get("action", {}).get("semantic_action") == "scroll_region":
        extra = {"scroll_parameters"}
    if set(before) not in (_KEYS | extra, _KEYS | extra | {"target_observation"}) or before.get("contract_version") != BEFORE_CONTRACT_VERSION:
        raise ValueError("fresh before fields are invalid")
    if before["artifact_is_authorization"] is not False or before["execute_binding_enabled"] is not False:
        raise ValueError("fresh before cannot grant authority")
    lineage = before["source_lineage"]
    if not isinstance(lineage, dict) or lineage.get("source_kind") != "fresh_learning":
        raise ValueError("fresh before source kind is invalid")
    FreshExecutionSourceLineage(**{key: value for key, value in lineage.items() if key != "source_kind"})
    if payload_sha256({key: value for key, value in before.items() if key != "content_sha256"}) != before["content_sha256"]:
        raise ValueError("fresh before digest mismatch")
    if set(before["action"]) != {"action_id", "semantic_action"}:
        raise ValueError("fresh before action is invalid")
    if set(before["capture"]) != {"capture_id", "screenshot_sha256", "evidence_ref"}:
        raise ValueError("fresh before capture is invalid")
    if set(before["geometry"]) != {"bbox", "viewport_size", "click_point", "target_window_handle", "target_process_id"}:
        raise ValueError("fresh before geometry is invalid")
    if "scroll_parameters" in extra:
        from app.agent.scroll_parameters import ReviewedScrollParameters, ScrollDispatchParameters
        geometry = before["geometry"]
        ScrollDispatchParameters(ReviewedScrollParameters.from_payload(before["scroll_parameters"]),
            tuple(geometry["bbox"][k] for k in ("x", "y", "w", "h")),
            tuple(geometry["viewport_size"][k] for k in ("width", "height"))).validate_point(tuple(geometry["click_point"]))
    if "text_parameters_ref" in extra:
        from app.agent.text_field_evidence import validate_text_field_expectation_reference

        expected = validate_text_field_expectation_reference(before["text_field_expectation_ref"],
            before["text_parameters_ref"])
        if expected["before"]["capture_id"] != before["capture"]["capture_id"]:
            raise ValueError("fresh before text capture mismatch")
    if "target_observation" in before:
        target = before["target_observation"]
        if (not isinstance(target, dict) or set(target) != {
                "contract_version", "capture_id", "screenshot_sha256", "candidate_id", "element_id",
                "label", "text", "role"}
                or target["contract_version"] != "action_learning_target_observation_v1"
                or any(not isinstance(target[key], str) for key in target)
                or any(target[key] != before["capture"][key] for key in ("capture_id", "screenshot_sha256"))
                or before["candidate_ref"] != "candidate:" + target["capture_id"] + ":" + target["candidate_id"]):
            raise ValueError("fresh before target observation is invalid")


def validate_fresh_before_source(before, snapshot, record):
    from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt

    if not isinstance(record.runtime_receipt, RuntimeFreshResultReceipt):
        raise ValueError("fresh before cannot join a reviewed receipt")
    expected = build_fresh_learning_before(snapshot)
    # 旧账本按原字段核验，不补写或改变其摘要。
    if "target_observation" not in before:
        expected.pop("target_observation")
    expected["content_sha256"] = payload_sha256(expected)
    if before != expected:
        raise ValueError("fresh before differs from authoritative consume")
    receipt = record.runtime_receipt
    if (receipt.source_sha256 != before["source_lineage"]["source_sha256"]
            or receipt.action.model_dump(mode="json") != before["action"]):
        raise ValueError("fresh before differs from authoritative receipt")
    return {"status": "verified", "reason": None,
            "checkpoint_sha256": snapshot.grounded_consume.content_sha256}
