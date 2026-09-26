"""Agent-only instant runtime dependency and import-boundary checks."""

import ast
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "requirements" / "agent-runtime-win311.txt"
IMPORT_DISTRIBUTIONS = {
    "mcp": "mcp", "fastapi": "fastapi", "pydantic": "pydantic",
    "uvicorn": "uvicorn", "httpx": "httpx", "PIL": "pillow",
    "psutil": "psutil", "loguru": "loguru", "mss": "mss",
    "pywinauto": "pywinauto", "win32api": "pywin32",
    "win32gui": "pywin32", "win32con": "pywin32",
    "win32clipboard": "pywin32", "win32process": "pywin32",
}
RUNTIME_PATHS = (
    "scripts/start_instant_mcp.py", "scripts/run_local_step_session.py",
    "app/instant_mcp.py", "app/desktop_review/host.py",
    "app/desktop_review/single_step_coordinator.py",
    "app/desktop_review/local_direct_step.py", "app/desktop_review/single_step.py",
    "app/api/action.py", "app/core/screenshot.py",
    "app/core/window_manager.py", "app/core/input_controller.py",
    "app/core/process_sampler.py", "app/agent_link/host.py",
)
OPTIONAL = {"rapidocr", "rapidocr-onnxruntime", "paddlepaddle", "torch",
            "torchvision", "transformers", "accelerate", "safetensors",
            "opencv-python", "numpy", "omegaconf", "pyyaml", "pyside6"}


def _requirements():
    return {
        Requirement(line).name.lower(): Requirement(line)
        for raw in MANIFEST.read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    }


def test_runtime_external_imports_have_declared_distributions():
    declared = _requirements()
    imported = set()
    for relative in RUNTIME_PATHS:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.partition(".")[0])
    required = {IMPORT_DISTRIBUTIONS[name] for name in imported & IMPORT_DISTRIBUTIONS.keys()}
    assert required == set(declared)
    assert not set(declared) & OPTIONAL
    assert all(str(value.specifier).startswith("==") for value in declared.values())


def test_agent_import_boundary_without_local_models_or_qt():
    # 独立解释器避免已加载模块绕过拦截；只证明导入边界，不冒充隔离安装验收。
    code = """
import importlib.abc
import sys
blocked = {'PySide6', 'rapidocr', 'rapidocr_onnxruntime', 'paddle',
           'torch', 'torchvision', 'transformers', 'cv2', 'numpy',
           'omegaconf', 'yaml'}
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition('.')[0] in blocked:
            raise ModuleNotFoundError('unexpected optional import: ' + fullname)
sys.meta_path.insert(0, Deny())
for name in ('app.instant_mcp', 'app.desktop_review.host',
             'app.desktop_review.single_step_coordinator',
             'app.desktop_review.local_direct_step', 'app.api.action'):
    __import__(name)
"""
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
