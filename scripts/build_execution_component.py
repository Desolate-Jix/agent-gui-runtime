"""收集独立执行组件真实依赖，生成安装清单并隔离预检；不派发输入。"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_component_sources import collect_module_sources, copy_component_sources
from app.learning_memory.execution_installation import build_execution_installation_descriptor


ENTRIES = (
    "scripts/start_instant_mcp.py", "scripts/run_local_step_session.py",
    "scripts/start_instant_mcp_admin.py", "scripts/instant_admin_worker.py",
    "scripts/configure_instant_mcp.py", "scripts/check_instant_entrypoints.py",
    "scripts/check_execution_component.py",
    "scripts/learning_benchmark_client.py",
    # PowerShell 启动的维护 worker 不可从 Python 导入图发现，须显式闭合。
    "app/vision/model_workers/vista_openai_server.py",
    # 真实预检动态拼接的兼容入口须明确纳入，不能靠原工作树补包。
    "app/desktop_review/local_direct_step.py", "app/desktop_review/post_action_recovery.py",
    "app/desktop_review/input_sequence.py", "app/desktop_review/form_fill.py",
    "app/desktop_review/conditional_observation.py",
)
RESOURCES = (
    "scripts/setup_instant.ps1", "scripts/configure_instant.ps1",
    "requirements/agent-runtime-win311.txt", "requirements/desktop-runtime-constraints.txt",
    "requirements/pylock.desktop-runtime-win311.toml", "pyproject.toml", "uv.lock",
    "LICENSE", "README.md", "FRIEND_SETUP.md", "AGENT_GUIDE.md", "RELEASE_SCOPE.md",
    "configs/decision-profile.example.json", "docs/development/DECISION_API.md",
    "configs/vision-api-openai-luna.example.json", "docs/development/TASK_PLAN.md",
    "docs/development/EXTERNAL_VISION_BENCHMARK.md",
    "docs/verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md",
    "docs/OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md",
    "configs/model_profiles/vista_4b_transformers.json", "skills/codex-vision-session/SKILL.md",
)


def reject_gui_dependencies(root, sources):
    root = Path(root).resolve()
    for path in sources:
        path = Path(path).resolve()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(name.startswith(("PySide", "PyQt")) for name in names):
                raise ValueError("execution GUI dependency: " + path.relative_to(root).as_posix()
                                 + ":" + str(node.lineno))


def collect_execution_sources(root):
    root = Path(root).resolve()
    # 模型服务启动脚本由配置路径加载，不把字符串依赖误当普通导入闭合。
    worker_entries = tuple(path.relative_to(root).as_posix()
                           for path in sorted((root / "scripts/model_servers").glob("*.py")))
    entries = ENTRIES + worker_entries
    sources = collect_module_sources(root, entries)
    reject_gui_dependencies(root, sources)
    resources = list(RESOURCES)
    resources += [path.relative_to(root).as_posix() for path in
                  sorted((root / "scripts/model_servers").glob("*.ps1"))]
    resources += [path.relative_to(root).as_posix() for path in sorted((root / "schemas").rglob("*.json"))]
    resources += [path.relative_to(root).as_posix() for path in sorted((root / "app").rglob("*.json"))]
    for relative in resources:
        if not (root / relative).is_file():
            raise FileNotFoundError("execution resource missing: " + relative)
    return entries, tuple(sorted(set(resources))), sources


def verify_component(output, report, *, python):
    output, report = Path(output).resolve(), Path(report).resolve()
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory(prefix="execution-isolated-preflight-") as working:
        isolated_root = Path(working) / "payload"
        shutil.copytree(output, isolated_root)
        result = subprocess.run([str(python), "-I", "-B", "-X", "utf8", str(isolated_root / "scripts/check_execution_component.py"),
            "--root", str(isolated_root), "--report", str(report)], cwd=working, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    evidence = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else None
    if result.returncode != 0 or not isinstance(evidence, dict) or evidence.get("passed") is not True:
        raise RuntimeError("execution isolated entrypoint check failed: " + str(report)
                           + "\n" + str(evidence.get("error") if isinstance(evidence, dict) else "report missing")
                           + "\n" + result.stderr.decode("utf-8", errors="strict"))
    return evidence


def build(root, output, *, version, python=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(str(output))
    if not isinstance(version, str) or not version.strip():
        raise ValueError("execution component version is required")
    entries, resources, _ = collect_execution_sources(root)
    source_manifest = copy_component_sources(root, output, entries, resources=resources)
    installation_files = [row["path"] for row in source_manifest["files"]]
    installation_files.append("COMPONENT_SOURCE_MANIFEST.json")
    descriptor = build_execution_installation_descriptor(output, version=version, files=installation_files)
    (output / "execution-installation.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = output.with_name(output.name + "-entrypoint-verification.json")
    evidence = verify_component(output, report, python=python or sys.executable)
    # 安装器严格要求 size 字段；清单置于载荷外，避免自包含摘要和多余文件。
    rows = [{"path": path.relative_to(output).as_posix(), "size": path.stat().st_size,
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(output.rglob("*")) if path.is_file()]
    manifest = output.with_name(output.name + "-payload-manifest.json")
    manifest.write_text(json.dumps({"files": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(output), "version": version, "source_files": len(source_manifest["files"]),
        "payload_files": len(rows), "bytes": sum(row["size"] for row in rows),
        "installer_manifest": str(manifest), "verification_report": str(report),
        "input_executed": evidence["input_executed"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    arguments = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1], arguments.output,
        version=arguments.version, python=arguments.python), ensure_ascii=False))
