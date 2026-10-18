"""沿用原生重学版本服务；候选只修正已绑定的原图，不操作桌面。"""
import re


def validate_request(request):
    shapes = {"list": {"action"}, "read": {"action", "issue_id"},
              "submit": {"action", "issue_id", "expected_baseline_sha256", "changes"}}
    action = request.get("action")
    if not isinstance(action, str) or action not in shapes or set(request) != shapes[action]:
        raise ValueError("learning_feedback requires action=list, read(issue_id), or "
                         "submit(issue_id, expected_baseline_sha256, changes); no extra fields")
    if action != "list":
        issue = request["issue_id"]
        if not isinstance(issue, str) or not re.fullmatch(
                r"interface-issue-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", issue):
            raise ValueError("issue_id must be copied from learning_feedback list")
    if action == "submit":
        digest = request["expected_baseline_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("expected_baseline_sha256 must be the feedback baseline digest")
        changes = request["changes"]
        if not isinstance(changes, dict) or not changes or set(changes) - {"meaning", "recognition_text", "regions"}:
            raise ValueError("changes must contain meaning, recognition_text and/or regions")


def feedback_control(library, request, idempotency_key):
    validate_request(request)
    action = request["action"]
    if action == "list":
        return library.list_interface_relearning_feedback("memory-local")
    if action == "read":
        from app.desktop_review.interface_relearning_gateway import InterfaceRelearningGateway
        value = InterfaceRelearningGateway(library).get("memory-local", request["issue_id"], include_image=False)
        return {**value, "coordinate_scope": "baseline_image_pixels_for_editing_only",
                "image_role": "feedback_baseline_not_live_observation",
                "region_edit_contract": {
                    "list_semantics": "complete_replacement",
                    "existing_region_ids": "preserve IDs for retained regions; omitted regions are removed",
                    "new_region_id_format": "region-user-<lowercase UUID>",
                    "required_fields": ["region_id", "bbox", "name", "kind", "meaning", "recognition_text"],
                    "bbox_coordinate_space": "baseline_image_pixels",
                    "bbox_format": "[x, y, width, height], inside the pinned baseline PNG",
                    "executable_coordinates": False,
                },
                "next": "Inspect the pinned baseline screenshot and issue. Submit semantic/region corrections "
                        "with the baseline digest. For regions follow region_edit_contract; retain all "
                        "unchanged regions in the replacement list. Historical boxes are not executable coordinates. "
                        "Read the original PNG with instant_image(request_id, view=before), or instant_result "
                        "images=both. There is no after image until another action records one. "
                        "For a NEW screenshot use learning_adopt_source instead."}
    value = library.submit_interface_relearning_candidate("memory-local", request["issue_id"],
        request["expected_baseline_sha256"], request["changes"], idempotency_key)
    return {**value, "content_adopted": False, "workflow_references_updated": False,
            "next": "Candidate stored. Compare and explicitly adopt it in the interface editor; "
                    "existing workflow versions remain pinned. No execution was requested."}


def read_baseline_image(library_root, result):
    import hashlib
    from .workspace import MemoryWorkspace
    from app.agent_link.contracts import MAX_LOCAL_PNG_BYTES
    issue = result["issue"]
    with MemoryWorkspace(library_root) as library:
        version = "interface-version-" + issue["baseline_content_sha256"]
        evidence = library.load_interface_content_evidence(issue["interface_id"], version)
        if evidence["sha256"] != result["screenshot"]["sha256"]:
            raise ValueError("feedback baseline digest differs from receipt")
        with library._artifact_file(evidence["image_path"], "重学基线原图").open("rb") as source:
            raw = source.read(MAX_LOCAL_PNG_BYTES + 1)
        if (len(raw) > MAX_LOCAL_PNG_BYTES or not raw.startswith(b"\x89PNG\r\n\x1a\n")
                or hashlib.sha256(raw).hexdigest() != evidence["sha256"]):
            raise ValueError("feedback baseline PNG is invalid or changed")
        return raw
