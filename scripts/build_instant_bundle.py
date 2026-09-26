"""白名单构建小型源码测试包，不复制模型、依赖环境或用户会话。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def retained_app_source(relative):
    relative = Path(relative)
    # 精确排除退役目录和学习启动入口，保留执行共用的宿主、识别与清理依赖。
    excluded_roots = (Path("app/seek"), Path("app/web_panel"))
    return (relative.suffix in {".py", ".json"} and not any(x in relative.parts for x in ("__pycache__", "tests"))
            and relative.as_posix() not in {"app/main.py", "app/api/panel.py",
                "app/desktop_review/entrypoint.py", "app/desktop_review/application.py",
                "app/agent_link/mcp_bridge.py"}
            and not any(relative.is_relative_to(prefix) for prefix in excluded_roots))


def verify_entrypoints(output):
    report = output / "entrypoint-verification.json"
    # 采用隔离 Python 和临时工作目录，不能靠原工作树/PYTHONPATH 补齐漏包。
    with tempfile.TemporaryDirectory(prefix="instant-bundle-preflight-") as working:
        result = subprocess.run([sys.executable, "-I", str(output / "scripts/check_instant_entrypoints.py"),
            "--root", str(output), "--report", str(report)], cwd=working,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    evidence = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else None
    if result.returncode != 0 or not evidence or evidence.get("passed") is not True:
        raise RuntimeError("isolated bundle entrypoint validation failed; inspect " + str(report))
    return evidence


ROOT_FILES = ("LICENSE", ".gitignore", ".gitattributes", "pyproject.toml", "uv.lock",
              "README.md", "AGENT_GUIDE.md", "FRIEND_SETUP.md", "CHANGELOG.md", "RELEASE_SCOPE.md",
              "configs/model_profiles/vista_4b_transformers.json")
SCRIPTS = tuple("scripts/" + name for name in (
    "start_instant_mcp.py", "run_local_step_session.py", "start_instant_mcp_admin.py",
    "instant_admin_worker.py", "setup_instant.ps1", "configure_instant.ps1",
    "configure_instant_mcp.py", "smoke_instant_mcp.py", "check_instant_entrypoints.py",
    "build_instant_bundle.py"))


def collect_sources(root):
    root = Path(root).resolve()
    files = [root / name for name in ROOT_FILES + SCRIPTS]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError("required delivery source is missing: " + str(path))
    files += [p for p in (root / "app").rglob("*") if p.is_file()
              and retained_app_source(p.relative_to(root))]
    for folder, suffixes in (("modules", {".py", ".json"}), ("tests", {".py", ".json"}),
                             ("requirements", {".txt", ".in", ".toml"}),
                             ("scripts/model_servers", {".py", ".ps1"}),
                             ("docs/verification", {".md"}), ("docs/history", {".md"}),
                             ("docs/development", {".md"})):
        files += [p for p in (root / folder).rglob("*") if p.is_file()
                  and p.suffix in suffixes and "__pycache__" not in p.parts]
    for path in files:
        if not path.resolve().is_relative_to(root):
            raise ValueError("delivery source escapes the project root")
    return sorted(set(files))


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("use a new bundle directory; never overwrite an existing delivery")
    files = collect_sources(root)
    output.mkdir(parents=True)
    for source in files:
        target = output / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    verify_entrypoints(output)
    shipped = [output / source.relative_to(root) for source in files]
    shipped.append(output / "entrypoint-verification.json")
    manifest = [{"path": p.relative_to(output).as_posix(), "bytes": p.stat().st_size,
                 "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(set(shipped))]
    (output / "MANIFEST.json").write_text(json.dumps({"format": "instant-source-preview-v1",
        "includes_dependencies": False, "includes_models": False, "includes_user_data": False,
        "files": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(output), "source_files": len(manifest),
            "bytes": sum(p["bytes"] for p in manifest)}


def archive(output):
    output = Path(output).resolve()
    destination = Path(str(output) + ".zip")
    verify_entrypoints(output)
    manifest = json.loads((output / "MANIFEST.json").read_text(encoding="utf-8"))
    paths = []
    for row in manifest["files"]:
        path = (output / row["path"]).resolve()
        if not path.is_relative_to(output) or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("bundle source differs from its manifest")
        paths.append(path)
    # 朋友包不夹带本机配置或验收记录；接收者在自己的电脑生成连接配置。
    paths += [output / "MANIFEST.json"]
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(paths):
            z.write(path, output.name + "/" + path.relative_to(output).as_posix())
    with zipfile.ZipFile(destination) as z:
        if z.testzip() is not None:
            raise ValueError("archive CRC verification failed")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(digest + "  " + destination.name + "\n", encoding="utf-8")
    return {"zip": str(destination), "bytes": destination.stat().st_size, "sha256": digest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-only", action="store_true")
    args = parser.parse_args()
    result = archive(args.output) if args.archive_only else build(Path(__file__).resolve().parents[1], args.output)
    print(json.dumps(result, ensure_ascii=False))
