"""只针对显式本地 inbox/state 路径启动原生审核进程。"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start the Qt native human-review workspace.")
    parser.add_argument("--state-path", required=True, help="Explicit Agent Link inbox JSON path.")
    parser.add_argument("--review-root", required=True, help="Explicit directory for immutable reviewer revisions.")
    parser.add_argument("--vision-config", type=Path, help="Existing vision configuration; defaults to configs/vision.json beside the inbox.")
    parser.add_argument("--listen-port", type=int, help="Opt in to the shared 127.0.0.1 Agent receiver; 0 selects an OS-assigned port.")
    arguments = parser.parse_args(argv)
    if arguments.listen_port is not None and not 0 <= arguments.listen_port <= 65535:
        parser.error("--listen-port must be in 0..65535")
    token = secrets.token_urlsafe(32) if arguments.listen_port is not None else os.environ.get("AGENT_LINK_REVIEWER_TOKEN")
    if arguments.listen_port is None and not token:
        parser.error("AGENT_LINK_REVIEWER_TOKEN environment variable is required")
    state_path, review_root = Path(arguments.state_path), Path(arguments.review_root)
    if not state_path.name or str(review_root) in {"", "."}:
        parser.error("--state-path and --review-root must be explicit paths")
    vision_config = (arguments.vision_config or state_path.parent / "configs/vision.json").expanduser().absolute()

    from app.runtime_environment import inspect_environment

    environment = inspect_environment(profile="desktop_review")
    if environment["status"] != "metadata_present_unverified":
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
        print(json.dumps({
            "code": "desktop_dependencies_missing",
            "message": "原生桌面依赖缺失、无法检查，或 Python 版本不受支持；未启动审核程序。",
            "next_action": "Run scripts/check_desktop_environment.py --profile desktop_review with the same interpreter.",
            "environment": environment,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore
    from app.desktop_review.workspace import NativeReviewFacade
    from app.desktop_review.window import ReviewMainWindow, ensure_application

    store = None
    facade = None
    host = None
    coordinator = None
    try:
        application = ensure_application()
        if arguments.listen_port is None:
            store = AgentLinkStore(state_path)
            facade = NativeReviewFacade(AgentLinkService(store, reviewer_token=token), reviewer_token=token, artifact_root=review_root)
            window = ReviewMainWindow(facade)
        else:
            from app.desktop_review.host import DesktopReviewHost
            from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
            host = DesktopReviewHost(state_path, review_root, token, port=arguments.listen_port)
            coordinator = NativeSingleStepCoordinator(review_root, host.facade, host, vision_config_path=vision_config,
                runtime_output_root=state_path.expanduser().resolve().parent / "runtime-output")
            window = ReviewMainWindow(host.facade, connections=host.connections, startup=host.start, shutdown=coordinator.shutdown, single_step=coordinator, application_startup=host.application_startup)
        window.show()
        return application.exec()
    finally:
        # 窗口关闭前后均尝试释放只属于本进程的资源。
        if coordinator is not None:
            coordinator.shutdown()
        elif host is not None:
            host.close()
        elif facade is not None:
            facade.close()
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
