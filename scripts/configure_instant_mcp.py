"""为解压后的即时包生成本机通用 MCP 与 Codex 配置，不改 Agent 全局设置。"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--enable-local-input", action="store_true",
                        help="Explicitly include --allow-local-input in generated config")
    parser.add_argument("--administrator", action="store_true",
                        help="Use the UAC administrator stdio bridge; operator confirmation required")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.python.is_file() or not args.model_directory.is_dir():
        parser.error("Python executable and model directory must exist")
    sys.path.insert(0, str(root))
    from app.desktop_review.model_setup import _model_directory, ModelSetupError
    try:
        _model_directory(args.model_directory.resolve())
    except ModelSetupError as error:
        parser.error(str(error))
    entrypoint = "start_instant_mcp_admin.py" if args.administrator else "start_instant_mcp.py"
    arguments = [str(root / "scripts" / entrypoint), "--data-dir", str(args.data_dir.resolve()),
                 "--model-directory", str(args.model_directory.resolve())]
    if args.enable_local_input:
        arguments.append("--allow-local-input")
    server = {"command": str(args.python.resolve()), "args": arguments,
              "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}}
    (root / "mcp-config.local.json").write_text(json.dumps({"mcpServers": {"agent-review-instant": server}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    q = lambda value: json.dumps(value, ensure_ascii=False)
    (root / "mcp-config.local.toml").write_text('[mcp_servers.agent-review-instant]\ncommand = '
        + q(server["command"]) + '\nargs = ' + q(arguments)
        + ('\nstartup_timeout_sec = 180\ntool_timeout_sec = 30\n' if args.administrator else '\nstartup_timeout_sec = 30\ntool_timeout_sec = 30\n')
        + '\n[mcp_servers.agent-review-instant.env]\nPYTHONUTF8 = "1"\nPYTHONIOENCODING = "utf-8"\n', encoding="utf-8")
    print(str(root / "mcp-config.local.json"))


if __name__ == "__main__":
    main()
