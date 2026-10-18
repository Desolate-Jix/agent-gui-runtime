"""安装包共用入口：原生工作台、STDIO 桥与只读依赖诊断相互分离。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def gui_arguments(data_dir: Path | None, vision_config: Path | None = None) -> list[str]:
    if data_dir is None:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        if not local.is_absolute():
            raise ValueError("LOCALAPPDATA must be absolute or --data-dir must be supplied")
        data_dir = local / "AgentGuiRuntime"
    root = Path(data_dir).expanduser().resolve()
    config = (root / "configs/vision.json") if vision_config is None else vision_config.expanduser().absolute()
    return ["--state-path", str(root / "inbox.json"), "--review-root", str(root / "reviews"),
            "--listen-port", "0", "--vision-config", str(config)]


def _launch_gui(arguments: list[str]) -> int:
    from app.desktop_review.application import main
    return main(arguments)


def _show_startup_error(kind: str) -> None:
    message = "原生审核工作台无法启动，未自动重置任何数据。\n请运行 AgentReviewBridge.exe --diagnostics 检查安装依赖。\n错误类型：" + kind
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Agent Review 启动失败", 0x10)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--model-worker":
        if len(arguments) < 2 or arguments[1] != "vista":
            argparse.ArgumentParser(prog="AgentReview", description="Agent Review model worker.").error(
                "--model-worker requires the exact worker name: vista"
            )
        from app.vision.model_workers.vista_openai_server import main as vista_main
        return vista_main(arguments[2:])

    parser = argparse.ArgumentParser(description="Agent Review native desktop and Agent Link companion.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--agent-link-mcp", action="store_true", help="Run only the capability-negotiated STDIO learning and memory bridge.")
    modes.add_argument("--diagnostics", action="store_true", help="Inspect installed metadata without creating a GUI or execution runtime.")
    parser.add_argument("--profile", choices=["all", "desktop_review", "agent_bridge", "windows_runtime"])
    parser.add_argument("--data-dir", type=Path, help="Explicit user data directory; never defaults to the installation or working directory.")
    parser.add_argument("--vision-config", type=Path, help="Existing vision configuration for the native desktop; defaults to the user data configs directory.")
    args = parser.parse_args(arguments)
    if args.profile is not None and not args.diagnostics:
        parser.error("--profile requires --diagnostics")
    if args.data_dir is not None and (args.diagnostics or args.agent_link_mcp):
        parser.error("--data-dir is only available for the native desktop")
    if args.vision_config is not None and (args.diagnostics or args.agent_link_mcp):
        parser.error("--vision-config is only available for the native desktop")
    if args.agent_link_mcp:
        if sys.stdin is None or sys.stdout is None:
            raise RuntimeError("STDIO is unavailable; use AgentReviewBridge.exe --agent-link-mcp")
        from app.agent_link.mcp_bridge import run_stdio
        run_stdio()
        return 0
    if args.diagnostics:
        if sys.stdout is None:
            raise RuntimeError("STDIO is unavailable; use AgentReviewBridge.exe --diagnostics")
        from app.runtime_environment import inspect_environment
        report = inspect_environment(profile=args.profile or "all")
        if callable(getattr(sys.stdout, "reconfigure", None)):
            sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "metadata_present_unverified" else 2
    try:
        result = _launch_gui(gui_arguments(args.data_dir, args.vision_config))
    except Exception as error:
        # 启动异常只显示类型，不泄漏可能含凭据的异常正文。
        _show_startup_error(type(error).__name__)
        return 2
    if result != 0:
        _show_startup_error("native_startup_failed")
    return result
