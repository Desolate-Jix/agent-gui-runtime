"""启动明确配置的原 Runtime，标准流不经过本包解析。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


_OS_ENV = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "COMSPEC", "PATHEXT",
           "USERPROFILE", "LOCALAPPDATA", "APPDATA")


class ConfigurationError(ValueError):
    """仅携带固定错误代码，不回显配置值或凭据。"""


def _path(environment, name, *, kind):
    value = environment.get(name, "")
    if not value.strip():
        raise ConfigurationError("configuration_missing:" + name)
    try:
        path = Path(value)
        if not path.is_absolute():
            raise ConfigurationError("path_invalid:" + name)
        path = path.resolve()
        if (kind == "file" and not path.is_file()) or (kind == "directory" and not path.is_dir()):
            raise ConfigurationError("path_invalid:" + name)
        return path
    except (OSError, ValueError):
        raise ConfigurationError("path_invalid:" + name) from None


def _json_object(path, error_code):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError(error_code) from None


def _configuration(environment):
    root = _path(environment, "AGENT_GUI_RUNTIME_ROOT", kind="directory")
    python = _path(environment, "AGENT_GUI_RUNTIME_PYTHON", kind="file")
    vision = _path(environment, "AGENT_GUI_RUNTIME_API_PROFILE", kind="file")
    decision = _path(environment, "AGENT_GUI_RUNTIME_DECISION_PROFILE", kind="file")
    data = _path(environment, "AGENT_GUI_RUNTIME_DATA", kind="output")
    if not environment.get("OPENAI_API_KEY", "").strip():
        raise ConfigurationError("configuration_missing:OPENAI_API_KEY")
    input_allowed = environment.get("AGENT_GUI_RUNTIME_INPUT_ALLOWED", "false")
    if input_allowed not in ("true", "false"):
        raise ConfigurationError("input_setting_invalid")

    # 版本标记仅用于兼容性检查，不替代原安装器或文件认证。
    marker = _json_object(root / "execution-installation.json", "execution_0_1_4_or_0_1_5_required")
    if ((marker.get("schema"), marker.get("component")) != ("execution_installation.v1", "execution")
            or marker.get("version") not in ("0.1.4", "0.1.5")):
        raise ConfigurationError("execution_0_1_4_or_0_1_5_required")
    script = root / "scripts/start_instant_mcp.py"
    if not script.is_file():
        raise ConfigurationError("entrypoint_missing")

    # 本实验只绑定一个 secret；原 Runtime 仍负责完整 profile 校验。
    v = _json_object(vision, "profile_json_invalid:api_profile")
    d = _json_object(decision, "profile_json_invalid:decision_profile")
    if (v.get("api_key_env") != "OPENAI_API_KEY"
            or d.get("api_key_env", "OPENAI_API_KEY") != "OPENAI_API_KEY"
            or d.get("ordinary_review_api_key_env") not in (None, "OPENAI_API_KEY")):
        raise ConfigurationError("profile_requires_OPENAI_API_KEY")

    child_environment = {name: environment[name] for name in _OS_ENV if name in environment}
    child_environment.update(OPENAI_API_KEY=environment["OPENAI_API_KEY"], PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    argv = [str(python), "-I", "-B", "-X", "utf8", str(script),
            "--data-dir", str(data), "--recognition-source", "external_api",
            "--api-profile", str(vision), "--decision-profile", str(decision)]
    if input_allowed == "true":
        argv.append("--allow-local-input")
    return root, python, argv, child_environment


def main():
    if sys.platform != "win32":
        print("agent-gui-extension:windows_only", file=sys.stderr)
        return 2
    try:
        root, python, argv, child_environment = _configuration(os.environ)
        # 探测使用非秘密 OS 环境，不启动 Runtime，也不输出探测载荷。
        probe_environment = {name: child_environment[name] for name in _OS_ENV if name in child_environment}
        try:
            probe = subprocess.run([str(python), "-I", "-B", "-X", "utf8", "-c",
                                    "import sys; print('%s.%s' % sys.version_info[:2])"],
                                   env=probe_environment, capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ConfigurationError("python_probe_failed") from None
        if probe.returncode != 0:
            raise ConfigurationError("python_probe_failed")
        if probe.stdout.strip() != b"3.11":
            raise ConfigurationError("python_3_11_required")
    except ConfigurationError as error:
        print("agent-gui-extension:" + str(error), file=sys.stderr)
        return 2

    try:
        # 不创建代理管道、不读写 MCP 字节；原进程直接继承三个标准流。
        with subprocess.Popen(argv, cwd=root, env=child_environment) as process:
            return process.wait()
    except OSError:
        print("agent-gui-extension:runtime_launch_failed", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
