"""隔离检查交付包的输入和读取入口依赖；不调用输入、窗口、模型或截图函数。"""
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
    from app.core.editing_keys import EDITING_KEY_CHORDS
    # 全部维护键必须经过真实参数链，但预检不得派发输入。
    editing_keys = []
    for key in EDITING_KEY_CHORDS:
        local._validated_request("press_key", {"key": key, "x": 1, "y": 1})
        editing_keys.append(key)
    routes = {getattr(r, "path", "") for r in application.routes}
    for operation in ("execute_recognition_plan", "type_text", "scroll"):
        if "/action/" + operation not in routes:
            raise ValueError("action route not registered: " + operation)
    # 读取入口延迟加载 OCR，预检必须显式覆盖，避免漏包被握手成功掩盖。
    reader = importlib.import_module("app.operation.screen_reading.captured_text")
    ocr = importlib.import_module("app.core.ocr_service")
    instant = importlib.import_module("app.instant_mcp")
    sequence = importlib.import_module("app.desktop_review.input_sequence")
    fields = importlib.import_module("app.agent.windows_text_field_reader")
    receipts = importlib.import_module("app.instant_receipt")
    if not (callable(sequence.run_input_sequence) and callable(fields.WindowsTextFieldReader.read_field)
            and callable(receipts.compact_receipt)):
        raise ValueError("input sequence dependencies are unavailable")
    instant.InstantCommand.model_validate({"kind": "input_sequence", "request": {
        "field_goal": "Search input", "text": "dependency preflight only", "submit_search": True}}).command()
    condition = importlib.import_module("app.desktop_review.conditional_observation")
    if not callable(condition.observe_until_condition) or not callable(condition.UIATextConditionProbe):
        raise ValueError("conditional observation dependencies are unavailable")
    instant.InstantCommand.model_validate({"kind": "input_sequence", "request": {
        "field_goal": "Search input", "text": "preflight", "submit_search": True},
        "observation_condition": {"text": "Expected result", "control_type": "Text"}}).command()
    if not callable(reader.read_captured_text) or not callable(ocr.ocr_service.scan_image):
        raise ValueError("observation handler is not callable: read_text")
    instant.InstantCommand.model_validate({"kind": "read_text", "max_chars": 10000})
    observation_checked = [{"operation": "read_text", "handler_imported": True,
                            "request_validated": True, "handler_executed": False}]
    # 新操作也走真实参数链，不能仅因旧单击入口可导入就宣称完整。
    click_variants = []
    for kind in ("single", "double", "right"):
        request = {"goal": "dependency preflight only", "click_kind": kind, "dry_run": True}
        instant.InstantCommand.model_validate({"kind": "step", "operation": "execute_recognition_plan",
                                              "request": request})
        validated = local._validated_request("execute_recognition_plan", request)
        if validated["click_kind"] != kind:
            raise ValueError("click kind changed during validation: " + kind)
        click_variants.append({"click_kind": kind, "request_validated": True, "handler_executed": False})
    preparation = importlib.import_module("app.desktop_review.window_preparation")
    close = importlib.import_module("app.core.window_close")
    if not callable(preparation.WindowPreparationMixin.close_launched_window) or not callable(close.post_window_close):
        raise ValueError("window handler is not callable: close_launched_window")
    instant.InstantCommand.model_validate({"kind": "close_launched_window", "handle": 1, "process_id": 1})
    window_checked = [{"operation": "close_launched_window", "handler_imported": True,
                       "request_validated": True, "handler_executed": False}]
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
            "operations": checked, "observation_operations": observation_checked,
            "recognition_click_variants": click_variants, "window_operations": window_checked,
            "editing_keys_validated": editing_keys,
            "input_sequence": {"handler_imported": True, "request_validated": True, "handler_executed": False},
            "local_module_sources": sources,
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
