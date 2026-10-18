# -*- mode: python ; coding: utf-8 -*-
"""原生工作台与学习桥共用依赖目录，不复制开发数据。"""
from pathlib import Path
import os
import sys
import json
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata
ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "packaging"))
from qt_pruning import prune_qt_webengine
ENTRY = ROOT / "scripts" / "start_agent_review.py"
RETIRED_MODULES = ("app.main", "app.api.panel", "app.web_panel", "app.seek",
                   "scripts.start_desktop_review", "scripts.model_servers.vista_openai_server")
QTWEBENGINE_MODULES = ("PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets")
def application_modules():
    modules = []
    for source in sorted((ROOT / "app").rglob("*.py")):
        relative = source.relative_to(ROOT).with_suffix("")
        if "tests" not in relative.parts and "__pycache__" not in relative.parts:
            parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
            module = ".".join(parts)
            if not any(module == retired or module.startswith(retired + ".") for retired in RETIRED_MODULES):
                modules.append(module)
    return modules
RUNTIME_DISTRIBUTIONS = ("PySide6", "Pillow", "pydantic", "fastapi", "httpx", "uvicorn", "psutil", "mcp", "loguru", "pywinauto", "comtypes", "pywin32", "mss", "rapidocr-onnxruntime", "paddlepaddle", "torch")
RUNTIME_PACKAGES = ("PySide6", "PIL", "pydantic", "fastapi", "httpx", "uvicorn", "psutil", "mcp", "loguru", "pywinauto", "comtypes", "mss", "rapidocr_onnxruntime", "rapidocr", "omegaconf", "paddle", "torch", "torchvision", "transformers", "accelerate", "tokenizers", "safetensors", "huggingface_hub", "numpy")
hiddenimports = application_modules() + list(RUNTIME_PACKAGES) + ["win32api", "win32con", "win32gui", "win32process", "win32clipboard", "mcp.server", "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on"]
# Auto 模型映射为惰性导入，显式收集现有 VISTA 架构和处理器，不打包用户权重。
hiddenimports += [
    "app.vision.model_workers.vista_openai_server",
    "transformers.models.qwen3_5.configuration_qwen3_5",
    "transformers.models.qwen3_5.modeling_qwen3_5",
    "transformers.models.qwen3_5.tokenization_qwen3_5",
    "transformers.models.qwen3_vl.processing_qwen3_vl",
    "transformers.models.qwen3_vl.video_processing_qwen3_vl",
    "transformers.models.qwen2_vl.image_processing_qwen2_vl_fast",
    "transformers.models.qwen2_vl.image_processing_qwen2_vl",
]
datas, binaries = [(str(ROOT / "LICENSE"), ".")], []
datas.append((str(ROOT / "configs" / "model_profiles" / "vista_4b_transformers.json"), "configs/model_profiles"))
for package in RUNTIME_PACKAGES:
    datas += collect_data_files(package, include_py_files=False, excludes=["**/tests/**", "**/test/**"])
    binaries += collect_dynamic_libs(package)
# 从不受构建工具污染的运行环境清单复制元数据与发行包自带许可。
runtime_manifest = Path(os.environ["AGENT_REVIEW_RUNTIME_MANIFEST"])
runtime_inventory = json.loads(runtime_manifest.read_text(encoding="utf-8"))
for distribution in sorted({item["name"] for item in runtime_inventory["packages"]}):
    datas += copy_metadata(distribution)
datas.append((str(runtime_manifest), "."))
# 仅剔除已清单证明且当前 Widgets 入口没有导入的 QtWebEngine 组件与专属 Chromium 资源。
datas = prune_qt_webengine(datas)
binaries = prune_qt_webengine(binaries)
analysis = Analysis([str(ENTRY)], pathex=[str(ROOT)], binaries=binaries, datas=datas, hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["tests", *RETIRED_MODULES, *QTWEBENGINE_MODULES], noarchive=False)
pyz = PYZ(analysis.pure)
gui = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="AgentReview", console=False)
bridge = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="AgentReviewBridge", console=True, hide_console="hide-early")
# hooks 可能在 Analysis 后重新加入二进制；COLLECT 前再次使用同一精确规则。
collect_binaries = prune_qt_webengine(analysis.binaries)
collect_datas = prune_qt_webengine(analysis.datas)
COLLECT(gui, bridge, collect_binaries, collect_datas, name="AgentReview")
