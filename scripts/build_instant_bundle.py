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
    # 退役的是精确目录 app/seek，不是所有名为 seek 的维护依赖或上级目录。
    excluded_roots = (Path("app/seek"), Path("app/web_panel"))
    return (relative.suffix in {".py", ".json"} and not any(x in relative.parts for x in ("__pycache__", "tests"))
            and relative.as_posix() not in {"app/main.py", "app/api/panel.py"}
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


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("use a new bundle directory; never overwrite an existing delivery")
    output.mkdir(parents=True)
    files = [p for p in (root / "app").rglob("*") if p.is_file()
             and retained_app_source(p.relative_to(root))]
    files += [root / p for p in (
        "LICENSE", "pyproject.toml", "uv.lock", "configs/model_profiles/vista_4b_transformers.json",
        "scripts/start_instant_mcp.py", "scripts/run_local_step_session.py",
        "scripts/start_instant_mcp_admin.py", "scripts/instant_admin_worker.py",
        "scripts/setup_instant.ps1", "scripts/configure_instant.ps1",
        "scripts/configure_instant_mcp.py", "scripts/smoke_instant_mcp.py", "scripts/check_instant_entrypoints.py",
        "tests/conftest.py", "tests/test_local_editing_keys.py", "tests/test_instant_mcp.py",
        "tests/test_input_controller.py", "tests/test_text_input_guard.py",
        "tests/test_clipboard_transaction.py", "tests/test_clipboard_bitmap_recovery.py",
        "tests/test_instant_read_text.py", "tests/test_instant_read_text_entrypoint.py",
        "tests/test_recognition_click_kind.py", "tests/test_mouse_click_sequence.py",
        "tests/test_launched_window_close.py", "tests/test_ocr_word_boxes.py",
        "tests/test_local_recognition_policy.py", "tests/test_execution_menu_scope.py",
        "tests/test_uia_provider_pinned_snapshot.py", "tests/test_fresh_action_risk.py",
        "tests/test_window_close_observation.py", "tests/test_post_action_window_transition.py",
        "tests/test_keyboard_focus_diagnostics.py", "tests/test_post_action_recovery.py",
        "tests/test_local_step_observation.py", "tests/test_local_step_timings.py",
        "tests/test_native_menu_ownership.py", "tests/test_capture_window_ownership.py",
        "tests/test_explicit_word_ocr_evidence.py", "tests/test_execution_refine_context.py",
        "tests/test_execution_selected_identity.py", "tests/test_execution_browser_chrome_scope.py",
        "tests/test_execution_control_text_anchor.py", "tests/test_current_control_ocr_binding.py",
        "tests/test_execution_quoted_button_target.py", "tests/test_editable_click_visibility.py",
        "tests/test_named_field_target.py", "tests/test_native_edit_primary.py",
        "tests/test_native_edit_client_geometry.py", "tests/test_mouse_absolute_pixels.py",
        "tests/test_uia_finite_traversal.py", "tests/test_uia_bounded_snapshot.py",
        "tests/test_model_worker_environment.py",
        "tests/test_execution_browser_document_observation.py")]
    files += [p for p in (root / "modules").rglob("*") if p.is_file()
              and p.suffix in {".py", ".json"} and "__pycache__" not in p.parts]
    files += [p for p in (root / "requirements").iterdir() if p.is_file()]
    files += [p for p in (root / "scripts/model_servers").glob("*") if p.is_file() and p.suffix in {".ps1", ".py"}]
    for source in files:
        relative = source.relative_to(root)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(root / "docs/INSTANT_PUBLIC_README.md", output / "README.md")
    shutil.copy2(root / "docs/INSTANT_PUBLIC_AGENT_GUIDE.md", output / "AGENT_GUIDE.md")
    shutil.copy2(root / "docs/EXECUTION_READ_TEXT.md", output / "EXECUTION_READ_TEXT.md")
    shutil.copy2(root / "docs/INSTANT_FRIEND_SETUP.md", output / "FRIEND_SETUP.md")
    shutil.copy2(root / "docs/INSTANT_RELEASE_NOTES.md", output / "FIXES.md")
    shutil.copy2(root / "docs/INSTANT_RELEASE_GITIGNORE", output / ".gitignore")
    contract_docs = ("EXECUTION_WINDOW_TRANSITIONS.md", "EXECUTION_FOCUS_RECOVERY.md",
                     "EXECUTION_WORD_CONTEXT_FIX.md", "EXECUTION_OBSERVATION_RECOVERY.md",
                     "EXECUTION_SELECTION_KEYS.md", "EXECUTION_QUOTED_BUTTON_TARGET.md",
                     "EXECUTION_EDITABLE_CONTEXT_VISIBILITY.md", "EXECUTION_MODEL_ENVIRONMENT.md",
                     "EXECUTION_BROWSER_RETEST_20260921.md")
    for name in contract_docs:
        shutil.copy2(root / "docs" / name, output / name)
    verify_entrypoints(output)
    shipped = [output / source.relative_to(root) for source in files]
    shipped += [output / name for name in ("README.md", "AGENT_GUIDE.md", "EXECUTION_READ_TEXT.md", "FRIEND_SETUP.md", "FIXES.md", ".gitignore", "entrypoint-verification.json")]
    shipped += [output / name for name in contract_docs]
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
