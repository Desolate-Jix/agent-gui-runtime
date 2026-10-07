# -*- mode: python ; coding: utf-8 -*-
"""只冻结工作台依赖；动作与识图交给独立安装的维护宿主。"""
import os
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(os.environ['LEARNING_WORKBENCH_SOURCE']).resolve()
QT_WEB = ['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick', 'PySide6.QtWebEngineWidgets']
# 这些推理库只供独立源码宿主使用，GUI 不装载或启动模型。
MODEL_LIBRARIES = ['torch', 'torchvision', 'torchaudio', 'paddle', 'paddleocr',
                  'transformers', 'accelerate', 'onnxruntime', 'rapidocr',
                  'rapidocr_onnxruntime', 'scipy', 'sklearn', 'matplotlib', 'IPython']
datas = [(str(ROOT / 'LICENSE'), '.'),
         (str(ROOT / 'app/learning_memory/translations'), 'app/learning_memory/translations')]
for distribution in ('PySide6', 'Pillow', 'pydantic', 'psutil', 'httpx', 'fastapi', 'loguru', 'numpy', 'opencv-python'):
    datas += copy_metadata(distribution)
analysis = Analysis([str(ROOT / 'scripts/start_learning_workbench.py')], pathex=[str(ROOT)],
                    datas=datas, hiddenimports=[], hookspath=[], runtime_hooks=[],
                    excludes=['tests', *QT_WEB, *MODEL_LIBRARIES], noarchive=False)
pyz = PYZ(analysis.pure)
gui = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
          name='AgentLearningWorkbench', console=False, contents_directory='runtime')
COLLECT(gui, analysis.binaries, analysis.datas, name='AgentLearningWorkbench')
