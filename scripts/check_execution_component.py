"""树外执行组件预检：真实输入入口与描述一致性，不创建宿主或输入。"""
import argparse
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
import tempfile


def _check_adaptive_decision_dependencies(session):
    from PIL import Image
    from app.judgment import DecisionProfile, DecisionService
    session.mkdir()
    condition = "Offline adaptive dependency probe."
    calls = []
    frames = []
    for role, color in (("after", "white"), ("observation", "blue")):
        image = session / (role + ".png")
        Image.new("RGB", (4, 3), color).save(image)
        frames.append({"capture_id": "offline-adaptive-" + role, "image_path": str(image),
            "sha256": sha256(image.read_bytes()).hexdigest(), "role": role,
            "window_identity": {"handle": 1, "process_id": 2, "process_create_time": 3.0}})
    context = {"goal": "Read the completed offline result", "step_goal": condition,
        "remaining_plan": ["Read the completed result"], "allowed_states": ["Loading", "Completed"],
        "source_id": "offline-adaptive-source", "source_sha256": sha256(b"offline-source").hexdigest(),
        "wait_policy": {"loading_condition": "A visible loading indicator is present",
                        "completion_excludes_loading": True}}
    round_context = {"assessment_round": 0, "original_receipt_sha256": sha256(b"offline-receipt").hexdigest(),
        "evidence_set_sha256": sha256(b"offline-initial-evidence").hexdigest(),
        "elapsed_ms": 0, "timeout_seconds": 8}
    initial = {"request_id": "offline-adaptive-observe", "execution_request_id": "offline-adaptive-execution",
        "condition": condition, "frames": frames[:1], "review_context": context, "assessment_context": round_context}
    completion = deepcopy(initial)
    completion.update(request_id="offline-adaptive-complete", frames=frames)
    completion["assessment_context"].update(assessment_round=1, elapsed_ms=100,
        timeout_seconds=7, evidence_set_sha256=sha256(b"offline-followup-evidence").hexdigest())
    review = {key: deepcopy(value) for key, value in initial.items() if key != "assessment_context"}
    review["request_id"] = "offline-adaptive-review"
    review["review_context"].pop("wait_policy")
    manual = deepcopy(review)
    manual["request_id"] = "offline-adaptive-always-main"
    manual["review_context"]["review_policy"] = "always_main"

    class OfflineAdaptiveProvider:
        def judge(self, request):
            # 模拟最低层返回，策略、证据读取、持久化和认证均走公开服务。
            calls.append(deepcopy(request))
            waiting = request.get("assessment_context", {}).get("assessment_round") == 0
            probabilities = {"condition_met": 0.01 if waiting else 0.99, "visible_error": 0.01,
                "needs_agent_review": 0.99 if "assessment_context" not in request else 0.01,
                "still_progressing": 0.99 if waiting else 0.01}
            return {"request_sha256": request["request_sha256"], "predicates": {
                name: {"type": "predicate", "probability": probabilities[name]}
                for name in request["enabled_predicates"]},
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "http_elapsed_ms": 0.0, "server_processing_ms": None,
                "provider_request_id": "offline-adaptive-dependency-probe"}

    profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto",
        api_key_env="DECISION_CLOSURE_KEY_UNUSED", auto_conditions=[condition])
    service = DecisionService(session, profile=profile, provider=OfflineAdaptiveProvider())
    try:
        results = [service.evaluate(**binding) for binding in (initial, completion, review)]
        expected = [("uncertain", "observe", False), ("success", "continue", True),
                    ("success", "review_required", False)]
        if (len(calls) != 3 or any(result.get("status") != "completed"
                or result.get("schema_version") != "decision_assessment.v2"
                or (result.get("verdict"), result.get("disposition"), result.get("adopted")) != wanted
                for result, wanted in zip(results, expected))
                or [frame["role"] for frame in calls[1]["frames"]] != ["after", "observation"]
                or calls[0]["enabled_predicates"] != ["condition_met", "visible_error", "needs_agent_review", "still_progressing"]
                or calls[2]["enabled_predicates"] != ["condition_met", "visible_error", "needs_agent_review"]):
            raise ValueError("adaptive decision dependency routing probe failed")
        manual_result = service.evaluate(**manual)
        manual_zero_request = (len(calls) == 3 and manual_result.get("status") == "skipped"
            and manual_result.get("reason") == "decision_always_main"
            and manual_result.get("disposition") == "review_required" and manual_result.get("adopted") is False)
        cached_zero_request = service.evaluate(**completion) == results[1] and len(calls) == 3
        if not manual_zero_request or not cached_zero_request:
            raise ValueError("adaptive decision dependency zero-request policy probe failed")
    finally:
        service.close()
    before = {path.relative_to(session).as_posix(): path.read_bytes()
              for path in session.rglob("*") if path.is_file()}
    reopened = DecisionService(session, profile=profile)
    try:
        authenticated = all(reopened.validate_result(result, **binding)
            for result, binding in zip([*results, manual_result], [initial, completion, review, manual]))
        tampered = deepcopy(results[1])
        tampered["disposition"] = "review_required"
        rejected = not reopened.validate_result(tampered, **completion)
        changed_review = deepcopy(completion)
        changed_review["review_context"]["remaining_plan"] = ["A changed suffix"]
        review_mismatch = not reopened.validate_result(results[1], **changed_review)
        changed_round = deepcopy(completion)
        changed_round["assessment_context"]["elapsed_ms"] += 1
        round_mismatch = not reopened.validate_result(results[1], **changed_round)
        changed_frame = deepcopy(completion)
        changed_frame["frames"][1]["capture_id"] = "another-observation"
        frame_mismatch = not reopened.validate_result(results[1], **changed_frame)
    finally:
        reopened.close()
    after = {path.relative_to(session).as_posix(): path.read_bytes()
             for path in session.rglob("*") if path.is_file()}
    if not all((authenticated, rejected, review_mismatch, round_mismatch, frame_mismatch, before == after)):
        raise ValueError("adaptive decision dependency readonly authentication probe failed")
    return {"passed": True, "profile_contract": profile.contract_version,
        "result_schema": results[0]["schema_version"], "dispositions": [result["disposition"] for result in results],
        "review_success_not_adopted": results[2]["adopted"] is False,
        "always_main_zero_request": manual_zero_request, "cached_replay_zero_request": cached_zero_request,
        "dpapi_authenticated": authenticated, "tampered_result_rejected": rejected,
        "review_context_mismatch_rejected": review_mismatch, "assessment_context_mismatch_rejected": round_mismatch,
        "observation_frame_binding_rejected": frame_mismatch, "readonly_source_unchanged": True,
        "synthetic_provider_calls": len(calls), "network_used": False, "key_required": False,
        "input_executed": False, "synthetic_evidence": True}


def check_decision_dependencies():
    from PIL import Image
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    if not callable(OpenAIDecisionsProvider.judge):
        raise ValueError("decision dependency provider entrypoint unavailable")
    condition = "Offline package dependency probe."
    calls = []

    class OfflineProvider:
        def judge(self, request):
            # 仅返回本探针合成合同，认证与图像读取仍使用真实生产实现。
            calls.append(request)
            return {"request_sha256": request["request_sha256"], "predicates": {
                "condition_met": {"type": "predicate", "probability": 0.99},
                "visible_error": {"type": "predicate", "probability": 0.01}},
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "http_elapsed_ms": 0.0, "server_processing_ms": None, "provider_request_id": "offline-dependency-probe"}

    with tempfile.TemporaryDirectory(prefix="decision-closure-") as temporary:
        session = Path(temporary)
        image = session / "fresh.png"
        Image.new("RGB", (4, 3), "white").save(image)
        binding = {"request_id": "offline-decision-probe", "execution_request_id": "offline-execution-probe",
            "condition": condition, "mode": "execution", "phase": "after_action", "run_id": None,
            "step_id": None, "action": None, "frames": [{"capture_id": "fresh-package-probe",
                "image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(), "role": "after",
                "window_identity": {"handle": 1, "process_id": 2, "process_create_time": 3.0}}]}
        profile = DecisionProfile(mode="auto", api_key_env="DECISION_CLOSURE_KEY_UNUSED", auto_conditions=[condition])
        service = DecisionService(session, profile=profile, provider=OfflineProvider())
        try:
            result = service.evaluate(**binding)
        finally:
            service.close()
        if result.get("status") != "completed" or result.get("adopted") is not True or len(calls) != 1:
            raise ValueError("decision dependency persistence or contract probe failed")
        before = {path.relative_to(session).as_posix(): path.read_bytes()
                  for path in session.rglob("*") if path.is_file()}
        reopened = DecisionService(session, profile=profile)
        try:
            authenticated = reopened.validate_result(result, **binding)
            tampered = deepcopy(result)
            tampered["verdict"] = "failure"
            rejected = not reopened.validate_result(tampered, **binding)
            mismatched = not reopened.validate_result(result, **{**binding, "execution_request_id": "another-execution"})
        finally:
            reopened.close()
        after = {path.relative_to(session).as_posix(): path.read_bytes()
                 for path in session.rglob("*") if path.is_file()}
        if not authenticated or not rejected or not mismatched or before != after:
            raise ValueError("decision dependency readonly authentication probe failed")
        adaptive = _check_adaptive_decision_dependencies(session / "adaptive-v2")
    return {"passed": True, "dpapi_authenticated": authenticated, "tampered_result_rejected": rejected,
        "binding_mismatch_rejected": mismatched, "readonly_source_unchanged": True,
        "adaptive_v2": adaptive,
        "synthetic_provider_calls": len(calls), "network_used": False, "key_required": False,
        "input_executed": False, "synthetic_evidence": True,
        "limitation": "Offline dependency and durable authentication check; no provider accuracy or desktop acceptance"}


def check(root):
    root = Path(root).resolve()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    from app.learning_memory.execution_installation import load_execution_installation
    installation = load_execution_installation(root)
    from app.instant_mcp import build_server
    mcp_version = build_server(None)._lowlevel_server.create_initialization_options().server_version
    if mcp_version != installation.version:
        raise ValueError("MCP version mismatch: actual=" + str(mcp_version)
                         + ", installation=" + installation.version)
    from scripts.check_instant_entrypoints import check as check_inputs
    inputs = check_inputs(root)
    from scripts.check_image_feature_closure import check as check_images
    image_feature = check_images()
    decision_feature = check_decision_dependencies()
    entries = {}
    for name in ("start_instant_mcp", "start_instant_mcp_http", "run_local_step_session", "start_instant_mcp_admin",
                 "instant_admin_worker", "configure_instant_mcp", "execution_client", "update_runtime"):
        module = importlib.import_module("scripts." + name)
        if not callable(module.main):
            raise ValueError("execution entrypoint is unavailable: " + name)
        entries[name] = {"imported": True, "main_executed": False}
    adapter = importlib.import_module("scripts.current_agent_client")
    ordinary = importlib.import_module("scripts.execution_client")
    if not isinstance(adapter.CurrentAgentClient, type) or not issubclass(
            adapter.CurrentAgentClient, ordinary.ExecutionClient):
        raise ValueError("current Agent session adapter is unavailable")
    entries["current_agent_client"] = {"imported": True, "constructed": False}
    qt = [name for name in sys.modules if name.startswith(("PySide", "PyQt"))]
    if qt:
        raise ValueError("execution imported Qt: " + ", ".join(qt))
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("app.", "modules.", "scripts.")) and getattr(module, "__file__", None):
            if not Path(module.__file__).resolve().is_relative_to(root):
                raise ValueError("original source leaked into execution component: " + name)
    return {"passed": True, "check": "execution_component_entrypoints.v1", "version": installation.version,
        "mcp_server_version": mcp_version,
        "image_feature_closure": image_feature,
        "decision_feature_closure": decision_feature,
        "isolated_real_input_entrypoints": inputs, "entrypoints": entries,
        "qt_imported": False, "input_executed": False, "host_started": False,
        "interpreter": sys.executable, "python_isolated": bool(sys.flags.isolated),
        "publisher_verified": False,
        "limitation": "Dependency validation with an existing interpreter; no fresh environment install or real input acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.root)
    except Exception as error:
        result = {"passed": False, "error_type": type(error).__name__, "error": str(error),
                  "input_executed": False, "host_started": False}
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "isolated_real_input_entrypoints"}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
