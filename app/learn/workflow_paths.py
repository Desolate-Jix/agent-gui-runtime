"""工作流状态的纯路径解析；不创建存储、锁、目录或加载应用。"""

import os
from pathlib import Path
from typing import Mapping


LEARNING_WORKFLOW_STORE_PATH_ENV = "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_learning_workflow_store_path(
    *,
    project_root: str | Path = _PROJECT_ROOT,
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    """保持既有优先级：环境变量、仓库默认；相对环境路径以仓库为准。"""
    environment = os.environ if environment is None else environment
    configured = str(environment.get(LEARNING_WORKFLOW_STORE_PATH_ENV) or "").strip()
    if configured == ":memory:":
        return None
    root = Path(project_root).resolve()
    if configured:
        return (root / configured).resolve()
    return (root / "runtime_state" / "learning-workflow-runs.json").resolve()
