"""发布元数据必须与实际 API 声明一致，不启动服务或模型。"""

import json
from pathlib import Path
import tomllib

from app.api.application import create_runtime_app

app = create_runtime_app()


def test_api_and_node_metadata_match_python_project_version():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert app.version == project["version"] == package["version"]


def test_declared_node_entry_point_exists():
    root = Path(__file__).resolve().parents[1]
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    entry = package.get("main")
    assert entry is None or (root / entry).is_file(), f"Node entry point does not exist: {entry}"
