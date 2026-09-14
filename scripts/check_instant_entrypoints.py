"""隔离检查交付包的真实输入入口依赖；不调用输入、窗口、模型或截图函数。"""
import argparse
import importlib
import json
from pathlib import Path
import sys


def check(root):
    root = Path(root).resolve()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    action = importlib.import_module("app.api.action")
    execute = importlib.import_module("app.api.execute")
    local = importlib.import_module("app.desktop_review.local_direct_step")
    keyboard = importlib.import_module("app.desktop_review.local_keyboard_action")
    from fastapi import FastAPI
    application = FastAPI()
    application.include_router(action.router)
    application.include_router(execute.router)
    requests = {
        "execute_recognition_plan": {"goal": "dependency preflight only", "task": "click_target", "dry_run": True},
        "type_text": {"text": "dependency preflight only", "x": 1, "y": 1, "click_before_typing": True, "dry_run": True},
        "press_key": {"key": "Enter", "x": 1, "y": 1},
        "scroll": {"direction": "down", "wheel_clicks": 1, "x": 1, "y": 1, "dry_run": True},
    }
    checked = []
    for operation, request in requests.items():
        handler = keyboard.press_local_key if operation == "press_key" else getattr(action, operation)
        if not callable(handler):
            raise ValueError("input handler is not callable: " + operation)
        local._validated_request(operation, request)
        checked.append({"operation": operation, "handler_imported": True, "request_validated": True,
                        "handler_executed": False})
    routes = {getattr(r, "path", "") for r in application.routes}
    for operation in ("execute_recognition_plan", "type_text", "scroll"):
        if "/action/" + operation not in routes:
            raise ValueError("action route not registered: " + operation)
    sources = {}
    for name, module in list(sys.modules.items()):
        if name == "app" or name.startswith("app.") or name == "modules" or name.startswith("modules."):
            path = getattr(module, "__file__", None)
            if path:
                path = Path(path).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("original workspace import leaked into bundle: " + name)
                sources[name] = path.relative_to(root).as_posix()
    return {"passed": True, "check": "isolated_real_input_entrypoint_imports_v1", "bundle_root": ".",
            "input_executed": False, "screenshots_taken": False, "model_inference_tested": False,
            "operations": checked, "local_module_sources": sources,
            "limitation": "Dependency and request validation only, not real input or end-to-end acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.root)
    except Exception as error:
        result = {"passed": False, "error_type": type(error).__name__, "error": str(error), "input_executed": False}
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "local_module_sources"}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
