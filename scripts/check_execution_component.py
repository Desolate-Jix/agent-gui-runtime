"""树外执行组件预检：真实输入入口与描述一致性，不创建宿主或输入。"""
import argparse
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
import tempfile


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
    return {"passed": True, "dpapi_authenticated": authenticated, "tampered_result_rejected": rejected,
        "binding_mismatch_rejected": mismatched, "readonly_source_unchanged": True,
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
    for name in ("start_instant_mcp", "run_local_step_session", "start_instant_mcp_admin",
                 "instant_admin_worker", "configure_instant_mcp"):
        module = importlib.import_module("scripts." + name)
        if not callable(module.main):
            raise ValueError("execution entrypoint is unavailable: " + name)
        entries[name] = {"imported": True, "main_executed": False}
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
