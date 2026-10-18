"""补齐模型子进程必需的 Windows 环境，不修改父进程或全局设置。"""
from __future__ import annotations

import os
from typing import Mapping


def model_worker_environment(environment: Mapping[str, str], *, platform: str | None = None) -> dict[str, str]:
    result = dict(environment)
    if (os.name if platform is None else platform) != 'nt':
        return result
    keys = {key.upper(): key for key in result}
    # 缺少 PATHEXT 时 PowerShell 会把绝对路径的 python.exe 当文档打开。
    extension_key = keys.get('PATHEXT', 'PATHEXT')
    if not result.get(extension_key):
        result[extension_key] = '.EXE'
    # Torch 的 getpass 不能在 Windows 上退回 pwd；账户必须来自操作系统。
    if not any(result.get(keys.get(key, key)) for key in ('LOGNAME', 'USER', 'LNAME', 'USERNAME')):
        username = os.getlogin()
        if not isinstance(username, str) or not username.strip():
            raise OSError('Windows model worker account lookup returned no identity')
        result[keys.get('USERNAME', 'USERNAME')] = username
    return result
