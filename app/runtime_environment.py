"""只检查模块可发现性和安装元数据，不导入执行后端或模型。"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from typing import Callable


_PROFILES = {
    "desktop_review": (
        ("PySide6", "PySide6"), ("PIL", "Pillow"), ("pydantic", "pydantic"),
        ("fastapi", "fastapi"), ("httpx", "httpx"), ("uvicorn", "uvicorn"),
        ("psutil", "psutil"),
    ),
    "agent_bridge": (("mcp", "mcp"), ("httpx", "httpx")),
    "windows_runtime": (
        ("loguru", "loguru"), ("pywinauto", "pywinauto"), ("comtypes", "comtypes"),
        ("win32api", "pywin32"), ("win32con", "pywin32"), ("win32gui", "pywin32"),
        ("win32process", "pywin32"), ("win32clipboard", "pywin32"), ("mss", "mss"),
        ("PIL", "Pillow"), ("pydantic", "pydantic"), ("fastapi", "fastapi"),
    ),
}
PROFILE_NAMES = ("all", *_PROFILES)


def inspect_environment(
    profile: str = "all",
    *,
    find_spec: Callable | None = None,
    version: Callable | None = None,
    python_version: tuple[int, ...] | None = None,
    platform: str | None = None,
) -> dict:
    if profile not in PROFILE_NAMES:
        raise ValueError("unknown environment profile")
    discover = find_spec if find_spec is not None else importlib.util.find_spec
    distribution_version = version if version is not None else importlib.metadata.version
    python_info = tuple(sys.version_info[:3]) if python_version is None else python_version
    platform_name = sys.platform if platform is None else platform
    python_supported = python_info[:2] == (3, 11)
    platform_supported = profile not in {"all", "windows_runtime"} or platform_name == "win32"
    entries = dict.fromkeys(
        pair for name in (_PROFILES if profile == "all" else (profile,))
        for pair in _PROFILES[name]
    )
    checks, missing_modules, missing_distributions, probe_errors = [], [], [], []
    for module, distribution in entries:
        item = {"module": module, "distribution": distribution, "version": None,
                "module_discoverable": False, "status": "metadata_present_unverified"}
        try:
            item["module_discoverable"] = discover(module) is not None
            if not item["module_discoverable"]:
                missing_modules.append(module)
                item["status"] = "module_missing"
        except Exception as error:
            # 只保留异常类型，不传播可能含凭据的路径或异常正文。
            probe_errors.append({"module": module, "stage": "find_spec", "error_type": type(error).__name__})
            item["status"] = "probe_failed"
        try:
            installed_version = distribution_version(distribution)
            if not isinstance(installed_version, str) or not installed_version.strip():
                raise ValueError("invalid distribution version")
            item["version"] = installed_version
        except importlib.metadata.PackageNotFoundError:
            if distribution not in missing_distributions:
                missing_distributions.append(distribution)
            if item["status"] == "metadata_present_unverified":
                item["status"] = "distribution_missing"
        except Exception as error:
            probe_errors.append({"module": module, "stage": "distribution_version", "error_type": type(error).__name__})
            item["status"] = "probe_failed"
        checks.append(item)
    blocked = bool(missing_modules or missing_distributions or probe_errors or not python_supported or not platform_supported)
    return {
        "contract_version": "native_environment_metadata_v1",
        "profile": profile,
        "status": "blocked" if blocked else "metadata_present_unverified",
        "interpreter": sys.executable,
        "python_version": ".".join(map(str, python_info)),
        "platform": platform_name,
        "python_supported": python_supported,
        "platform_supported": platform_supported,
        "required_python": ">=3.11,<3.12",
        "checks": checks,
        "missing_modules": missing_modules,
        "missing_distributions": missing_distributions,
        "probe_errors": probe_errors,
        "runtime_verified": False,
        "imports_exercised": False,
        "model_assets_checked": False,
        "artifact_is_authorization": False,
        "limitations": [
            "只检查模块与安装元数据，不验证依赖版本兼容性、导入、DLL、COM、UIA 或真实截图。",
            "不检查识别模型、权重或 GPU；不枚举窗口，不创建执行实例，也不授权输入。",
        ],
    }
