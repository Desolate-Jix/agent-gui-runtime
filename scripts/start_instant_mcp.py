"""即时模式独立 MCP 入口；标准输出仅传输协议。"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--recognition-source", choices=["local", "agent_current", "agent_delegate", "external_api"],
                        default="local")
    parser.add_argument("--delegate-profile")
    parser.add_argument("--allow-local-input", action="store_true",
                        help="Operator explicitly enables existing non-learning direct input, automatic risk interception OFF")
    args = parser.parse_args()
    # SDK 保存协议流，普通 Python print 和本机库的 stdout 改到 stderr。
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    from app.instant_mcp import InstantSession, build_server
    session = InstantSession(ROOT, args.data_dir, args.model_directory, allow_local_input=args.allow_local_input,
                             recognition_source=args.recognition_source, delegate_profile=args.delegate_profile)
    try:
        import anyio
        from mcp.server.stdio import stdio_server
        server = build_server(session)

        async def serve():
            async with stdio_server(stdout=anyio.wrap_file(protocol)) as (read_stream, write_stream):
                await server._lowlevel_server.run(read_stream, write_stream,
                    server._lowlevel_server.create_initialization_options())

        anyio.run(serve)
    finally:
        session.close()


if __name__ == "__main__":
    main()
