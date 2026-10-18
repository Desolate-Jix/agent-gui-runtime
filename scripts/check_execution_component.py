"""树外执行组件预检：真实输入入口与描述一致性，不创建宿主或输入。"""
import argparse
import importlib
import json
from pathlib import Path
import sys


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
